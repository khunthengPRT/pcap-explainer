#!/usr/bin/env python3
"""
ue_events.py - per-UE event ledger for an F1 + NG capture: handovers, context releases and
RRC re-establishments, with causes, broken down per lap and keyed to a stable UE identity.

Identity: the capture is searched for the UE's real subscriber id (SUCI/SUPI -> MSIN). Lab UEs that
were already registered before the capture started never send a SUCI, only a 5G-GUTI / 5G-S-TMSI, so
when no MSIN is present the script falls back to a "TMSI chain": the AMF hands out a new 5G-GUTI in
each Registration Accept, and every Registration Request quotes the previous one, so the chain of
old->new TMSIs stitches all the RRC connections of one physical UE together. That chain is the
primary key; the MSIN column says "not in capture" rather than guessing.

Usage:
    python3 ue_events.py capture.pcapng [--out DIR] [--tz Asia/Tokyo] [--ring 101,202,...]

Outputs (in --out, default ./ue_out):
    ue_events.csv      one row per UE per lap (the table)
    ue_events.md       the same table, ready to paste
    ue_identity.csv    every RRC connection: CU/DU/C-RNTI/AMF ids mapped to the UE key
    ue_events.json     everything, for further processing
"""
import argparse, collections, csv, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ho_analyze import (read_capture, sctp_user_messages, ies, find, analyze, fmt_ts,   # noqa: E402
                        PPID_F1AP, PPID_NGAP, F1PDU, NGPDU, IE_CAUSE, IE_CU_ID, IE_DU_ID, IE_CRNTI)

IE_AMF_UE, IE_RAN_UE, IE_NAS, IE_NG_CAUSE = 10, 85, 38, 15
NAS_MT = {0x41: 'RegistrationRequest', 0x42: 'RegistrationAccept', 0x43: 'RegistrationComplete',
          0x54: 'ConfigurationUpdateCommand',
          0x45: 'DeregistrationRequest(UE)', 0x47: 'DeregistrationRequest(network)',
          0x4c: 'ServiceRequest', 0x4e: 'ServiceAccept', 0x5d: 'IdentityResponse'}


# ----------------------------------------------------------------------------- NAS
def nas_plain(nas):
    """Strip the 5GS NAS security header (7E <sht> <MAC:4> <SN:1>) if present."""
    if len(nas) >= 8 and nas[0] == 0x7e and nas[1] in (1, 2, 3, 4):
        return nas[7:]
    return nas


def mobile_identity(buf):
    """-> (kind, value). kind: 'suci-msin' | 'guti' | 's-tmsi' | other."""
    if not buf:
        return None, None
    t = buf[0] & 0x07
    if t == 1:                                    # SUCI
        if len(buf) < 8:
            return 'suci', None
        scheme = buf[7] & 0x0f if len(buf) > 7 else None
        if (buf[0] >> 4) & 0x07 == 0 and scheme == 0:     # IMSI + null scheme -> MSIN in the clear
            digits = ''
            for b in buf[8:]:
                digits += '%d%d' % (b & 0x0f, b >> 4)
            return 'suci-msin', digits.rstrip('f')
        return 'suci', buf.hex()
    if t == 2 and len(buf) >= 11:                 # 5G-GUTI: PLMN(3) region(1) set+ptr(2) 5G-TMSI(4)
        return 'guti', int.from_bytes(buf[7:11], 'big')
    if t == 4 and len(buf) >= 7:                  # 5G-S-TMSI: set+ptr(2) 5G-TMSI(4)
        return 's-tmsi', int.from_bytes(buf[3:7], 'big')
    return 'id%d' % t, buf.hex()


