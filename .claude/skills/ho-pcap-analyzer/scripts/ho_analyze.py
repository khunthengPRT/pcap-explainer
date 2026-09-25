#!/usr/bin/env python3
"""
ho_analyze.py - extract and classify 5G NR handover (HO) events from a pcap/pcapng
capture taken on the F1 interface (CU <-> DU), using pure Python + pycrate.

Outputs (in --out directory, default ./ho_out):
  ho_events.json   structured HO events (input for ho_report.py)
  ho_events.csv    one row per HO attempt (open in Excel)
  f1_timeline.txt  every F1AP/RRC message decoded, one line each (grep-friendly)
  summary.txt      human-readable summary printed to stdout as well

Usage:
  python3 ho_analyze.py capture.pcapng [--out DIR] [--tz Asia/Tokyo]
                        [--rlf-window 5] [--trigger-window 3]

Requires:  pip install pycrate   (pure Python, no root, no tshark needed)
"""
import argparse, collections, csv, datetime, json, os, struct, sys

try:
    from pycrate_asn1dir import F1AP, NGAP, RRCNR
except ImportError:
    sys.exit("pycrate is required:  pip install pycrate   (or: pip install git+https://github.com/pycrate-org/pycrate)")

F1PDU = F1AP.F1AP_PDU_Descriptions.F1AP_PDU
NGPDU = NGAP.NGAP_PDU_Descriptions.NGAP_PDU
D = RRCNR.NR_RRC_Definitions
DL_DCCH, UL_DCCH, UL_CCCH, DL_CCCH, CGC = D.DL_DCCH_Message, D.UL_DCCH_Message, D.UL_CCCH_Message, D.DL_CCCH_Message, D.CellGroupConfig

# F1AP procedure codes (TS 38.473)
PC = {1: 'F1Setup', 3: 'gNBDUConfigUpdate', 5: 'UECtxSetup', 6: 'UECtxRelease', 7: 'UECtxMod', 8: 'UECtxModRequired',
      10: 'UECtxReleaseReq', 11: 'InitialULRRC', 12: 'DLRRC', 13: 'ULRRC', 18: 'Paging'}
# F1AP protocol IE ids used here
IE_CAUSE, IE_DUtoCU, IE_CU_ID, IE_DU_ID, IE_RRC, IE_SPCELL, IE_SRB, IE_CRNTI, IE_NRCGI, IE_TXSTOP = 0, 39, 40, 41, 50, 63, 64, 95, 111, 79
PPID_F1AP, PPID_NGAP = 62, 60


# ----------------------------------------------------------------------------- capture reading
def read_capture(path):
    """Yield (frame_no, epoch_ts, linktype, packet_bytes) from pcapng or classic pcap."""
    data = open(path, 'rb').read()
    magic = data[:4]
    if magic == b'\x0a\x0d\x0d\x0a':
        yield from _read_pcapng(data)
    elif magic in (b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4', b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d'):
        yield from _read_pcap(data)
    else:
        sys.exit('Unknown capture format (not pcap/pcapng)')


def _read_pcapng(data):
    pos, endian, ifaces, n = 0, '<', [], 0
    while pos + 12 <= len(data):
        btype, blen = struct.unpack(endian + 'II', data[pos:pos + 8])
        if btype == 0x0A0D0D0A:  # section header: (re)detect byte order
            endian = '<' if data[pos + 8:pos + 12] == b'\x4d\x3c\x2b\x1a' else '>'
            btype, blen = struct.unpack(endian + 'II', data[pos:pos + 8])
            ifaces = []
        if blen < 12:
            break
        body = data[pos + 8:pos + blen - 4]
        if btype == 1:  # interface description
            lt, = struct.unpack(endian + 'H', body[:2])
            tsres = 6
            opos = 8
            while opos + 4 <= len(body):  # look for if_tsresol option (code 9)
                code, olen = struct.unpack(endian + 'HH', body[opos:opos + 4])
                if code == 0:
                    break
                if code == 9 and olen >= 1:
                    v = body[opos + 4]
                    tsres = v & 0x7f if not v & 0x80 else -(v & 0x7f)
                opos += 4 + ((olen + 3) & ~3)
            ifaces.append((lt, tsres))
        elif btype == 6:  # enhanced packet block
            ifid, th, tl, cap, orig = struct.unpack(endian + 'IIIII', body[:20])
            lt, tsres = ifaces[ifid] if ifid < len(ifaces) else (1, 6)
            raw = (th << 32) | tl
            ts = raw / (10 ** tsres) if tsres >= 0 else raw / (2 ** -tsres)
            n += 1
            yield n, ts, lt, body[20:20 + cap]
        pos += blen