def parse_nas(p):
    """-> (name, identity_kind, identity_value) for the messages that carry a UE identity."""
    if len(p) < 3 or p[0] != 0x7e:
        return None, None, None
    mt = p[2]
    name = NAS_MT.get(mt, hex(mt))
    body = p[3:]
    if mt in (0x41, 0x4c):                        # Registration / Service Request: identity of the UE
        if len(body) >= 3:
            ln = int.from_bytes(body[1:3], 'big')
            k, v = mobile_identity(body[3:3 + ln])
            return name, k, v
    elif mt in (0x42, 0x54):                      # Registration Accept / Config Update: the NEW GUTI, IEI 0x77
        i = 0
        while i < len(body) - 2:
            if body[i] == 0x77:
                ln = int.from_bytes(body[i + 1:i + 3], 'big')
                k, v = mobile_identity(body[i + 3:i + 3 + ln])
                return name, k, v
            i += 1
    elif mt == 0x5d:                              # Identity Response
        if len(body) >= 2:
            ln = int.from_bytes(body[0:2], 'big')
            k, v = mobile_identity(body[2:2 + ln])
            return name, k, v
    return name, None, None


# ----------------------------------------------------------------------------- second pass
def collect(path):
    """Per CU-UE-F1AP-ID: identities, releases with causes, re-establishments. Plus the TMSI chain."""
    ctx = collections.defaultdict(lambda: {'du': set(), 'crnti': set(), 'amf': set(), 'tmsi': set(),
                                           'releases': [], 'ngap_cause': [], 'nas': []})
    chain = []                       # (old_tmsi, new_tmsi) pairs seen in Registration Request/Accept
    last_req = {}                    # ran_ue -> tmsi quoted in its Registration Request
    msin = {}                        # tmsi -> MSIN when a SUCI ever appears
    for num, ts, src, dst, ppid, buf in sctp_user_messages(read_capture(path)):
        if ppid == PPID_F1AP:
            try:
                F1PDU.from_aper(buf); v = F1PDU.get_val()
            except Exception:
                continue
            pc, kind, d = v[1]['procedureCode'], v[0], ies(v)
            cu = d.get(IE_CU_ID)
            if cu is None:
                continue
            c = ctx[cu]
            if d.get(IE_DU_ID) is not None:
                c['du'].add(d[IE_DU_ID])
            if d.get(IE_CRNTI) is not None:
                c['crnti'].add(d[IE_CRNTI])
            for r in find(d, 'newUE-Identity'):
                if isinstance(r, int):
                    c['crnti'].add(r)
            if pc == 6 and kind == 'initiatingMessage':          # UE CONTEXT RELEASE COMMAND
                cause = d.get(IE_CAUSE)
                c['releases'].append({'ts': ts, 'frame': num, 'du': d.get(IE_DU_ID), 'to': dst,
                                      'cause': cause[1] if isinstance(cause, tuple) else str(cause)})
        elif ppid == PPID_NGAP:
            try:
                NGPDU.from_aper(buf); v = NGPDU.get_val()
            except Exception:
                continue
            pc, d = v[1]['procedureCode'], ies(v)
            ran = d.get(IE_RAN_UE)
            if ran is not None:
                c = ctx[ran]
                if d.get(IE_AMF_UE) is not None:
                    c['amf'].add(d[IE_AMF_UE])
                if pc == 42 and d.get(IE_NG_CAUSE):              # UE Context Release Request (gNB->AMF)
                    cz = d[IE_NG_CAUSE]
                    c['ngap_cause'].append({'ts': ts, 'frame': num,
                                            'cause': cz[1] if isinstance(cz, tuple) else str(cz)})
            nas = d.get(IE_NAS)
            if isinstance(nas, bytes) and ran is not None:
                name, k, val = parse_nas(nas_plain(nas))
                if name:
                    ctx[ran]['nas'].append({'ts': ts, 'frame': num, 'msg': name, 'idkind': k, 'id': val})
                if k == 'suci-msin':
                    msin[('ran', ran)] = val
                if k in ('guti', 's-tmsi') and val is not None:
                    ctx[ran]['tmsi'].add(val)
                    if name in ('RegistrationAccept', 'ConfigurationUpdateCommand'):
                        if last_req.get(ran) is not None and last_req[ran] != val:
                            chain.append((last_req[ran], val))   # the AMF reallocated the GUTI
                    last_req[ran] = val
    return ctx, chain, msin


def union(chain, tmsis):
    """Union-find over TMSIs so every TMSI the same physical UE ever held maps to one key."""
    parent = {t: t for t in tmsis}

    def root(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for a, b in chain:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[rb] = ra
    return {t: root(t) for t in list(parent)}


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('capture')
    ap.add_argument('--out', default='ue_out')
    ap.add_argument('--tz', default='UTC')
    ap.add_argument('--ring', default=None)
    ap.add_argument('--lap-start', type=int, default=None)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ring = [int(x) for x in a.ring.split(',')] if a.ring else None

    res, _ = analyze(a.capture, a.tz, ring_override=ring, lap_start=a.lap_start)
    ctx, chain, msin = collect(a.capture)

    all_t = {t for c in ctx.values() for t in c['tmsi']} | {t for p in chain for t in p}
    grp = union(chain, all_t)
    keys = {}                                         # cu_id -> UE key
    for cu, c in ctx.items():
        roots = {grp.get(t, t) for t in c['tmsi']}
        keys[cu] = min(roots) if roots else None
    order = sorted({k for k in keys.values() if k is not None})
    label = {r: 'UE-%d' % (i + 1) for i, r in enumerate(order)}
    for cu in keys:
        keys[cu] = label.get(keys[cu], 'UE?(ctx %s)' % cu)

    laps = res.get('laps', {}).get('laps', [])

    def lap_of(ts):
        for l in laps:
            if l['start_ts'] <= ts <= (l['end_ts'] or 1e18):
                return l['n']
        return None

    # inter-DU handover releases: the source DU context released right after a successful inter-DU HO
    ho_rel = set()
    for h in res['ho_events']:
        if h['ok'] and h['type'] == 'inter-DU':
            for c in ctx.get(h['cu_id'], {}).get('releases', []):
                if 0 <= c['ts'] - h['complete_ts'] <= 3 and c['cause'] == 'normal-release':
                    ho_rel.add((h['cu_id'], c['frame']))

    # a context with no NAS identity (capture ends before it registers) inherits the UE that was
    # active just before it - correct for single-UE drive tests, and flagged as inferred
    first_seen = {}
    for h in res['ho_events']:
        first_seen.setdefault(h['cu_id'], h['ts'])
    for e in res.get('all_reest', []):
        if e.get('cu_id') is not None:
            first_seen.setdefault(e['cu_id'], e['ts'])
    for cu, c in ctx.items():
        if c['releases']:
            first_seen.setdefault(cu, c['releases'][0]['ts'])
    inferred = set()
    known = sorted((t, cu) for cu, t in first_seen.items() if not str(keys.get(cu, '')).startswith('UE?'))
    for cu, t in sorted(first_seen.items(), key=lambda kv: kv[1]):
        if str(keys.get(cu, '')).startswith('UE?'):
            prev = [k for k in known if k[0] <= t]
            if prev:
                keys[cu] = keys[prev[-1][1]]
                inferred.add(cu)

    rows = collections.defaultdict(lambda: {'ho': 0, 'ok': 0, 'ng': 0,
                                            'rel': collections.Counter(), 'reest': collections.Counter(),
                                            'ngap': collections.Counter(), 'cu': set(), 'du': set(),
                                            'crnti': set(), 'amf': set(), 'tmsi': set(), 'inf': False})

    def ue_of(cu, ts):
        k = keys.get(cu)
        if k and not str(k).startswith('UE?'):
            return k, cu in inferred
        prev = [p for p in known if p[0] <= ts]          # last UE seen before this moment
        return (keys[prev[-1][1]], True) if prev else ('?', True)

    def touch(cu, lap, ts=None):
        """Open the (UE, lap) row and stamp it with the identities this context actually used."""
        key, inf = ue_of(cu, ts) if ts is not None else (keys.get(cu, '?'), cu in inferred)
        r = rows[(key, lap)]
        if inf:
            r['inf'] = True
        c = ctx.get(cu)
        if c:
            r['cu'].add(cu); r['du'] |= c['du']; r['crnti'] |= c['crnti']
            r['amf'] |= c['amf']; r['tmsi'] |= c['tmsi']
        return r

    for h in res['ho_events']:
        r = touch(h['cu_id'], lap_of(h['ts']), h['ts'])
        r['ho'] += 1; r['ok' if h['ok'] else 'ng'] += 1
    for e in res.get('all_reest', []):
        if e.get('repeat_of'):
            continue
        r = touch(e.get('cu_id'), lap_of(e['ts']), e['ts'])
        r['reest'][e['cause']] += 1
    for cu, c in ctx.items():
        for rel in c['releases']:
            if (cu, rel['frame']) in ho_rel:
                continue                                  # inter-DU handover housekeeping, not a release
            touch(cu, lap_of(rel['ts']), rel['ts'])['rel'][rel['cause']] += 1
        for ng in c['ngap_cause']:
            touch(cu, lap_of(ng['ts']), ng['ts'])['ngap'][ng['cause']] += 1

    def j(s, n=6):
        s = sorted(s)
        return ', '.join(str(x) for x in s[:n]) + (' +%d' % (len(s) - n) if len(s) > n else '')

    def cz(c):
        return '; '.join('%s x%d' % (k, v) for k, v in c.most_common()) or '-'

    out = []
    for (ue, lap), r in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        out.append({'ue': ue + (' *' if r['inf'] else ''), 'msin': msin.get(ue, 'not in capture'), 'lap': lap,
                    'tmsi': j({'0x%08X' % t for t in r['tmsi']}), 'amf': j(r['amf']),
                    'cu': j(r['cu']), 'du': j(r['du']), 'crnti': j(r['crnti']),
                    'ho': r['ho'], 'ho_ok': r['ok'], 'ho_ng': r['ng'],
                    'rel': sum(r['rel'].values()), 'rel_causes': cz(r['rel']),
                    'ngap_causes': cz(r['ngap']),
                    'reest': sum(r['reest'].values()), 'reest_causes': cz(r['reest'])})

    cols = ['ue', 'msin', 'lap', 'tmsi', 'amf', 'cu', 'du', 'crnti', 'ho', 'ho_ok', 'ho_ng',
            'rel', 'rel_causes', 'ngap_causes', 'reest', 'reest_causes']
    head = ['UE', 'MSIN', 'Lap', '5G-TMSI', 'AMF-UE-NGAP-ID', 'gNB-CU-UE-F1AP-ID', 'gNB-DU-UE-F1AP-ID',
            'C-RNTI', 'HO', 'HO OK', 'HO NG', 'Releases', 'Release cause (F1AP)', 'Release cause (NGAP)',
            'Re-est', 'Re-est cause']
    with open(os.path.join(a.out, 'ue_events.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(head)
        for r in out:
            w.writerow([r[c] for c in cols])
    with open(os.path.join(a.out, 'ue_events.md'), 'w') as f:
        f.write('| ' + ' | '.join(head) + ' |\n|' + '---|' * len(head) + '\n')
        for r in out:
            f.write('| ' + ' | '.join(str(r[c]) for c in cols) + ' |\n')
    with open(os.path.join(a.out, 'ue_identity.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['ue', 'gNB-CU-UE-F1AP-ID', 'gNB-DU-UE-F1AP-ID', 'C-RNTI',
                                       'AMF-UE-NGAP-ID', '5G-TMSI', 'NAS messages'])
        for cu in sorted(ctx):
            c = ctx[cu]
            w.writerow([keys.get(cu, '?'), cu, j(c['du']), j(c['crnti']), j(c['amf']),
                        j({'0x%08X' % t for t in c['tmsi']}),
                        '; '.join(m['msg'] for m in c['nas'])])
    json.dump({'rows': out, 'laps': [{k: v for k, v in l.items() if k != 'visited'} for l in laps],
               'chain': chain, 'msin_found': bool(msin)},
              open(os.path.join(a.out, 'ue_events.json'), 'w'), indent=1, default=str)

    print('UEs: %d   contexts: %d   laps: %d' % (len(order), len(ctx), len(laps)))
    print('MSIN present in capture: %s' % ('yes' if msin else 'NO - no SUCI/SUPI sent; using the 5G-TMSI chain'))
    if any(r['ue'].endswith('*') for r in out):
        print('* = context identity inferred from timing (no NAS identity before the capture ended)')
    print(open(os.path.join(a.out, 'ue_events.md')).read())


if __name__ == '__main__':
    main()