def _read_pcap(data):
    magic = data[:4]
    endian = '<' if magic in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1') else '>'
    nano = magic in (b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d')
    lt, = struct.unpack(endian + 'I', data[20:24])
    pos, n = 24, 0
    while pos + 16 <= len(data):
        s, us, cap, orig = struct.unpack(endian + 'IIII', data[pos:pos + 16])
        n += 1
        yield n, s + us / (1e9 if nano else 1e6), lt, data[pos + 16:pos + 16 + cap]
        pos += 16 + cap


def ip_payload(pkt, lt):
    """Return (src, dst, proto, payload) for IPv4/IPv6 packets on common link types."""
    if lt == 1:  # Ethernet
        eth = struct.unpack('!H', pkt[12:14])[0]; off = 14
        while eth in (0x8100, 0x88a8):
            eth = struct.unpack('!H', pkt[off + 2:off + 4])[0]; off += 4
    elif lt == 276:  # Linux SLL2
        eth = struct.unpack('!H', pkt[0:2])[0]; off = 20
    elif lt == 113:  # Linux SLL
        eth = struct.unpack('!H', pkt[14:16])[0]; off = 16
    elif lt == 101:  # raw IP
        eth = 0x0800 if pkt[0] >> 4 == 4 else 0x86dd; off = 0
    else:
        return None
    if eth == 0x0800:
        ihl = (pkt[off] & 0xf) * 4
        proto = pkt[off + 9]
        src = '.'.join(map(str, pkt[off + 12:off + 16])); dst = '.'.join(map(str, pkt[off + 16:off + 20]))
        return src, dst, proto, pkt[off + ihl:]
    if eth == 0x86dd:
        nh = pkt[off + 6]
        src = pkt[off + 8:off + 24].hex(); dst = pkt[off + 24:off + 40].hex()
        return src, dst, nh, pkt[off + 40:]
    return None


def sctp_user_messages(capture):
    """Yield (frame_no, ts, src, dst, ppid, payload) reassembling SCTP DATA chunk fragments."""
    frag = collections.defaultdict(bytes)
    for num, ts, lt, pkt in capture:
        r = ip_payload(pkt, lt)
        if not r or r[2] != 132:
            continue
        src, dst, _, sctp = r
        p = 12
        while p + 4 <= len(sctp):
            ctype, cflags, clen = struct.unpack('!BBH', sctp[p:p + 4])
            if clen < 4:
                break
            if ctype == 0 and clen >= 16:
                tsn, sid, ssn, ppid = struct.unpack('!IHHI', sctp[p + 4:p + 16])
                key = (src, dst, sid)
                frag[key] += sctp[p + 16:p + clen]
                if cflags & 1:  # E bit: last fragment
                    yield num, ts, src, dst, ppid, frag.pop(key)
            p += (clen + 3) & ~3


# ----------------------------------------------------------------------------- helpers
def find(v, key):
    """Recursively collect all values stored under dict key `key` in a pycrate value tree."""
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            if k == key:
                out.append(x)
            out += find(x, key)
    elif isinstance(v, (list, tuple)):
        for x in v:
            out += find(x, key)
    return out


def ies(v):
    return {ie['id']: ie['value'][1] for ie in v[1]['value'][1]['protocolIEs']}


def rrc_decode(msg, buf, pdcp):
    """RRC in F1AP RRC-Container: SRB0 = raw RRC; SRB1/2 = PDCP PDU (2-byte header + RRC + 4-byte MAC-I)."""
    msg.from_uper(buf[2:-4] if pdcp else buf)
    return msg.get_val()


def cell_group(x):
    if isinstance(x, tuple):  # pycrate already decoded the CONTAINING type
        return x[1]
    CGC.from_uper(x)
    return CGC.get_val()


def rsrp_dbm(idx):
    """SS-RSRP index -> dBm (TS 38.133 Table 10.1.6.1-1): value 0 = < -156, 127 = >= -31."""
    return None if idx is None else idx - 156


def nrcgi_str(x):
    if not x:
        return None
    ci = find(x, 'nRCellIdentity')
    if ci:
        val, bits = ci[0]
        return '%d' % val  # 36-bit NR Cell Identity as integer
    return None


# ----------------------------------------------------------------------------- main analysis
class UE:
    def __init__(self, cu_id):
        self.cu_id = cu_id
        self.du_ip = None          # DU currently serving (IP)
        self.du_id = None
        self.crnti = None          # current C-RNTI
        self.pci = None            # current serving PCI (None if unknown)
        self.cell = None           # current NR Cell Identity (string) if known
        self.meas = []             # recent measurement reports
        self.meas_cfg = {}         # measId -> description e.g. 'A3 off=3dB TTT=40ms'
        self.first_ts = None
        self.last_ts = None
        self.n_meas = 0
        self.setup_kind = None     # rrcSetup / rrcReestablishment
        self.msgs = []             # (ts, text) short message log for sequence diagrams
        self.tmsi1 = None          # ng-5G-S-TMSI-Part1 (39 LSB) - links contexts of the same physical UE
        self.pending_ho = None


def describe_report_config(rc):
    """Turn a ReportConfigNR into a short label like 'A3 off=+3.0dB hys=1.0dB TTT=ms40'."""
    try:
        rt = rc['reportType']
        if rt[0] != 'eventTriggered':
            return rt[0]
        ev = rt[1]['eventId']
        name = ev[0].replace('event', '')
        body = ev[1]
        parts = [name]
        for k in ('a3-Offset', 'a6-Offset'):
            if k in body:
                q = body[k]
                parts.append('off=%+.1fdB' % (q[1] / 2.0) if isinstance(q, tuple) else 'off=%s' % (q,))
        for k in ('a1-Threshold', 'a2-Threshold', 'a4-Threshold', 'a5-Threshold1', 'a5-Threshold2'):
            if k in body:
                q = body[k]
                if isinstance(q, tuple) and q[0] == 'rsrp':
                    parts.append('%s=%ddBm' % (k.split('-')[0] if 'Threshold' not in k else k.replace('-Threshold', 'thr'), rsrp_dbm(q[1])))
        if 'hysteresis' in body:
            parts.append('hys=%.1fdB' % (body['hysteresis'] / 2.0))
        if 'timeToTrigger' in body:
            parts.append('TTT=%s' % body['timeToTrigger'])
        return ' '.join(parts)
    except Exception:
        return '?'


def analyze(path, tz='UTC', rlf_window=5.0, trigger_window=3.0, verbose=False, ring_override=None, lap_start=None):
    try:
        from zoneinfo import ZoneInfo
        tzinfo = ZoneInfo(tz)
    except Exception:
        tzinfo = datetime.timezone.utc

    def fmt(ts):
        return datetime.datetime.fromtimestamp(ts, tzinfo).strftime('%H:%M:%S.%f')[:-3]

    cellmap = {}            # NR Cell Identity (str) -> PCI
    cell_du = {}            # PCI -> DU ip
    ues = {}                # cu_id -> UE
    pending_initial = {}    # (du_ip, du_id) -> list of pending CCCH events waiting for the CU-UE id
    timeline = []           # text lines
    ho_events = []          # dicts
    reest_events = []       # dicts (all RRCReestablishmentRequests)
    setup_events = []       # dicts (all RRCSetupRequests)
    all_meas = []           # every measurement report (for "report not followed by HO" analysis)
    open_mod = {}           # (cu_id) -> ts of a UE Context Modification Request still unanswered
    unanswered_mod = []     # (cu_id, ts_req, ts_release)
    core_release = []       # timestamps of NGAP UE Context Release / Release Request (session ended from the core side)
    setup_reqs = {}         # cu_id -> last UE Context Setup Request (inter-DU HO preparation)
    pending_setup_resp = {}
    pending_mod_req = {}    # (cu_id) -> SpCell in UE Context Mod Request (intra-DU HO)
    first_ts = last_ts = None
    stats = collections.Counter()

    def ue_for(cu_id):
        if cu_id not in ues:
            ues[cu_id] = UE(cu_id)
        return ues[cu_id]

    def log(num, ts, src, dst, pc, kind, cu, du, text):
        timeline.append('%6d %s %-15s -> %-15s %-16s %-18s cu=%-6s du=%-4s %s' % (
            num, fmt(ts), src, dst, PC.get(pc, pc), kind, cu, du, text))

    def learn_cell(cellid, pci, du_ip):
        if cellid and pci is not None:
            cellmap[cellid] = pci
        if pci is not None and du_ip:
            cell_du[pci] = du_ip

    for num, ts, src, dst, ppid, buf in sctp_user_messages(read_capture(path)):
        if ppid != PPID_F1AP:
            if ppid == PPID_NGAP:
                stats['ngap_msgs'] += 1
                try:                       # NGAP UE Context Release (41) / Release Request (42): the core ended the session
                    NGPDU.from_aper(buf)
                    nv = NGPDU.get_val()
                    if nv[1]['procedureCode'] in (41, 42):
                        core_release.append(ts)
                except Exception:
                    pass
            continue
        try:
            F1PDU.from_aper(buf)
            v = F1PDU.get_val()
        except Exception as e:
            stats['f1ap_decode_errors'] += 1
            continue
        stats['f1ap_msgs'] += 1
        first_ts = first_ts if first_ts is not None else ts
        last_ts = ts
        pc, kind = v[1]['procedureCode'], v[0]
        d = ies(v)
        cu_id, du_id = d.get(IE_CU_ID), d.get(IE_DU_ID)
        text = ''

        # ---- learn cell identities from F1 Setup / gNB-DU Configuration Update (served cells)
        if pc in (1, 3) and kind == 'initiatingMessage':
            for sc in find(v, 'served-Cell-Information'):
                learn_cell(nrcgi_str(sc.get('nRCGI')), sc.get('nRPCI'), src)
            text = 'served cells: ' + ', '.join('%s=PCI%s' % (nrcgi_str(sc.get('nRCGI')), sc.get('nRPCI')) for sc in find(v, 'served-Cell-Information'))
            log(num, ts, src, dst, pc, kind, cu_id, du_id, text)
            continue

        # ---- resolve CU-UE id for earlier CCCH messages of this (DU, DU-UE id)
        if cu_id is not None and du_id is not None and (src, du_id) in pending_initial:
            for ev in pending_initial.pop((src, du_id)):
                ev['cu_id'] = cu_id
                ue = ue_for(cu_id)
                ue.du_ip, ue.du_id, ue.crnti, ue.cell = src, du_id, ev['crnti'], ev['cell']
                ue.pci = cellmap.get(ev['cell'])
                ue.first_ts = ue.first_ts or ev['ts']
                ue.setup_kind = ev['kind']
                if ev.get('tmsi1') is not None:
                    ue.tmsi1 = ev['tmsi1']
                if ue.pending_ho is not None and ue.pending_ho['result'] is None:
                    ue.pending_ho['aborted_by'] = ev['kind']
                    ue.pending_ho = None
                if ev['kind'] == 'rrcReestablishmentRequest':
                    ue.msgs.append((ev['ts'], 'UE->DU', 'RRCReestablishmentRequest cause=%s (was on PCI %s) sent on cell:%s' % (ev['cause'], ev['pci'], ev['cell'])))
                else:
                    ue.msgs.append((ev['ts'], 'UE->DU', 'RRCSetupRequest (new connection) on cell:%s' % ev['cell']))
        if cu_id is None and du_id is not None and pc != 11:
            # DU-initiated message before we know the CU id: keep it simple, ignore
            pass

        ue = ue_for(cu_id) if cu_id is not None else None
        if ue is not None:
            ue.last_ts = ts
            ue.first_ts = ue.first_ts or ts
            if du_id is not None and (ue.du_ip is None):
                ue.du_ip, ue.du_id = (src if src != dst else None), du_id

        rrc = d.get(IE_RRC)
        # ============================================================== CCCH (RRCSetupRequest / RRCReestablishmentRequest)
        if pc == 11 and rrc is not None:
            mv = rrc_decode(UL_CCCH, rrc, False)
            name, body = mv['message'][1][0], mv['message'][1][1]
            body = body[name] if isinstance(body, dict) and name in body else body
            cell = nrcgi_str(d.get(IE_NRCGI))
            ev = {'ts': ts, 'frame': num, 'kind': name, 'du_ip': src, 'du_id': du_id, 'crnti': d.get(IE_CRNTI), 'cell': cell,
                  'cu_id': None, 'cause': None, 'pci': None, 'old_crnti': None}
            if name == 'rrcReestablishmentRequest':
                ev['cause'] = body['reestablishmentCause']
                ev['pci'] = body['ue-Identity']['physCellId']
                ev['old_crnti'] = body['ue-Identity']['c-RNTI']
                reest_events.append(ev)
                stats['reestablishment_requests'] += 1
                text = 'RRCReestablishmentRequest cause=%s lastPCI=%s lastC-RNTI=%s on cell %s newC-RNTI=%s' % (ev['cause'], ev['pci'], ev['old_crnti'], cell, ev['crnti'])
            else:
                uid = body.get('ue-Identity')
                if isinstance(uid, tuple) and uid[0] == 'ng-5G-S-TMSI-Part1':
                    ev['tmsi1'] = uid[1][0]
                text = '%s cause=%s on cell %s C-RNTI=%s' % (name, body.get('establishmentCause'), cell, ev['crnti'])
                stats['setup_requests'] += 1
                setup_events.append(ev)
            pending_initial.setdefault((src, du_id), []).append(ev)
            log(num, ts, src, dst, pc, kind, cu_id, du_id, text)
            continue

        # ============================================================== UE Context Setup (inter-DU HO preparation or initial)
        if pc == 5:
            if kind == 'initiatingMessage':
                cell = nrcgi_str(d.get(IE_SPCELL))
                setup_reqs[cu_id] = {'ts': ts, 'frame': num, 'target_du': dst, 'cell': cell, 'prep': rrc is not None}
                text = 'UE Context Setup Request -> DU %s, SpCell %s%s' % (dst, cell, ' (HO preparation, RRC container)' if rrc is not None else '')
                if ue and ue.cell is None and ue.du_ip in (None, dst):
                    ue.cell = cell
                    ue.pci = ue.pci if ue.pci is not None else cellmap.get(cell)
            else:
                req = setup_reqs.get(cu_id)
                duc = d.get(IE_DUtoCU)
                pci = None
                if duc and duc.get('cellGroupConfig') is not None:
                    cg = cell_group(duc['cellGroupConfig'])
                    rws = find(cg, 'reconfigurationWithSync')
                    if rws:
                        pci = rws[0]['spCellConfigCommon'].get('physCellId')
                        if req:
                            learn_cell(req['cell'], pci, src)
                            req['pci'] = pci
                            req['new_crnti'] = rws[0].get('newUE-Identity', d.get(IE_CRNTI))
                            req['target_du_id'] = du_id
                text = 'UE Context Setup Response from DU %s%s' % (src, (' target PCI %s, new C-RNTI %s' % (pci, d.get(IE_CRNTI))) if pci is not None else '')
            log(num, ts, src, dst, pc, kind, cu_id, du_id, text)
            if kind == 'unsuccessfulOutcome':
                stats['ue_context_setup_failures'] += 1
            continue

        # ============================================================== UE Context Modification (intra-DU HO uses this)
        if pc == 7:
            if kind == 'initiatingMessage':
                open_mod[cu_id] = (ts, num)
            else:
                open_mod.pop(cu_id, None)
            if kind == 'initiatingMessage':
                cell = nrcgi_str(d.get(IE_SPCELL))
                if cell:
                    pending_mod_req[cu_id] = {'cell': cell, 'ts': ts}
                text = 'UE Context Modification Request' + (' SpCell %s' % cell if cell else '') + (' txStop=%s' % d.get(IE_TXSTOP) if d.get(IE_TXSTOP) else '')
            else:
                duc = d.get(IE_DUtoCU)
                if duc and duc.get('cellGroupConfig') is not None and cu_id in pending_mod_req:
                    cg = cell_group(duc['cellGroupConfig'])
                    rws = find(cg, 'reconfigurationWithSync')
                    if rws:
                        pci = rws[0]['spCellConfigCommon'].get('physCellId')
                        learn_cell(pending_mod_req[cu_id]['cell'], pci, src)
                text = 'UE Context Modification Response'
            if rrc is None:
                log(num, ts, src, dst, pc, kind, cu_id, du_id, text)
                continue
            # fall through: request carries an RRC container (HO command to source DU)

        # ============================================================== UE Context Release
        if pc in (6, 10):
            cause = d.get(IE_CAUSE)
            text = ('UE Context Release Command' if pc == 6 else 'UE Context Release Request') + (' cause=%s' % (cause[1] if isinstance(cause, tuple) else cause) if cause else '')
            if kind == 'initiatingMessage' and ue:
                ue.msgs.append((ts, ('CU->DU' if pc == 6 else 'DU->CU'), text.replace('UE Context ', '')))
                if pc == 6 and cu_id in open_mod and cause and cause[1] != 'normal-release':
                    ue.mod_unanswered = open_mod.pop(cu_id)
                    unanswered_mod.append({'cu_id': cu_id, 'req_ts': ue.mod_unanswered[0], 'req_frame': ue.mod_unanswered[1], 'release_ts': ts, 'release_frame': num})
                    ue.msgs.append((ue.mod_unanswered[0], 'CU->DU', 'UE Context Modification Request (frame %d) - never answered by the DU' % ue.mod_unanswered[1]))
                if pc == 6 and cause and cause[1] != 'normal-release':
                    for h in ho_events:
                        if h['cu_id'] == cu_id and h['result'] == 'OK' and h.get('post_ho_drop') is None and 0 <= ts - h['complete_ts'] <= 5 and h is getattr(ue, 'last_ok_ho', None):
                            h['post_ho_drop'] = {'ts': ts, 'time': fmt(ts), 'frame': num, 'cause': cause[1], 'delay_s': round(ts - h['complete_ts'], 3),
                                                 'mod_unanswered': getattr(ue, 'mod_unanswered', None) is not None}
                            h['detail'] += '; then UE Context Release (%s) %.1f s after the HO%s' % (cause[1], ts - h['complete_ts'], ' - the DU never answered the post-HO UE Context Modification Request' if h['post_ho_drop']['mod_unanswered'] else '')
                if pc == 6:
                    # mark open HO attempts of this UE towards this DU
                    for h in ho_events:
                        if h['cu_id'] == cu_id and h['result'] is None and dst in (h['source_du'], h.get('target_du')) and cause and cause[1] != 'normal-release':
                            h['release'] = {'ts': ts, 'cause': cause[1], 'du': dst}
                if pc == 10:
                    for h in ho_events:
                        if h['cu_id'] == cu_id and h['result'] is None:
                            h['release_req'] = {'ts': ts, 'cause': cause[1] if cause else None, 'du': src}
            log(num, ts, src, dst, pc, kind, cu_id, du_id, text)
            continue

        if rrc is None or pc not in (7, 12, 13):
            if pc != 18:
                log(num, ts, src, dst, pc, kind, cu_id, du_id, text)
            continue

        # ============================================================== DL RRC (DLRRC / UECtxMod container)
        if pc in (12, 7):
            try:
                mv = rrc_decode(DL_DCCH, rrc, True); name = mv['message'][1][0]; ccch = False
            except Exception:
                mv = rrc_decode(DL_CCCH, rrc, False); name = mv['message'][1][0]; ccch = True
            txid = (find(mv, 'rrc-TransactionIdentifier') or [None])[0]
            text = name
            if name == 'rrcReconfiguration':
                # measurement configuration: remember event types per measId
                for mc in find(mv, 'measConfig'):
                    rcs = {rc['reportConfigId']: describe_report_config(rc['reportConfig'][1]) for rc in mc.get('reportConfigToAddModList', [])}
                    for mi in mc.get('measIdToAddModList', []):
                        if ue:
                            ue.meas_cfg[mi['measId']] = rcs.get(mi['reportConfigId'], ue.meas_cfg.get(mi['measId'], '?'))
                    if mc.get('reportConfigToAddModList') or mc.get('measIdToAddModList'):
                        text += ' +measConfig(%s)' % ', '.join('measId%s=%s' % (k, val) for k, val in sorted(ue.meas_cfg.items())) if ue else ''
                mcg = find(mv, 'masterCellGroup')
                rws = find(cell_group(mcg[0]), 'reconfigurationWithSync') if mcg else []
                if rws:
                    r = rws[0]
                    target_pci = r['spCellConfigCommon'].get('physCellId')
                    new_crnti = r.get('newUE-Identity')
                    t304 = r.get('t304')
                    stats['ho_commands'] += 1
                    # inter-DU?  a UE Context Setup Response with this PCI from another DU just before
                    req = setup_reqs.get(cu_id)
                    inter = bool(req and req.get('pci') == target_pci and req['target_du'] != dst and ts - req['ts'] < 5)
                    trig = None
                    for m in reversed(ue.meas):
                        if ts - m['ts'] <= trigger_window:
                            trig = m
                            break
                    target_rsrp = None
                    if trig:
                        for pci_n, rs in trig['neigh']:
                            if pci_n == target_pci:
                                target_rsrp = rs
                    h = {'id': len(ho_events) + 1, 'cu_id': cu_id, 'ue_label': str(cu_id), 'frame': num, 'ts': ts, 'time': fmt(ts),
                         'source_pci': ue.pci, 'source_cell': ue.cell, 'source_du': dst, 'source_crnti': ue.crnti,
                         'target_pci': target_pci, 'target_cell': req['cell'] if inter else pending_mod_req.get(cu_id, {}).get('cell'),
                         'target_du': req['target_du'] if inter else dst, 'new_crnti': new_crnti, 't304': t304, 'txid': txid,
                         'type': 'inter-DU' if inter else 'intra-DU',
                         'trigger': trig, 'serving_rsrp': trig['serving_rsrp'] if trig else None, 'target_rsrp': target_rsrp,
                         'result': None, 'detail': '', 'complete_ts': None, 'latency_ms': None, 'reest': None, 'post_ho_rlf': None}
                    if trig and trig['serving_rsrp'] is not None and target_rsrp is not None:
                        h['delta_db'] = target_rsrp - trig['serving_rsrp']
                    ho_events.append(h)
                    # if the target cell id is unknown but PCI is, and vice versa, learn
                    if h['target_cell'] and target_pci is not None:
                        learn_cell(h['target_cell'], target_pci, h['target_du'])
                    text += ' *** HO COMMAND: PCI %s -> PCI %s (%s, new C-RNTI %s, t304=%s, txid=%s)' % (ue.pci, target_pci, h['type'], new_crnti, t304, txid)
                    ue.msgs.append((ts, 'CU->UE', 'RRCReconfiguration (HO command -> PCI %s)' % target_pci))
                    ue.pending_ho = h
                else:
                    ue and ue.msgs.append((ts, 'CU->UE', 'RRCReconfiguration' + (' (measConfig)' if find(mv, 'measConfig') else '')))
            elif name in ('rrcSetup', 'rrcReestablishment'):
                ue.msgs.append((ts, 'CU->UE', name))
                if name == 'rrcSetup' and ue.setup_kind == 'rrcReestablishmentRequest':
                    text += ' (fallback: context not found -> new connection)'
            elif name == 'rrcRelease':
                ue.msgs.append((ts, 'CU->UE', name))
            log(num, ts, src, dst, pc, kind, cu_id, du_id, text)
            continue

        # ============================================================== UL RRC (DCCH)
        if pc == 13:
            try:
                mv = rrc_decode(UL_DCCH, rrc, True)
            except Exception as e:
                log(num, ts, src, dst, pc, kind, cu_id, du_id, 'UL RRC decode error: %s' % e)
                continue
            name = mv['message'][1][0]
            txid = (find(mv, 'rrc-TransactionIdentifier') or [None])[0]
            text = name
            if name == 'measurementReport':
                mr = mv['message'][1][1]['criticalExtensions'][1]['measResults']
                serv = []
                for x in mr.get('measResultServingMOList', []):
                    r = find(x.get('measResultServingCell', {}), 'rsrp')
                    serv.append(rsrp_dbm(r[0]) if r else None)
                neigh = []
                if 'measResultNeighCells' in mr:
                    for x in mr['measResultNeighCells'][1]:
                        r = find(x, 'rsrp')
                        neigh.append((x.get('physCellId'), rsrp_dbm(r[0]) if r else None))
                neigh.sort(key=lambda t: -(t[1] if t[1] is not None else -999))
                m = {'ts': ts, 'frame': num, 'measId': mr.get('measId'), 'event': ue.meas_cfg.get(mr.get('measId'), '?'),
                     'serving_pci': ue.pci, 'serving_rsrp': serv[0] if serv else None, 'neigh': neigh}
                m['cu_id'] = cu_id
                m['after_reest'] = ue.setup_kind == 'rrcReestablishmentRequest'
                all_meas.append(m)
                ue.meas.append(m); ue.meas = ue.meas[-20:]
                ue.n_meas += 1
                stats['measurement_reports'] += 1
                text += ' measId=%s (%s) serving PCI %s = %s dBm, neighbours %s' % (m['measId'], m['event'], ue.pci, m['serving_rsrp'], ', '.join('PCI %s=%s dBm' % n for n in neigh))
                ue.msgs.append((ts, 'UE->CU', 'MeasurementReport %s: serving %s dBm, %s' % (m['event'].split(' ')[0], m['serving_rsrp'], ('PCI %s %s dBm' % neigh[0]) if neigh else 'no neighbour')))
            elif name == 'rrcReconfigurationComplete':
                h = getattr(ue, 'pending_ho', None)
                if h and h['result'] is None and (h['txid'] is None or txid == h['txid']):
                    h['result'] = 'OK'
                    h['complete_ts'] = ts
                    h['latency_ms'] = round((ts - h['ts']) * 1000, 1)
                    h['complete_via_du'] = src
                    h['detail'] = 'RRCReconfigurationComplete after %.0f ms' % h['latency_ms']
                    text += ' *** HO OK (PCI %s -> PCI %s, %.0f ms)' % (h['source_pci'], h['target_pci'], h['latency_ms'])
                    # UE now lives on the target
                    ue.pci, ue.cell, ue.du_ip, ue.du_id = h['target_pci'], h['target_cell'], src, du_id
                    if h['new_crnti'] is not None:
                        ue.crnti = h['new_crnti']
                    ue.pending_ho = None
                    ue.last_ok_ho = h
                    ue.mod_unanswered = None
                ue.msgs.append((ts, 'UE->CU', 'RRCReconfigurationComplete'))
            elif name == 'rrcReestablishmentComplete':
                ue.msgs.append((ts, 'UE->CU', name))
            elif name == 'rrcSetupComplete':
                ue.msgs.append((ts, 'UE->CU', name))
                for tv in find(mv, 'ng-5G-S-TMSI-Value'):
                    if tv[0] == 'ng-5G-S-TMSI':
                        ue.tmsi1 = tv[1][0] & ((1 << 39) - 1)
            log(num, ts, src, dst, pc, kind, cu_id, du_id, text)

    # ------------------------------------------------------------------ post-processing
    # learn cell ids from re-establishment requests of UEs that never handed over
    for ev in reest_events:
        pass
    # fill PCIs that were unknown at the time (cell map learned later)
    for h in ho_events:
        if h['source_pci'] is None and h['source_cell'] in cellmap:
            h['source_pci'] = cellmap[h['source_cell']]
        if h['target_pci'] is not None and h['target_cell'] is None:
            for cid, p in cellmap.items():
                if p == h['target_pci']:
                    h['target_cell'] = cid
    for ue in ues.values():
        if ue.pci is None and ue.cell in cellmap:
            ue.pci = cellmap[ue.cell]

    # match re-establishment requests to HO attempts.
    # The UE identifies itself by (PCI, C-RNTI) of the cell it was last connected to. Intra-DU HOs often keep the
    # same C-RNTI, so the identity alone is ambiguous: always attach a re-establishment to the LATEST HO attempt
    # of that identity that precedes it.
    reest_events.sort(key=lambda e: e['ts'])
    for ev in reest_events:
        ev['pci_new_cell'] = cellmap.get(ev['cell'])
        ev['matched_ho'] = None
        ev['repeat_of'] = None
    prev = None
    for ev in reest_events:
        if prev and ev['pci'] == prev['pci'] and ev['old_crnti'] == prev['old_crnti'] and ev['ts'] - prev['ts'] < 3:
            ev['repeat_of'] = prev['frame']   # UE retried the same request (e.g. first attempt got no usable answer)
            continue
        prev = ev
        cands = []
        for h in ho_events:
            if h['ts'] >= ev['ts']:
                break
            same_source = ev['pci'] == h['source_pci'] and ev['old_crnti'] == h['source_crnti']
            same_target = ev['pci'] == h['target_pci'] and ev['old_crnti'] == h['new_crnti']
            if same_source or same_target:
                cands.append(h)
        if not cands:
            continue
        h = cands[-1]
        rinfo = {'ts': ev['ts'], 'time': fmt(ev['ts']), 'frame': ev['frame'], 'cause': ev['cause'], 'on_cell': ev['cell'],
                 'on_pci': ev['pci_new_cell'], 'last_pci': ev['pci'], 'delay_s': round(ev['ts'] - h['ts'], 3)}
        if h['result'] is None and ev['ts'] - h['ts'] <= 60:
            ev['matched_ho'] = h['id']
            h['result'] = 'NG'
            h['reest'] = rinfo
            h['fail_class'] = 'Reestablishment/' + ev['cause']
            h['detail'] = 'RRCReestablishmentRequest cause=%s (UE was on PCI %s) sent on PCI %s %.1f s after HO command' % (ev['cause'], ev['pci'], ev['pci_new_cell'], rinfo['delay_s'])
        elif h['result'] == 'OK' and h['post_ho_rlf'] is None and ev['ts'] - h['complete_ts'] <= rlf_window:
            ev['matched_ho'] = h['id']
            h['post_ho_rlf'] = rinfo
            h['detail'] += '; RLF %.1f s after HO: RRCReestablishmentRequest cause=%s on PCI %s' % (ev['ts'] - h['complete_ts'], ev['cause'], ev['pci_new_cell'])
    # a release that the core asked for (NGAP UE Context Release / Release Request just before it) is the end of the
    # session, not a radio/F1 drop - keep it visible but out of the drop count
    for h in ho_events:
        d = h.get('post_ho_drop')
        if d and not d['mod_unanswered'] and any(-2.0 <= t - d['ts'] <= 0.5 for t in core_release):
            d['core_initiated'] = True
            h['detail'] = h['detail'].replace('; then UE Context Release (%s) %.1f s after the HO' % (d['cause'], d['delay_s']),
                                              '; then the core released the UE %.1f s after the HO (NGAP UE Context Release - end of session, not a drop)' % d['delay_s'])
    for h in ho_events:
        if h.get('post_ho_rlf') and h.get('post_ho_drop') and h['post_ho_drop']['ts'] > h['post_ho_rlf']['ts']:
            h.pop('post_ho_drop')  # the release is the consequence of the RLF, not a separate drop
            h['detail'] = h['detail'].split('; then UE Context Release')[0] + '; RLF %.1f s after HO: RRCReestablishmentRequest cause=%s on PCI %s' % (
                h['post_ho_rlf']['ts'] - h['complete_ts'], h['post_ho_rlf']['cause'], h['post_ho_rlf']['on_pci'])
        if h.get('reest'):  # a later context release is a consequence, not the cause
            for k in ('release', 'release_req'):
                if h.get(k) and h[k]['ts'] > h['reest']['ts']:
                    h.pop(k)
        if h['result'] is None:
            h['result'] = 'NG'
            if h.get('release'):
                h['fail_class'] = 'NoResponse/UEContextRelease'
                h['detail'] = 'no RRCReconfigurationComplete; UE Context Release (%s) %.1f s after HO command' % (h['release']['cause'], h['release']['ts'] - h['ts'])
            elif h.get('release_req'):
                h['fail_class'] = 'NoResponse/UEContextReleaseRequest'
                h['detail'] = 'no RRCReconfigurationComplete; DU sent UE Context Release Request (%s) %.1f s after HO command' % (h['release_req']['cause'], h['release_req']['ts'] - h['ts'])
            else:
                h['fail_class'] = 'NoResponse/EndOfCapture' if last_ts - h['ts'] < 15 else 'NoResponse'
                h['detail'] = 'no RRCReconfigurationComplete and no re-establishment seen'
        h['ok'] = h['result'] == 'OK'
        # ping-pong: back to previous cell within 10 s handled in report

    # stable UE labels: contexts sharing the same 5G-S-TMSI are the same physical UE
    # UE label = gNB-CU-UE-F1AP-ID (what engineers filter on in Wireshark); the 5G-S-TMSI link is kept in ue_tmsi1
    def label_for(ue):
        return str(ue.cu_id)
    for ue in ues.values():
        ue.label = label_for(ue)
    for h in ho_events:
        h['ue_label'] = ues[h['cu_id']].label
        h['ue_tmsi1'] = ues[h['cu_id']].tmsi1
    # a HO with no response where a UE later comes back with a brand-new RRC connection (RRCSetupRequest).
    # If the 5G-S-TMSI matches it is certainly the same UE; otherwise it is only a hint (true in single-UE drive tests).
    for h in ho_events:
        if h['result'] == 'NG' and h.get('fail_class', '').startswith('NoResponse'):
            for ev in setup_events:
                if 0 < ev['ts'] - h['ts'] <= 30:
                    same = h.get('ue_tmsi1') is not None and ev.get('tmsi1') == h['ue_tmsi1']
                    h['reattach'] = {'ts': ev['ts'], 'time': fmt(ev['ts']), 'frame': ev['frame'], 'on_cell': ev['cell'], 'on_pci': cellmap.get(ev['cell']),
                                     'delay_s': round(ev['ts'] - h['ts'], 3), 'same_ue_confirmed': same}
                    h['detail'] += '; %s new RRCSetupRequest on PCI %s %.1f s after the HO command%s' % (
                        'same UE (5G-S-TMSI match) sent a' if same else 'next', cellmap.get(ev['cell']), ev['ts'] - h['ts'], '' if same else ' (likely the same UE in a single-UE test)')
                    break

    # measurement reports that did not lead to a HO command within 2 s (CU ignored them / UE dropped first)
    cmd_by_ue = collections.defaultdict(list)
    for h in ho_events:
        cmd_by_ue[h['cu_id']].append(h['ts'])
    unanswered_meas = []
    for m in all_meas:
        if any(0 <= t - m['ts'] <= 2.0 for t in cmd_by_ue.get(m['cu_id'], [])):
            continue
        if any(-0.5 <= t - m['ts'] < 0 for t in cmd_by_ue.get(m['cu_id'], [])):
            continue  # report arrived right after a command (stale)
        best = m['neigh'][0] if m['neigh'] else (None, None)
        unanswered_meas.append({'ts': m['ts'], 'time': fmt(m['ts']), 'frame': m['frame'], 'cu_id': m['cu_id'], 'event': m['event'],
                                'serving_pci': m['serving_pci'], 'serving_rsrp': m['serving_rsrp'], 'best_pci': best[0], 'best_rsrp': best[1],
                                'after_reest': m['after_reest']})

    # non-HO RLFs (re-establishments not tied to any HO)
    other_rlf = [e for e in reest_events if e['matched_ho'] is None and e['repeat_of'] is None]
    for e in other_rlf:
        e['ue_label'] = ues[e['cu_id']].label if e.get('cu_id') in ues else '?'
    for e in unanswered_meas:
        e['ue_label'] = ues[e['cu_id']].label if e.get('cu_id') in ues else '?'

    # per-UE summaries for the report
    ue_list = []
    for cu_id, ue in ues.items():
        hos = [h for h in ho_events if h['cu_id'] == cu_id]
        ue_list.append({'cu_id': cu_id, 'label': ue.label, 'tmsi1': ue.tmsi1, 'first_ts': ue.first_ts, 'last_ts': ue.last_ts,
                        'setup_kind': ue.setup_kind, 'n_meas': ue.n_meas, 'n_ho': len(hos),
                        'n_ok': sum(1 for h in hos if h['ok']), 'n_ng': sum(1 for h in hos if not h['ok']),
                        'meas_cfg': ue.meas_cfg, 'msgs': [(t, fmt(t), a, _cellfix(b, cellmap)) for t, a, b in ue.msgs]})

    result = {
        'capture': os.path.basename(path), 'tz': tz, 'first_ts': first_ts, 'last_ts': last_ts,
        'first_time': fmt(first_ts) if first_ts else None, 'last_time': fmt(last_ts) if last_ts else None,
        'duration_s': round(last_ts - first_ts, 1) if first_ts else 0,
        'stats': dict(stats), 'cellmap': cellmap, 'cell_du': cell_du,
        'ho_events': ho_events, 'other_rlf': other_rlf, 'ues': ue_list,
        'unanswered_meas': unanswered_meas, 'unanswered_mod': unanswered_mod,
        'all_reest': [{k: v for k, v in e.items() if k != 'matched_ho' or True} for e in reest_events],
        'all_setup': [{'ts': e['ts'], 'frame': e['frame'], 'cell': e['cell'], 'cu_id': e.get('cu_id')} for e in setup_events],
        'ho_ok': sum(1 for h in ho_events if h['ok']), 'ho_ng': sum(1 for h in ho_events if not h['ok']),
    }
    result['laps'] = count_laps(result, ring_override, lap_start)
    return result, timeline


def _cellfix(text, cellmap):
    import re
    return re.sub(r'cell:(\d+)', lambda m: 'PCI %s' % cellmap.get(m.group(1), '? (cell %s)' % m.group(1)), text)


def learn_ring(ho_events, start=None):
    """Order of cells around the test route, learned from the dominant HO direction (most frequent OK successor)."""
    succ = collections.defaultdict(collections.Counter)
    for h in ho_events:
        if h['ok'] and h['source_pci'] is not None and h['target_pci'] is not None:
            succ[h['source_pci']][h['target_pci']] += 1
    if not succ:
        return []
    cur = start if start in succ else min(succ)
    ring = [cur]
    while True:
        nxt = [p for p, _ in succ[cur].most_common() if p not in ring]
        if not nxt:
            break
        cur = nxt[0]
        ring.append(cur)
        if cur not in succ:
            break
    return ring


def count_laps(res, ring=None, start=None):
    """Walk every cell entry (OK HO target, re-establishment cell, new RRC setup cell) in time order and cut laps
    each time the route's start cell is entered again. Ping-pong (re-entering a cell already visited in this lap)
    does not break a lap; a lap is *complete* when all ring cells were visited, *clean* when every cell change
    in it was a successful HO."""
    hos = res['ho_events']
    ring = ring or learn_ring(hos, start)
    if len(ring) < 3:
        return {'ring': ring, 'laps': [], 'note': 'route could not be learned (need OK handovers between at least 3 cells)'}
    start = ring[0]
    entries = []
    for h in hos:
        if h['ok'] and h['target_pci'] is not None:
            entries.append((h['complete_ts'], h['target_pci'], 'HO', h['id']))
    for e in res.get('all_reest', []):
        if e.get('pci_new_cell') is not None and e.get('repeat_of') is None:
            entries.append((e['ts'], e['pci_new_cell'], 'reestablishment', e['frame']))
    for e in res.get('all_setup', []):
        pci = res['cellmap'].get(e['cell'])
        if pci is not None:
            entries.append((e['ts'], pci, 'new connection', e['frame']))
    entries.sort()
    seq = []
    for e in entries:  # collapse consecutive entries into the same cell (re-establishment in the same cell etc.)
        if seq and seq[-1][1] == e[1]:
            if e[2] != 'HO':
                seq[-1] = (seq[-1][0], seq[-1][1], seq[-1][2] + '+' + e[2], seq[-1][3])
            continue
        seq.append(e)
    laps, cur = [], None

    def close(cur, end_ts, reached_start):
        visited = [c for c in ring[1:] if c in cur['visited']]
        missed = [c for c in ring[1:] if c not in cur['visited']]
        cur.update({'end_ts': end_ts, 'complete': reached_start and not missed, 'reached_start': reached_start, 'missed': missed,
                    'clean': cur['n_reest'] == 0 and cur['n_new'] == 0 and cur['n_ng'] == 0,
                    'duration_s': round(end_ts - cur['start_ts'], 1) if end_ts and cur['start_ts'] else None})
        laps.append(cur)

    for ts, pci, how, ref in seq:
        if pci == start and cur is not None:
            # ping-pong at the lap boundary (start <-> neighbour cell only) is not a new lap
            if laps and not laps[-1].get('in_progress') and cur['visited'] and cur['visited'] <= {ring[-1], ring[1]} and not cur.get('partial_start'):
                prev = laps[-1]
                for k in ('n_ho', 'n_reest', 'n_new'):
                    prev[k] += cur[k]
                prev['n_pingpong'] += len(cur['path'])
                prev['path'] += cur['path']
                prev['end_ts'] = ts
                prev['duration_s'] = round(ts - prev['start_ts'], 1)
                cur = None   # fall through: this entry is on the start cell, so it opens the next lap normally
            else:
                close(cur, ts, True)
                cur = None
        if cur is None:
            cur = {'n': len(laps) + 1, 'start_ts': ts, 'start_how': how, 'visited': set(), 'path': [], 'n_ho': 0, 'n_reest': 0, 'n_new': 0, 'n_pingpong': 0, 'n_ng': 0}
            if pci != start:
                cur['start_ts'] = ts
                cur['partial_start'] = True
        if pci != start:
            if pci in cur['visited']:
                cur['n_pingpong'] += 1
            cur['visited'].add(pci)
        cur['path'].append(pci)
        if 'HO' in how:
            cur['n_ho'] += 1
        if 'reestablishment' in how:
            cur['n_reest'] += 1
        if 'new connection' in how:
            cur['n_new'] += 1
    if cur is not None:
        close(cur, res.get('last_ts'), False)
        cur['in_progress'] = True
    # NG HOs per lap (by time)
    for lap in laps:
        lap['n_ng'] = sum(1 for h in hos if not h['ok'] and lap['start_ts'] <= h['ts'] <= (lap['end_ts'] or 1e18))
        lap['clean'] = lap['n_reest'] == 0 and lap['n_new'] == 0 and lap['n_ng'] == 0
        lap['visited'] = sorted(lap['visited'])
    return {'ring': ring, 'laps': laps,
            'complete': sum(1 for l in laps if l['complete']),
            'clean': sum(1 for l in laps if l['complete'] and l['clean']),
            'incomplete': sum(1 for l in laps if not l['complete'] and not l.get('in_progress') and not l.get('partial_start')),
            'partial': sum(1 for l in laps if l.get('in_progress') or l.get('partial_start'))}


def write_outputs(res, timeline, out):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'f1_timeline.txt'), 'w') as f:
        f.write('\n'.join(timeline) + '\n')
    with open(os.path.join(out, 'ho_events.json'), 'w') as f:
        json.dump(res, f, indent=1, default=str)
    cols = ['id', 'time', 'gnb_cu_ue_f1ap_id', 'type', 'source_pci', 'target_pci', 'serving_rsrp', 'target_rsrp', 'delta_db', 'trigger_event',
            'result', 'fail_class', 'latency_ms', 'reest_cause', 'reest_on_pci', 'reest_delay_s', 'post_ho_rlf_s', 'post_ho_rlf_cause', 'dropped_after_s', 'detail', 'frame']
    with open(os.path.join(out, 'ho_events.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(cols)
        for h in res['ho_events']:
            w.writerow([h['id'], h['time'], h['ue_label'], h['type'], h['source_pci'], h['target_pci'], h['serving_rsrp'], h['target_rsrp'],
                        h.get('delta_db'), h['trigger']['event'] if h['trigger'] else '', h['result'], h.get('fail_class', ''), h['latency_ms'],
                        h['reest']['cause'] if h['reest'] else '', h['reest']['on_pci'] if h['reest'] else '', h['reest']['delay_s'] if h['reest'] else '',
                        round(h['post_ho_rlf']['ts'] - h['complete_ts'], 2) if h['post_ho_rlf'] else '', h['post_ho_rlf']['cause'] if h['post_ho_rlf'] else '',
                        h['post_ho_drop']['delay_s'] if h.get('post_ho_drop') else '', h['detail'], h['frame']])
    summary = summarize(res)
    with open(os.path.join(out, 'summary.txt'), 'w') as f:
        f.write(summary)
    return summary


def fmt_ts(ts, tz='UTC'):
    try:
        from zoneinfo import ZoneInfo
        tzinfo = ZoneInfo(tz)
    except Exception:
        tzinfo = datetime.timezone.utc
    return datetime.datetime.fromtimestamp(ts, tzinfo).strftime('%H:%M:%S.%f')[:-3]


def summarize(res):
    L = []
    hos = res['ho_events']
    L.append('Capture: %s   (%s .. %s %s, %.0f s)' % (res['capture'], res['first_time'], res['last_time'], res['tz'], res['duration_s']))
    L.append('F1AP messages: %s   UE contexts: %d   measurement reports: %s   re-establishment requests: %s' % (
        res['stats'].get('f1ap_msgs', 0), len(res['ues']), res['stats'].get('measurement_reports', 0), res['stats'].get('reestablishment_requests', 0)))
    cells = sorted(set([h['source_pci'] for h in hos] + [h['target_pci'] for h in hos]) - {None})
    L.append('Cells (PCI): %s   cell-id map: %s' % (cells, ', '.join('%s=PCI%s' % kv for kv in sorted(res['cellmap'].items()))))
    n = len(hos)
    L.append('')
    L.append('HANDOVER ATTEMPTS: %d   OK: %d   NG: %d   success rate: %s' % (n, res['ho_ok'], res['ho_ng'], ('%.1f%%' % (100.0 * res['ho_ok'] / n)) if n else '-'))
    fc = collections.Counter(h.get('fail_class', '') for h in hos if not h['ok'])
    for k, c in fc.most_common():
        L.append('   NG breakdown: %-40s %d' % (k, c))
    post = [h for h in hos if h['post_ho_rlf']]
    if post:
        L.append('   OK but RLF shortly after (re-establishment within window): %d' % len(post))
    drops = [h for h in hos if h.get('post_ho_drop') and not h['post_ho_drop'].get('core_initiated')]
    ended = [h for h in hos if h.get('post_ho_drop') and h['post_ho_drop'].get('core_initiated')]
    if drops:
        L.append('   OK but UE context released within 5 s (call dropped right after the HO): %d%s' % (
            len(drops), ' - in %d of them the DU never answered the post-HO UE Context Modification Request' % sum(1 for h in drops if h['post_ho_drop']['mod_unanswered'])))
    if ended:
        L.append('   OK and then the core ended the session normally (not a drop): %d' % len(ended))
    lat = [h['latency_ms'] for h in hos if h['ok'] and h['latency_ms'] is not None]
    if lat:
        L.append('   HO command -> complete latency: min %.0f / median %.0f / max %.0f ms' % (min(lat), sorted(lat)[len(lat) // 2], max(lat)))
    pairs = collections.Counter((h['source_pci'], h['target_pci'], h['ok']) for h in hos)
    L.append('')
    L.append('PER CELL PAIR (source -> target): OK / NG')
    for (s, t) in sorted(set((a, b) for a, b, _ in pairs), key=lambda x: (str(x[0]), str(x[1]))):
        L.append('   PCI %-4s -> PCI %-4s : %2d OK / %2d NG' % (s, t, pairs[(s, t, True)], pairs[(s, t, False)]))
    L.append('')
    L.append('EVENT LIST (UE column = gNB-CU-UE-F1AP-ID)')
    for h in hos:
        rs = 'serving %s dBm -> target %s dBm' % (h['serving_rsrp'], h['target_rsrp']) if h['trigger'] else 'no measurement report within window'
        L.append('  #%-3d %s %-9s PCI %-4s -> PCI %-4s %-8s %-3s %s  [%s]' % (h['id'], h['time'], h['ue_label'], h['source_pci'], h['target_pci'], h['type'], h['result'], rs, h['detail']))
    laps = res.get('laps', {})
    if laps.get('laps'):
        L.append('')
        L.append('LAPS (route %s, learned from the dominant HO direction; a lap = entering PCI %s again after visiting the other cells)' % (' -> '.join('PCI %s' % p for p in laps['ring'] + [laps['ring'][0]]), laps['ring'][0]))
        L.append('   complete laps: %d   (clean - every cell change was an OK handover: %d)   incomplete: %d   partial (start/end of capture): %d' % (
            laps['complete'], laps['clean'], laps['incomplete'], laps['partial']))
        for l in laps['laps']:
            kind = 'in progress at end of capture' if l.get('in_progress') else ('partial (capture starts mid-lap)' if l.get('partial_start') else ('COMPLETE' if l['complete'] else 'incomplete, missed PCI %s' % ', '.join(map(str, l['missed']))))
            L.append('   lap %2d  %s -> %s  %6s s  %-34s HO OK %2d, HO NG %d, re-est %d, new conn %d, ping-pong %d  %s' % (
                l['n'], fmt_ts(l['start_ts'], res['tz']), fmt_ts(l['end_ts'], res['tz']) if l['end_ts'] else '  end   ', l['duration_s'] if l['duration_s'] is not None else '-', kind,
                l['n_ho'], l['n_ng'], l['n_reest'], l['n_new'], l['n_pingpong'], 'CLEAN' if l['complete'] and l['clean'] else ''))
    elif laps.get('note'):
        L.append('')
        L.append('LAPS: ' + laps['note'])
    um = res.get('unanswered_meas', [])
    if um:
        L.append('')
        L.append('MEASUREMENT REPORTS NOT FOLLOWED BY A HO COMMAND within 2 s: %d (after a re-establishment: %d)' % (len(um), sum(1 for e in um if e['after_reest'])))
        L.append('   (the UE said a neighbour was stronger but the CU did not hand over - check what happened next in f1_timeline.txt)')
        for e in um[:40]:
            L.append('   %s frame %-6d %-9s serving PCI %-4s %s dBm, best neighbour PCI %-4s %s dBm%s' % (
                fmt_ts(e['ts'], res['tz']), e['frame'], e['ue_label'], e['serving_pci'], e['serving_rsrp'], e['best_pci'], e['best_rsrp'], '  [after re-establishment]' if e['after_reest'] else ''))
        if len(um) > 40:
            L.append('   ... %d more (see ho_events.json)' % (len(um) - 40))
    if res['other_rlf']:
        L.append('')
        L.append('RADIO LINK FAILURES NOT LINKED TO A HANDOVER (RRCReestablishmentRequest with no HO command before it): %d' % len(res['other_rlf']))
        L.append('   (when "was on" and "sent on" differ, the UE changed cell by re-establishment instead of by handover)')
        for e in res['other_rlf']:
            L.append('   %s frame %-6d cause=%-16s was on PCI %-4s -> sent on PCI %-4s (cell %s)' % (fmt_ts(e['ts'], res['tz']), e['frame'], e['cause'], e['pci'], e.get('pci_new_cell'), e['cell']))
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('capture')
    ap.add_argument('--out', default='ho_out')
    ap.add_argument('--tz', default='UTC', help='timezone for displayed times, e.g. Asia/Tokyo')
    ap.add_argument('--rlf-window', type=float, default=5.0, help='seconds after a successful HO within which a re-establishment is flagged as post-HO RLF')
    ap.add_argument('--trigger-window', type=float, default=3.0, help='seconds before the HO command to look for the triggering measurement report')
    ap.add_argument('--ring', default=None, help='route order of cells for lap counting, e.g. 101,202,303,404,505,606,707,808 (default: learned from the HO direction)')
    ap.add_argument('--lap-start', type=int, default=None, help='PCI where a lap starts/ends when the ring is learned (default: lowest PCI)')
    a = ap.parse_args()
    ring = [int(x) for x in a.ring.split(',')] if a.ring else None
    res, tl = analyze(a.capture, a.tz, a.rlf_window, a.trigger_window, ring_override=ring, lap_start=a.lap_start)
    print(write_outputs(res, tl, a.out))
    print('Wrote %s/{ho_events.json, ho_events.csv, f1_timeline.txt, summary.txt}' % a.out)
