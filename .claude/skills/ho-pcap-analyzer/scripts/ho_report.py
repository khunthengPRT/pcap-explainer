#!/usr/bin/env python3
"""
ho_report.py - turn ho_events.json (from ho_analyze.py) into a self-contained HTML report with
simplified diagrams a non-specialist can follow:

  1. headline numbers (attempts, OK, NG, success rate)
  2. "how to read a handover" explainer ladder (OK / HO failure / other failure)
  3. cell map: which cell hands over to which, with OK/NG counts on each arrow
  4. journey timeline: serving cell vs time with every HO drawn as an arrow (green OK, red NG)
  5. event table (every HO attempt: from -> to, RSRP, result, reason)
  6. one sequence diagram per NG event showing the real messages

Usage:  python3 ho_report.py ho_out/ho_events.json [-o ho_out/ho_report.html] [--title "..."] [--lang en|ja|both]
        --lang both (default) = one page with an English / 日本語 switch; en or ja = single-language page
Pure Python, no dependencies; the HTML has no external resources (opens offline, mails fine).
"""
import argparse, collections, html, json, math, os

OK, NG, WARN, GREY, INK, MUTED, LINE = '#1e8e3e', '#d93025', '#e37400', '#9aa0a6', '#202124', '#5f6368', '#dadce0'
RLF, DROP = '#b45309', '#00838f'   # RLF after HO = dark burnt orange (still reads as "bad", clearly not the NG red); drop = teal
LANG = 'en'
BLUE = '#1a73e8'


def esc(s):
    return html.escape(str(s if s is not None else ''))


def _(s):
    """UI string in the current language (Japanese when LANG == 'ja', English otherwise)."""
    return JA.get(s, s) if LANG == 'ja' else s


def pci_lbl(p):
    return 'PCI %s' % p if p is not None else 'PCI ?'


# ------------------------------------------------------------------------------------ explainer ladder
def ladder(title, subtitle, steps, color, width=480):
    """steps: list of (from_lane, to_lane, text, kind) lanes: 0=UE 1=Source cell 2=CU 3=Target cell.
    kind: 'ok','ng','warn','plain'"""
    lanes = [_('UE'), _('Source cell'), 'gNB-CU', _('Target cell')]
    lx = [60, 190, 320, 450]
    top, step_h = 70, 34
    h = top + step_h * len(steps) + 30
    out = ['<svg viewBox="0 0 %d %d" width="%d" role="img" aria-label="%s">' % (width, h, width, esc(title))]
    out.append('<text x="10" y="18" font-size="14" font-weight="700" fill="%s">%s</text>' % (color, esc(title)))
    out.append('<text x="10" y="34" font-size="11" fill="%s">%s</text>' % (MUTED, esc(subtitle)))
    for x, name in zip(lx, lanes):
        out.append('<text x="%d" y="56" font-size="11" text-anchor="middle" font-weight="600" fill="%s">%s</text>' % (x, INK, name))
        out.append('<line x1="%d" y1="62" x2="%d" y2="%d" stroke="%s" stroke-dasharray="3 3"/>' % (x, x, h - 12, LINE))
    for i, (a, b, text, kind) in enumerate(steps):
        y = top + step_h * i + 14
        col = {'ok': OK, 'ng': NG, 'warn': WARN}.get(kind, INK)
        if a == b:
            out.append('<circle cx="%d" cy="%d" r="5" fill="%s"/>' % (lx[a], y, col))
            out.append('<text x="%d" y="%d" font-size="10.5" fill="%s">%s</text>' % (lx[a] + 10, y + 4, col, esc(text)))
        else:
            x1, x2 = lx[a], lx[b]
            d = 1 if x2 > x1 else -1
            out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.6"/>' % (x1, y, x2 - 6 * d, y, col))
            out.append('<polygon points="%d,%d %d,%d %d,%d" fill="%s"/>' % (x2, y, x2 - 8 * d, y - 4, x2 - 8 * d, y + 4, col))
            if abs(x2 - x1) < 200:
                out.append('<text x="%d" y="%d" font-size="10.5" fill="%s">%s</text>' % (min(x1, x2) + 4, y - 5, col, esc(text)))
            else:
                out.append('<text x="%d" y="%d" font-size="10.5" text-anchor="middle" fill="%s">%s</text>' % ((x1 + x2) / 2, y - 5, col, esc(text)))
    out.append('</svg>')
    return '\n'.join(out)


def explainer():
    ok = ladder(_('OK handover'), _('what a normal, successful HO looks like'), [
        (0, 2, _('1. MeasurementReport "neighbour stronger" (A3)'), 'plain'),
        (2, 3, _('2. prepare UE context'), 'plain'),
        (2, 0, _('3. HO COMMAND (RRCReconfiguration, target PCI)'), 'plain'),
        (0, 3, _('4. sync + random access on target cell'), 'plain'),
        (0, 2, _('5. RRCReconfigurationComplete = OK'), 'ok'),
        (2, 1, _('6. release old context'), 'plain'),
    ], OK)
    hof = ladder(_('NG - handoverFailure'), _('UE could not reach the target cell (timer T304 expired)'), [
        (0, 2, _('1. MeasurementReport'), 'plain'),
        (2, 0, _('2. HO COMMAND (target PCI)'), 'plain'),
        (0, 0, _('3. random access on target fails'), 'ng'),
        (0, 0, _('4. T304 expires, UE falls back to source config'), 'ng'),
        (0, 1, _('5. RRCReestablishmentRequest cause=handoverFailure'), 'ng'),
        (2, 0, _('6. RRCReestablishment, or RRCSetup if context gone'), 'warn'),
    ], NG)
    oth = ladder(_('NG - otherFailure / no response'), _('radio link lost around the HO (RLF), or UE never answered'), [
        (0, 2, _('1. MeasurementReport (often weak serving RSRP)'), 'plain'),
        (2, 0, '2. HO COMMAND (target PCI)', 'plain'),
        (0, 0, _('3. radio link failure (RLF) detected by UE'), 'ng'),
        (0, 3, _('4. RRCReestablishmentRequest cause=otherFailure'), 'ng'),
        (2, 1, _("4'. or no answer at all: CU releases context"), 'ng'),
        (0, 1, _('5. UE comes back with a new RRCSetupRequest'), 'warn'),
    ], NG)
    return '<div class="row wrap">%s%s%s</div>' % tuple('<div class="card">%s</div>' % x for x in (ok, hof, oth))


# ------------------------------------------------------------------------------------ cell map
def cell_map(res):
    hos = res['ho_events']
    cells = sorted(set([h['source_pci'] for h in hos] + [h['target_pci'] for h in hos]) - {None})
    if not cells:
        return '<p class="muted">No handover events found.</p>'
    n = len(cells)
    W, H, R = 620, 460, 165
    cx, cy = W / 2, H / 2 + 10
    pos = {}
    for i, p in enumerate(cells):
        a = -math.pi / 2 + 2 * math.pi * i / n
        pos[p] = (cx + R * math.cos(a), cy + R * math.sin(a))
    edges = collections.defaultdict(lambda: [0, 0])
    for h in hos:
        if h['source_pci'] is None or h['target_pci'] is None:
            continue
        edges[(h['source_pci'], h['target_pci'])][0 if h['ok'] else 1] += 1
    out = ['<svg viewBox="0 0 %d %d" width="100%%" style="max-width:%dpx" role="img" aria-label="cell map">' % (W, H, W)]
    out.append('<defs><marker id="ah-g" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="%s"/></marker>'
               '<marker id="ah-r" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="%s"/></marker></defs>' % (OK, NG))
    node_r = 26
    for (s, t), (ok, ng) in sorted(edges.items()):
        (x1, y1), (x2, y2) = pos[s], pos[t]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1
        ux, uy = dx / L, dy / L
        # offset to the right so the reverse direction gets its own lane
        ox, oy = -uy * 9, ux * 9
        sx, sy = x1 + ux * (node_r + 2) + ox, y1 + uy * (node_r + 2) + oy
        ex, ey = x2 - ux * (node_r + 4) + ox, y2 - uy * (node_r + 4) + oy
        mx, my = (sx + ex) / 2 + ox * 2.2, (sy + ey) / 2 + oy * 2.2
        col = NG if ng else OK
        w = 1.2 + min(4, (ok + ng) / 5)
        out.append('<path d="M%.1f,%.1f Q%.1f,%.1f %.1f,%.1f" fill="none" stroke="%s" stroke-width="%.1f" opacity="0.85" marker-end="url(#ah-%s)"/>' % (
            sx, sy, mx, my, ex, ey, col, w, 'r' if ng else 'g'))
        lbl = '%d OK' % ok + (' / %d NG' % ng if ng else '')
        tx, ty = (sx + 2 * mx + ex) / 4, (sy + 2 * my + ey) / 4
        out.append('<rect x="%.1f" y="%.1f" width="%d" height="14" rx="3" fill="white" opacity="0.9"/>' % (tx - len(lbl) * 3.1, ty - 10, len(lbl) * 6.2))
        out.append('<text x="%.1f" y="%.1f" font-size="10" text-anchor="middle" fill="%s" font-weight="600">%s</text>' % (tx, ty + 1, col, lbl))
    for p, (x, y) in pos.items():
        du = res.get('cell_du', {}).get(str(p)) or res.get('cell_du', {}).get(p)
        out.append('<circle cx="%.1f" cy="%.1f" r="%d" fill="#e8f0fe" stroke="%s" stroke-width="1.5"/>' % (x, y, node_r, BLUE))
        out.append('<text x="%.1f" y="%.1f" font-size="12" text-anchor="middle" font-weight="700" fill="%s">PCI</text>' % (x, y - 3, INK))
        out.append('<text x="%.1f" y="%.1f" font-size="13" text-anchor="middle" font-weight="700" fill="%s">%s</text>' % (x, y + 12, INK, p))
    out.append('</svg>')
    out.append('<p class="small muted">%s %s</p>' % (_('Arrow = handover direction, label = attempts on that path; red = at least one NG. Cells per DU:'), esc(du_groups(res))))
    return '\n'.join(out)


def du_groups(res):
    g = collections.defaultdict(list)
    for p, du in res.get('cell_du', {}).items():
        g[du].append(int(p) if str(p).isdigit() else p)
    return '; '.join('%s: PCI %s' % (du, ', '.join(map(str, sorted(v)))) for du, v in sorted(g.items())) or 'n/a'


# ------------------------------------------------------------------------------------ journey timeline
def journey(res):
    hos = res['ho_events']
    rlf = res.get('other_rlf', [])
    cells = sorted(set([h['source_pci'] for h in hos] + [h['target_pci'] for h in hos] + [e.get('pci_new_cell') for e in rlf] + [e.get('pci') for e in rlf]) - {None})
    if not hos:
        return ''
    t0, t1 = res['first_ts'], res['last_ts']
    W, left, right, top, lane_h = 1100, 70, 20, 30, 34
    H = top + lane_h * len(cells) + 84
    ys = {p: top + lane_h * i + lane_h / 2 for i, p in enumerate(cells)}

    def X(ts):
        return left + (W - left - right) * (ts - t0) / max(1e-9, (t1 - t0))
    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="journey timeline">' % (W, H)]
    for p in cells:
        y = ys[p]
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>' % (left, y, W - right, y, LINE))
        out.append('<text x="%d" y="%.1f" font-size="11" text-anchor="end" fill="%s" font-weight="600">PCI %s</text>' % (left - 8, y + 4, INK, p))
    # time axis ticks every ~5 min
    span = t1 - t0
    step = 60 if span < 900 else 300 if span < 5400 else 900
    import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(res.get('tz', 'UTC'))
    except Exception:
        tz = datetime.timezone.utc
    k = math.ceil(t0 / step) * step
    while k <= t1:
        x = X(k)
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-dasharray="2 4"/>' % (x, top - 6, x, H - 50, LINE))
        out.append('<text x="%.1f" y="%d" font-size="10" text-anchor="middle" fill="%s">%s</text>' % (x, H - 36, MUTED, datetime.datetime.fromtimestamp(k, tz).strftime('%H:%M')))
        k += step
    for l in (res.get('laps') or {}).get('laps', []):
        if l.get('partial_start'):
            continue
        x = X(l['start_ts'])
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1"/>' % (x, top - 14, x, H - 50, '#b0b6bd'))
        out.append('<text x="%.1f" y="%d" font-size="9" fill="%s">%s %d</text>' % (x + 2, top - 16, MUTED, _('lap'), l['n']))
    # UE paths: connect the events of each UE label so the reader sees "one car going around"
    by_ue = collections.defaultdict(list)
    for h in hos:
        by_ue[h['ue_label']].append(h)
    for lbl, evs in by_ue.items():
        pts = []
        for h in evs:
            if h['source_pci'] in ys:
                pts.append((X(h['ts']), ys[h['source_pci']]))
            if h['ok'] and h['target_pci'] in ys:
                pts.append((X(h['complete_ts']), ys[h['target_pci']]))
        if len(pts) > 1:
            out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1" opacity="0.5"/>' % (' '.join('%.1f,%.1f' % p for p in pts), BLUE))
    last_x = -1e9
    for h in hos:
        if h['source_pci'] not in ys or h['target_pci'] not in ys:
            continue
        x = X(h['ts'])
        if x - last_x < 6:          # ping-pong: several HOs within a few seconds would overlap - spread them so each arrow is visible
            x = last_x + 6
        last_x = x
        y1, y2 = ys[h['source_pci']], ys[h['target_pci']]
        col = OK if h['ok'] else NG
        if h['ok'] and h.get('post_ho_rlf'):
            col = RLF
        elif h['ok'] and h.get('post_ho_drop') and not h['post_ho_drop'].get('core_initiated'):
            col = DROP
        d = 1 if y2 > y1 else -1
        dash = ' stroke-dasharray="3 2"' if col == RLF else ''
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"%s/>' % (x, y1, x, y2 - 5 * d, col, dash))
        out.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="%s"/>' % (x, y2, x - 4, y2 - 7 * d, x + 4, y2 - 7 * d, col))
        if col == RLF:
            out.append('<text x="%.1f" y="%.1f" font-size="9" text-anchor="middle" fill="%s" font-weight="700">RLF</text>' % (x, max(y1, y2) + 12, RLF))
        if not h['ok']:
            out.append('<text x="%.1f" y="%.1f" font-size="10" text-anchor="middle" fill="%s" font-weight="700">#%s</text>' % (x, min(y1, y2) - 6, NG, h['id']))
            out.append('<circle cx="%.1f" cy="%.1f" r="6" fill="none" stroke="%s" stroke-width="1.5"/>' % (x, y1, NG))
    for e in rlf:
        if e.get('pci_new_cell') in ys:
            x, y = X(e['ts']), ys[e['pci_new_cell']]
            out.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="%s" opacity="0.8"><title>RLF: re-establishment (%s) was on PCI %s</title></polygon>' % (
                x, y - 6, x + 6, y, x, y + 6, x - 6, y, GREY, e['cause'], e['pci']))
    ly = H - 26
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2"/><text x="%d" y="%d" font-size="10" fill="%s">%s</text>' % (left, ly, left + 18, ly, OK, left + 22, ly + 3, MUTED, _('HO OK')))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2"/><text x="%d" y="%d" font-size="10" fill="%s">%s</text>' % (left + 70, ly, left + 88, ly, NG, left + 92, ly + 3, MUTED, _('HO NG (circle on source cell, # = event id)')))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2" stroke-dasharray="3 2"/><text x="%d" y="%d" font-size="10" fill="%s">%s</text>' % (left + 330, ly, left + 348, ly, RLF, left + 352, ly + 3, MUTED, _('HO OK, then re-establishment (RLF)')))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2"/><text x="%d" y="%d" font-size="10" fill="%s">%s</text>' % (left, ly + 12, left + 18, ly + 12, DROP, left + 22, ly + 15, MUTED, _('HO OK, then context released (drop)')))
    out.append('<polygon points="%d,%d %d,%d %d,%d %d,%d" fill="%s"/><text x="%d" y="%d" font-size="10" fill="%s">%s</text>' % (
        left + 330, ly + 7, left + 335, ly + 12, left + 330, ly + 17, left + 325, ly + 12, GREY, left + 342, ly + 15, MUTED, _('re-establishment without HO (on the cell where it was sent)')))
    out.append('<text x="%d" y="%d" font-size="10" fill="%s">%s</text>' % (left, ly + 24, MUTED, _('arrows closer than a few seconds (ping-pong) are spread apart so each HO stays visible')))
    out.append('</svg>')
    return '\n'.join(out)


# ------------------------------------------------------------------------------------ sequence diagram for one event
def sequence(res, h):
    """Real message flow of one HO attempt, from the triggering report to its resolution."""
    ue = next((u for u in res['ues'] if u['cu_id'] == h['cu_id']), None)
    msgs = list(ue['msgs']) if ue else []
    t_start = (h['trigger']['ts'] if h['trigger'] else h['ts']) - 0.3
    t_end = h['ts'] + 3.5
    if h['ok']:
        t_end = h['complete_ts'] + 0.3
    for key in ('reest', 'post_ho_rlf', 'post_ho_drop', 'release', 'release_req', 'reattach'):
        if h.get(key):
            t_end = max(t_end, h[key]['ts'] + 0.3)
    # the re-establishment / re-attach may live in another UE context: make sure it is in the list once
    for key, text in (('reest', lambda r: 'RRCReestablishmentRequest cause=%s (was on PCI %s) sent on PCI %s' % (r['cause'], r['last_pci'], r['on_pci'])),
                      ('reattach', lambda r: 'RRCSetupRequest (new connection) on PCI %s%s' % (r['on_pci'], '' if r.get('same_ue_confirmed') else ', probably same UE'))):
        r = h.get(key)
        if r and not any(abs(m[0] - r['ts']) < 0.005 for m in msgs):
            msgs.append((r['ts'], r['time'], 'UE->DU', text(r)))
    sel = sorted([m for m in msgs if t_start <= m[0] <= t_end], key=lambda m: m[0])[:14]
    lanes = [_('UE'), _('source') + ' ' + pci_lbl(h['source_pci']), 'gNB-CU', _('target') + ' ' + pci_lbl(h['target_pci'])]
    lx = [70, 215, 360, 505]
    top, sh = 50, 27
    Hh = top + sh * len(sel) + 20
    out = ['<svg viewBox="0 0 580 %d" width="100%%" style="max-width:580px" role="img">' % Hh]
    for x, name in zip(lx, lanes):
        out.append('<text x="%d" y="22" font-size="11" text-anchor="middle" font-weight="600" fill="%s">%s</text>' % (x, INK, esc(name)))
        out.append('<line x1="%d" y1="30" x2="%d" y2="%d" stroke="%s" stroke-dasharray="3 3"/>' % (x, x, Hh - 8, LINE))
    import re
    for i, (ts, tstr, dirn, text) in enumerate(sel):
        y = top + sh * i
        a, b = {'UE->CU': (0, 2), 'CU->UE': (2, 0), 'UE->DU': (0, 1), 'CU->DU': (2, 1), 'DU->CU': (1, 2)}.get(dirn, (0, 2))
        tl = text.lower()
        col = INK
        if 'reestablishmentrequest' in tl:
            col = RLF
        elif 'release' in tl and 'normal' not in tl:
            col = DROP
        elif 'reconfigurationcomplete' in tl:
            col = OK
        elif 'ho command' in tl:
            col = BLUE
        elif 'setuprequest' in tl:
            col = WARN
        if 'reestablishmentrequest' in tl or 'setuprequest' in tl:
            m = re.search(r'sent on PCI (\d+)', text) or re.search(r'\) on PCI (\d+)', text)
            on = m.group(1) if m else None
            b = 3 if on == str(h['target_pci']) else 1
            text = re.sub(r' sent on PCI \d+', '', text)
            if on not in (str(h['target_pci']), str(h['source_pci'])):
                text += ' [sent on PCI %s, another cell]' % on
        x1, x2 = lx[a], lx[b]
        d = 1 if x2 > x1 else -1
        out.append('<text x="4" y="%d" font-size="9" fill="%s">%s</text>' % (y + 3, MUTED, esc(tstr[-9:])))
        out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.5"/>' % (x1, y, x2 - 6 * d, y, col))
        out.append('<polygon points="%d,%d %d,%d %d,%d" fill="%s"/>' % (x2, y, x2 - 8 * d, y - 4, x2 - 8 * d, y + 4, col))
        if abs(x2 - x1) < 200:
            out.append('<text x="%d" y="%d" font-size="9.5" fill="%s">%s</text>' % (min(x1, x2) + 4, y - 5, col, esc(text[:70])))
        else:
            out.append('<text x="%d" y="%d" font-size="9.5" text-anchor="middle" fill="%s">%s</text>' % ((x1 + x2) / 2, y - 5, col, esc(text[:70])))
    out.append('</svg>')
    return '\n'.join(out)


# ------------------------------------------------------------------------------------ page
def build(res, title=None):
    hos = res['ho_events']
    n, ok, ng = len(hos), res['ho_ok'], res['ho_ng']
    rate = ('%.1f%%' % (100.0 * ok / n)) if n else '-'
    lat = sorted(h['latency_ms'] for h in hos if h['ok'] and h['latency_ms'] is not None)
    med = ('%.0f ms' % lat[len(lat) // 2]) if lat else '-'
    post = sum(1 for h in hos if h.get('post_ho_rlf'))
    drops = [h for h in hos if h.get('post_ho_drop') and not h['post_ho_drop'].get('core_initiated')]
    ended = [h for h in hos if h.get('post_ho_drop') and h['post_ho_drop'].get('core_initiated')]
    drops_mod = sum(1 for h in drops if h['post_ho_drop'].get('mod_unanswered'))
    um = res.get('unanswered_meas', [])
    fc = collections.Counter(h.get('fail_class', '') for h in hos if not h['ok'])
    title = title or _('Handover analysis - %s') % res['capture']

    def tile(v, k, col=INK):
        return '<div class="tile"><div class="v" style="color:%s">%s</div><div class="k">%s</div></div>' % (col, esc(v), esc(k))
    tiles = [tile(n, _('HO attempts')), tile(ok, 'OK', OK), tile(ng, 'NG', NG), tile(rate, _('success rate'), OK if n and ok / n >= 0.95 else WARN),
             tile(med, _('median HO time (command -> complete)')), tile(post, _('OK but re-established right after (RLF)'), RLF if post else INK),
             tile(len(drops), _('OK but context released within 5 s (drop)'), DROP if drops else INK),
             tile(len(ended), _('OK, then the core ended the session (normal)'), GREY),
             tile(len(res.get('other_rlf', [])), _('re-establishments not linked to a HO'), GREY),
             tile(len(um), _('measurement reports without HO'), GREY)]
    laps = res.get('laps') or {}
    if laps.get('laps'):
        tiles.insert(1, tile(_('%d (%d clean)') % (laps['complete'], laps['clean']), _('complete laps (clean = only OK handovers)'), OK if laps['clean'] else WARN))
    laps_section = ''
    if laps.get('laps'):
        lrows = []
        for l in laps['laps']:
            if l.get('in_progress'):
                kind, col = _('in progress at end of capture'), MUTED
            elif l.get('partial_start'):
                kind, col = _('partial (capture starts mid-lap)'), MUTED
            elif l['complete']:
                kind, col = (_('complete, clean') if l['clean'] else _('complete')), (OK if l['clean'] else INK)
            else:
                kind, col = _('incomplete - missed %s') % ', '.join('PCI %s' % m for m in l['missed']), NG
            lrows.append('<tr><td>%d</td><td>%s</td><td>%s</td><td class="num">%s</td><td style="color:%s;font-weight:600">%s</td><td class="num">%d</td><td class="num" style="color:%s">%d</td><td class="num" style="color:%s">%d</td><td class="num" style="color:%s">%d</td><td class="num">%d</td></tr>' % (
                l['n'], esc(fmt_local(l['start_ts'], res.get('tz', 'UTC'))), esc(fmt_local(l['end_ts'], res.get('tz', 'UTC'))) if l['end_ts'] else _('end'), l['duration_s'] if l['duration_s'] is not None else '',
                col, kind, l['n_ho'], NG if l['n_ng'] else INK, l['n_ng'], RLF if l['n_reest'] else INK, l['n_reest'], DROP if l['n_new'] else INK, l['n_new'], l['n_pingpong']))
        laps_section = (_('<h2>1b. Laps</h2><p class="small">Route learned from the dominant handover direction: <b>%s</b>. A lap is counted each time the UE enters PCI %s again; it is <b>complete</b> when all cells were visited on the way and <b>clean</b> when every cell change in it was a successful handover (no re-establishment, no dropped-and-reconnected, no NG). Ping-pong = re-entering a cell already visited in that lap.</p>')
                        + _('<div class="card"><table><tr><th>lap</th><th>start</th><th>end</th><th>duration s</th><th>result</th><th>HO OK</th><th>HO NG</th><th>re-establishments</th><th>new connections</th><th>ping-pong</th></tr>') + '%s</table></div>'
                        + _('<p class="small"><b>%d complete laps</b> (%d clean), %d incomplete, %d partial at the start/end of the capture.</p>')) % (
            esc(' → '.join('PCI %s' % p for p in laps['ring'] + [laps['ring'][0]])), laps['ring'][0], ''.join(lrows), laps['complete'], laps['clean'], laps['incomplete'], laps['partial'])
    drops_note = ''
    if drops:
        drops_note = _('<p class="small"><b style="color:%s">%d handovers completed but the UE context was released within 5 s</b> (call dropped right after the switch)%s. They count as OK above; see section 6 for their message flow.</p>') % (
            DROP, len(drops), _(' - in %d of them the DU never answered the CU\'s post-HO UE Context Modification Request, so the CU gave up after its timer') % drops_mod if drops_mod else '')
    ng_rows = ''.join('<tr><td>%s</td><td class="num">%d</td><td>%s</td></tr>' % (esc(k), c, esc(_(FAIL_HELP.get(k, FAIL_HELP.get(k.split('/')[0], ''))))) for k, c in fc.most_common())

    rows = []
    for h in hos:
        cls = 'ok' if h['ok'] else 'ng'
        if h['ok'] and h.get('post_ho_rlf'):
            cls = 'rlf'
        elif h['ok'] and h.get('post_ho_drop') and not h['post_ho_drop'].get('core_initiated'):
            cls = 'drop'
        delta = h.get('delta_db')
        rows.append('<tr class="%s"><td>%d</td><td>%s</td><td>%s</td><td>%s &rarr; %s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                    '<td>%s</td><td>%s</td><td><b>%s</b></td><td>%s</td><td class="small">%s</td></tr>' % (
                        cls, h['id'], esc(h['time']), esc(h['ue_label']), pci_lbl(h['source_pci']), pci_lbl(h['target_pci']),
                        esc(h['serving_rsrp']), esc(h['target_rsrp']), ('%+d' % delta) if delta is not None else '',
                        esc(h['trigger']['event'] if h['trigger'] else '-'), esc(h['type']), h['result'],
                        esc(h.get('fail_class', '') or ('%.0f ms' % h['latency_ms'] if h['latency_ms'] is not None else '')), esc(h['detail'])))
    ng_cards = []
    for h in hos:
        if h['ok'] and not (h.get('post_ho_rlf') or (h.get('post_ho_drop') and not h['post_ho_drop'].get('core_initiated'))):
            continue
        tag = 'NG - ' + esc(h.get('fail_class', '')) if not h['ok'] else (_('OK, then RLF') if h.get('post_ho_rlf') else _('OK, then dropped (context released)'))
        head = '#%d %s CU-UE-ID %s: %s &rarr; %s - <span style="color:%s">%s</span>' % (h['id'], esc(h['time']), esc(h['ue_label']), pci_lbl(h['source_pci']), pci_lbl(h['target_pci']),
                                                                                NG if not h['ok'] else (RLF if h.get('post_ho_rlf') else DROP), tag)
        rs = _('Measurement at trigger: serving %s dBm, target %s dBm (%s).') % (h['serving_rsrp'], h['target_rsrp'], h['trigger']['event'] if h['trigger'] else '-') if h['trigger'] else _('No measurement report found just before the command.')
        ng_cards.append('<div class="card"><div class="cardhead">%s</div><p class="small">%s<br>%s</p>%s</div>' % (head, rs, esc(h['detail']), sequence(res, h)))
    um_rows = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>' % (
        esc(e['time']), esc(e.get('ue_label', '')), pci_lbl(e['serving_pci']), esc(e['serving_rsrp']), pci_lbl(e['best_pci']), esc(e['best_rsrp']),
        _('after re-establishment') if e['after_reest'] else '', e['frame']) for e in um)
    rlf_rows = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        esc(fmt_local(e['ts'], res.get('tz', 'UTC'))), esc(e.get('ue_label', '')), esc(e['cause']), pci_lbl(e['pci']), pci_lbl(e.get('pci_new_cell'))) for e in res.get('other_rlf', []))
    pairs = collections.defaultdict(lambda: [0, 0])
    for h in hos:
        pairs[(h['source_pci'], h['target_pci'])][0 if h['ok'] else 1] += 1
    pair_rows = ''.join('<tr><td>%s &rarr; %s</td><td class="num">%d</td><td class="num" style="color:%s">%d</td></tr>' % (pci_lbl(s), pci_lbl(t), a, NG if b else INK, b)
                        for (s, t), (a, b) in sorted(pairs.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))))

    return (BODY_JA if LANG == 'ja' else BODY_EN).format(
        title=esc(title), capture=esc(res['capture']), t0=esc(res['first_time']), t1=esc(res['last_time']), tz=esc(res['tz']), dur=res['duration_s'],
        f1=res['stats'].get('f1ap_msgs', 0), nue=len(res['ues']), nmeas=res['stats'].get('measurement_reports', 0), nreest=res['stats'].get('reestablishment_requests', 0),
        tiles=''.join(tiles), ng_rows=ng_rows or '<tr><td colspan="3">%s</td></tr>' % _('none'), explainer=explainer(), cellmap=cell_map(res), journey=journey(res),
        rows=''.join(rows), ng_cards=''.join(ng_cards) or '<p class="muted">%s</p>' % _('No NG events.'), rlf_rows=rlf_rows or '<tr><td colspan="5">%s</td></tr>' % _('none'),
        um_rows=um_rows or '<tr><td colspan="8">%s</td></tr>' % _('none'), drops_note=drops_note, laps_section=laps_section,
        pair_rows=pair_rows, cells=esc(', '.join('%s = PCI %s' % kv for kv in sorted(res['cellmap'].items()))),
        ok=OK, ng=NG, warn=WARN, rlf=RLF, drop=DROP)


def fmt_local(ts, tz):
    import datetime
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(tz)
    except Exception:
        z = datetime.timezone.utc
    return datetime.datetime.fromtimestamp(ts, z).strftime('%H:%M:%S.%f')[:-3]


FAIL_HELP = {
    'Reestablishment/handoverFailure': 'UE could not get into the target cell before timer T304 expired, fell back to the old cell configuration and asked to re-establish.',
    'Reestablishment/otherFailure': 'Radio link failure (RLF) around the HO: the UE lost the link (on the source, or on the target right after switching) and asked to re-establish.',
    'Reestablishment/reconfigurationFailure': 'UE could not apply the configuration in the HO command (configuration problem).',
    'NoResponse/UEContextRelease': 'HO command sent, but the UE never answered (no RRCReconfigurationComplete, no re-establishment); the CU released the UE context after its timer.',
    'NoResponse/UEContextReleaseRequest': 'HO command sent, UE never answered; the DU detected the loss and asked the CU to release the UE.',
    'NoResponse': 'HO command sent, nothing came back.',
    'NoResponse/EndOfCapture': 'HO command sent right before the capture ended - outcome unknown.',
}

STYLE = '''<style>
 body{{font-family:-apple-system,"Segoe UI",Roboto,"Noto Sans JP",Helvetica,Arial,sans-serif;color:#202124;background:#f8f9fa;margin:0;padding:24px 20px 60px}}
 h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:34px 0 10px;border-bottom:2px solid #e8eaed;padding-bottom:4px}}
 .muted{{color:#5f6368}} .small{{font-size:12px;color:#3c4043}}
 .tiles{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
 .tile{{background:#fff;border:1px solid #dadce0;border-radius:8px;padding:10px 16px;min-width:120px}}
 .tile .v{{font-size:24px;font-weight:700}} .tile .k{{font-size:11px;color:#5f6368}}
 .row{{display:flex;gap:14px}} .wrap{{flex-wrap:wrap}}
 .card{{background:#fff;border:1px solid #dadce0;border-radius:8px;padding:12px;margin:8px 0;max-width:100%;overflow-x:auto}}
 .cardhead{{font-weight:600;font-size:13px;margin-bottom:4px}}
 table{{border-collapse:collapse;background:#fff;font-size:12px;width:100%}} th,td{{border-bottom:1px solid #e8eaed;padding:5px 8px;text-align:left;vertical-align:top}}
 th{{background:#f1f3f4;position:sticky;top:0}} td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 tr.ok td:nth-child(10){{color:{ok}}} tr.ng{{background:#fce8e6}} tr.ng td:nth-child(10){{color:{ng}}} tr.rlf{{background:#fdebd0}} tr.rlf td:nth-child(10){{color:{rlf}}} tr.drop{{background:#e0f2f1}} tr.drop td:nth-child(10){{color:{drop}}}
 .scroll{{overflow-x:auto}} .legend span{{display:inline-block;margin-right:14px;font-size:12px}}
 .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} @media(max-width:900px){{.grid2{{grid-template-columns:1fr}}}}
 .langbar{{position:sticky;top:0;z-index:5;background:#f8f9fa;padding:6px 0 8px;margin-bottom:8px}} .langbar button{{font-size:12px;padding:4px 12px;border:1px solid #dadce0;border-radius:14px;background:#fff;cursor:pointer;margin-right:6px}} .langbar button.on{{background:#202124;color:#fff;border-color:#202124}}
</style>
'''

BODY_EN = '''
<h1>{title}</h1>
<div class="muted small">Capture <b>{capture}</b> &middot; {t0} - {t1} ({tz}, {dur} s) &middot; {f1} F1AP messages &middot; {nue} UE contexts &middot; {nmeas} measurement reports &middot; {nreest} re-establishment requests</div>
<div class="tiles">{tiles}</div>

<h2>1. Result at a glance</h2>
<div class="grid2">
 <div class="card"><div class="cardhead">Why the NG handovers failed</div>
 <table><tr><th>failure class</th><th>count</th><th>meaning</th></tr>{ng_rows}</table></div>
 <div class="card"><div class="cardhead">Per cell pair (source &rarr; target)</div>
 <div class="scroll" style="max-height:320px;overflow-y:auto"><table><tr><th>path</th><th>OK</th><th>NG</th></tr>{pair_rows}</table></div></div>
</div>

{drops_note}

{laps_section}

<h2>2. How to read a handover (simplified)</h2>
<p class="small">The UE (phone / modem) measures neighbour cells and reports when a neighbour becomes stronger than the serving cell (event A3). The CU then sends a <b>handover command</b> (RRCReconfiguration with reconfigurationWithSync, naming the <b>target PCI</b>). If the UE reaches the target cell it answers <b>RRCReconfigurationComplete</b> = <span style="color:{ok}"><b>OK</b></span>. If not, the UE has to re-establish: cause <b>handoverFailure</b> (could not access the target before timer T304 expired) or <b>otherFailure</b> (radio link failure). RSRP is the received power of the cell's reference signal in dBm; around -100 dBm is fine, below -115 dBm is weak.</p>
{explainer}

<h2>3. Cell map - who hands over to whom</h2>
<div class="card">{cellmap}</div>
<p class="small muted">Cell identity to PCI: {cells}</p>

<h2>4. Journey - serving cell over time</h2>
<div class="card">{journey}</div>

<h2>5. Every handover attempt</h2>
<div class="legend"><span style="color:{ok}">&#9632; OK</span><span style="color:{ng}">&#9632; NG</span><span style="color:{rlf}">&#9632; OK but re-established right after (RLF)</span><span style="color:{drop}">&#9632; OK but context released right after (drop)</span><span class="muted">RSRP in dBm; &Delta; = target - serving at the moment of the report</span></div>
<div class="scroll card" style="max-height:600px;overflow-y:auto"><table>
<tr><th>#</th><th>time</th><th>gNB-CU-UE-F1AP-ID</th><th>from &rarr; to</th><th>serving RSRP</th><th>target RSRP</th><th>&Delta;</th><th>trigger</th><th>type</th><th>result</th><th>class / HO time</th><th>what happened</th></tr>
{rows}</table></div>

<h2>6. NG events and post-HO drops in detail (actual message flow)</h2>
{ng_cards}

<h2>7. Measurement reports that did not lead to a handover</h2>
<p class="small muted">The UE reported a stronger neighbour (event A3) but no handover command followed within 2 s. Reports marked "after re-establishment" came from a UE that had just re-established - a CU that stops handing over after a re-establishment shows up here as a cluster.</p>
<div class="card"><table><tr><th>time</th><th>gNB-CU-UE-F1AP-ID</th><th>serving</th><th>serving RSRP</th><th>best neighbour</th><th>its RSRP</th><th>context</th><th>frame</th></tr>{um_rows}</table></div>

<h2>8. Radio link failures not linked to a handover</h2>
<p class="small muted">RRCReestablishmentRequest messages with no handover command before them. When "was on" and "sent on" differ, the UE moved to a new cell by re-establishment instead of by handover (typically it lost the link before a HO could be triggered).</p>
<div class="card"><table><tr><th>time</th><th>gNB-CU-UE-F1AP-ID</th><th>cause</th><th>was on</th><th>sent on</th></tr>{rlf_rows}</table></div>
<p class="small muted">Generated by ho_analyze.py / ho_report.py (pure-Python F1AP + NR RRC decode with pycrate). RSRP = SS-RSRP index - 156 dBm (TS 38.133).</p>
'''



BODY_JA = '''
<h1>{title}</h1>
<div class="muted small">キャプチャ <b>{capture}</b> &middot; {t0} - {t1} ({tz}, {dur} 秒) &middot; F1AP メッセージ {f1} 件 &middot; UE コンテキスト {nue} 件 &middot; 測定報告 {nmeas} 件 &middot; 再確立要求 {nreest} 件</div>
<div class="tiles">{tiles}</div>

<h2>1. 結果サマリ</h2>
<div class="grid2">
 <div class="card"><div class="cardhead">NG ハンドオーバの失敗理由</div>
 <table><tr><th>失敗クラス</th><th>件数</th><th>意味</th></tr>{ng_rows}</table></div>
 <div class="card"><div class="cardhead">セルペア別 (ソース &rarr; ターゲット)</div>
 <div class="scroll" style="max-height:320px;overflow-y:auto"><table><tr><th>経路</th><th>OK</th><th>NG</th></tr>{pair_rows}</table></div></div>
</div>

{drops_note}

{laps_section}

<h2>2. ハンドオーバの読み方 (簡略版)</h2>
<p class="small">UE (端末) は隣接セルを測定し、隣接セルが在圏セルより強くなると報告します (イベント A3)。CU は <b>ハンドオーバ指示</b> (reconfigurationWithSync を含む RRCReconfiguration。<b>ターゲット PCI</b> を指定) を送ります。UE がターゲットセルに到達できれば <b>RRCReconfigurationComplete</b> を返し、<span style="color:{ok}"><b>OK</b></span> となります。到達できない場合 UE は再確立 (re-establishment) を行います: 原因 <b>handoverFailure</b> (タイマ T304 満了までにターゲットへアクセスできなかった) または <b>otherFailure</b> (無線リンク障害 RLF)。RSRP はセルの参照信号の受信電力 [dBm] で、-100 dBm 前後は良好、-115 dBm 以下は弱い状態です。</p>
{explainer}

<h2>3. セルマップ - どのセルからどのセルへ</h2>
<div class="card">{cellmap}</div>
<p class="small muted">Cell Identity と PCI の対応: {cells}</p>

<h2>4. 走行経路 - 在圏セルの時間推移</h2>
<div class="card">{journey}</div>

<h2>5. 全ハンドオーバ試行</h2>
<div class="legend"><span style="color:{ok}">&#9632; OK</span><span style="color:{ng}">&#9632; NG</span><span style="color:{rlf}">&#9632; OK 直後に再確立 (RLF)</span><span style="color:{drop}">&#9632; OK 直後にコンテキスト解放 (切断)</span><span class="muted">RSRP は dBm、&Delta; = 報告時点の ターゲット - 在圏</span></div>
<div class="scroll card" style="max-height:600px;overflow-y:auto"><table>
<tr><th>#</th><th>時刻</th><th>gNB-CU-UE-F1AP-ID</th><th>ソース &rarr; ターゲット</th><th>在圏 RSRP</th><th>ターゲット RSRP</th><th>&Delta;</th><th>トリガ</th><th>種別</th><th>結果</th><th>クラス / HO 所要時間</th><th>経過</th></tr>
{rows}</table></div>

<h2>6. NG イベントと HO 直後の切断の詳細 (実際のメッセージフロー)</h2>
{ng_cards}

<h2>7. ハンドオーバに繋がらなかった測定報告</h2>
<p class="small muted">UE はより強い隣接セルを報告 (イベント A3) したが、2 秒以内にハンドオーバ指示が出なかったもの。「再確立後」は直前に再確立した UE からの報告です。再確立後にハンドオーバを出さなくなる CU は、ここに固まって現れます。</p>
<div class="card"><table><tr><th>時刻</th><th>gNB-CU-UE-F1AP-ID</th><th>在圏</th><th>在圏 RSRP</th><th>最強隣接</th><th>その RSRP</th><th>状況</th><th>フレーム</th></tr>{um_rows}</table></div>

<h2>8. ハンドオーバに紐づかない無線リンク障害</h2>
<p class="small muted">直前にハンドオーバ指示のない RRCReestablishmentRequest。「元セル」と「送信セル」が異なる場合、UE はハンドオーバではなく再確立でセルを移動しています (通常は HO がトリガされる前にリンクを失った)。</p>
<div class="card"><table><tr><th>時刻</th><th>gNB-CU-UE-F1AP-ID</th><th>原因</th><th>元セル</th><th>送信セル</th></tr>{rlf_rows}</table></div>
<p class="small muted">ho_analyze.py / ho_report.py により生成 (pycrate による純 Python の F1AP + NR RRC デコード)。RSRP = SS-RSRP index - 156 dBm (TS 38.133)。</p>
'''

JA = {
 'Handover analysis - %s': 'ハンドオーバ解析 - %s',
 'HO attempts': 'HO 試行数', 'success rate': '成功率', 'median HO time (command -> complete)': 'HO 所要時間の中央値 (指示 -> 完了)',
 'OK but re-established right after (RLF)': 'OK だが直後に再確立 (RLF)', 'OK but context released within 5 s (drop)': 'OK だが 5 秒以内にコンテキスト解放 (切断)',
 're-establishments not linked to a HO': 'HO に紐づかない再確立', 'measurement reports without HO': 'HO に繋がらなかった測定報告',
 '%d (%d clean)': '%d (クリーン %d)', 'complete laps (clean = only OK handovers)': '完了周回数 (クリーン = OK ハンドオーバのみ)',
 'in progress at end of capture': 'キャプチャ終了時に走行中', 'partial (capture starts mid-lap)': '部分 (キャプチャが周回途中から開始)',
 'complete, clean': '完了・クリーン', 'complete': '完了', 'incomplete - missed %s': '未完了 - %s を通過せず', 'end': '終了', 'lap': '周回',
 'No measurement report found just before the command.': '指示直前の測定報告が見つかりません。',
 'Measurement at trigger: serving %s dBm, target %s dBm (%s).': 'トリガ時の測定: 在圏 %s dBm、ターゲット %s dBm (%s)。',
 'OK, then RLF': 'OK、その後 RLF', 'OK, then dropped (context released)': 'OK、その後切断 (コンテキスト解放)', 'after re-establishment': '再確立後',
 'OK, then the core ended the session (normal)': 'OK、その後コアがセッションを正常終了',
 'none': 'なし', 'No NG events.': 'NG イベントはありません。',
 'UE': 'UE', 'Source cell': 'ソースセル', 'Target cell': 'ターゲットセル', 'source': 'ソース', 'target': 'ターゲット',
 'OK handover': 'OK ハンドオーバ', 'what a normal, successful HO looks like': '正常に成功した HO の流れ',
 '1. MeasurementReport "neighbour stronger" (A3)': '1. MeasurementReport「隣接が強い」(A3)', '2. prepare UE context': '2. UE コンテキスト準備',
 '3. HO COMMAND (RRCReconfiguration, target PCI)': '3. HO 指示 (RRCReconfiguration、ターゲット PCI)', '4. sync + random access on target cell': '4. ターゲットセルへ同期 + ランダムアクセス',
 '5. RRCReconfigurationComplete = OK': '5. RRCReconfigurationComplete = OK', '6. release old context': '6. 旧コンテキスト解放',
 'NG - handoverFailure': 'NG - handoverFailure', 'UE could not reach the target cell (timer T304 expired)': 'UE がターゲットセルに到達できず (タイマ T304 満了)',
 '1. MeasurementReport': '1. MeasurementReport', '2. HO COMMAND (target PCI)': '2. HO 指示 (ターゲット PCI)', '3. random access on target fails': '3. ターゲットでのランダムアクセス失敗',
 '4. T304 expires, UE falls back to source config': '4. T304 満了、UE はソース設定に戻る', '5. RRCReestablishmentRequest cause=handoverFailure': '5. RRCReestablishmentRequest cause=handoverFailure',
 '6. RRCReestablishment, or RRCSetup if context gone': '6. RRCReestablishment (コンテキストが無ければ RRCSetup)',
 'NG - otherFailure / no response': 'NG - otherFailure / 無応答', 'radio link lost around the HO (RLF), or UE never answered': 'HO 前後で無線リンク喪失 (RLF)、または UE が無応答',
 '1. MeasurementReport (often weak serving RSRP)': '1. MeasurementReport (在圏 RSRP が弱いことが多い)', '3. radio link failure (RLF) detected by UE': '3. UE が無線リンク障害 (RLF) を検出',
 '4. RRCReestablishmentRequest cause=otherFailure': '4. RRCReestablishmentRequest cause=otherFailure', "4'. or no answer at all: CU releases context": "4'. または無応答: CU がコンテキスト解放",
 '5. UE comes back with a new RRCSetupRequest': '5. UE は新たな RRCSetupRequest で再接続',
 'Arrow = handover direction, label = attempts on that path; red = at least one NG. Cells per DU:': '矢印 = ハンドオーバ方向、ラベル = その経路の試行数。赤 = NG が 1 件以上。DU ごとのセル:',
 'HO OK': 'HO OK', 'HO NG (circle on source cell, # = event id)': 'HO NG (ソースセルに丸、# = イベント番号)', 'HO OK, then re-establishment (RLF)': 'HO OK、その後再確立 (RLF)',
 'HO OK, then context released (drop)': 'HO OK、その後コンテキスト解放 (切断)', 're-establishment without HO (on the cell where it was sent)': 'HO なしの再確立 (送信したセル上)',
 'arrows closer than a few seconds (ping-pong) are spread apart so each HO stays visible': '数秒以内に連続する矢印 (ピンポン) は各 HO が見えるよう間隔を空けて表示',
 'Reestablishment/handoverFailure': 'Reestablishment/handoverFailure',
 'UE could not get into the target cell before timer T304 expired, fell back to the old cell configuration and asked to re-establish.': 'タイマ T304 満了までにターゲットセルに入れず、旧セル設定に戻って再確立を要求した。',
 'Radio link failure (RLF) around the HO: the UE lost the link (on the source, or on the target right after switching) and asked to re-establish.': 'HO 前後の無線リンク障害 (RLF): UE がリンクを失い (ソース側、または切替直後のターゲット側)、再確立を要求した。',
 'UE could not apply the configuration in the HO command (configuration problem).': 'UE が HO 指示の設定を適用できなかった (設定の問題)。',
 'HO command sent, but the UE never answered (no RRCReconfigurationComplete, no re-establishment); the CU released the UE context after its timer.': 'HO 指示を送ったが UE が無応答 (RRCReconfigurationComplete も再確立も無し)。CU はタイマ後に UE コンテキストを解放した。',
 'HO command sent, UE never answered; the DU detected the loss and asked the CU to release the UE.': 'HO 指示を送ったが UE が無応答。DU が喪失を検出し CU に解放を要求した。',
 'HO command sent, nothing came back.': 'HO 指示を送ったが何も返ってこなかった。', 'HO command sent right before the capture ended - outcome unknown.': 'キャプチャ終了直前に HO 指示 - 結果不明。',
 '<h2>1b. Laps</h2><p class="small">Route learned from the dominant handover direction: <b>%s</b>. A lap is counted each time the UE enters PCI %s again; it is <b>complete</b> when all cells were visited on the way and <b>clean</b> when every cell change in it was a successful handover (no re-establishment, no dropped-and-reconnected, no NG). Ping-pong = re-entering a cell already visited in that lap.</p>':
   '<h2>1b. 周回</h2><p class="small">主要なハンドオーバ方向から学習した経路: <b>%s</b>。UE が PCI %s に再び入るたびに 1 周と数えます。途中の全セルを通過していれば <b>完了</b>、周回内の全セル移動が成功したハンドオーバであれば (再確立・切断再接続・NG なし) <b>クリーン</b> です。ピンポン = その周回で既に通過したセルへの再進入。</p>',
 '<div class="card"><table><tr><th>lap</th><th>start</th><th>end</th><th>duration s</th><th>result</th><th>HO OK</th><th>HO NG</th><th>re-establishments</th><th>new connections</th><th>ping-pong</th></tr>':
   '<div class="card"><table><tr><th>周回</th><th>開始</th><th>終了</th><th>所要 秒</th><th>結果</th><th>HO OK</th><th>HO NG</th><th>再確立</th><th>新規接続</th><th>ピンポン</th></tr>',
 '<p class="small"><b>%d complete laps</b> (%d clean), %d incomplete, %d partial at the start/end of the capture.</p>': '<p class="small"><b>完了周回 %d</b> (クリーン %d)、未完了 %d、キャプチャ開始/終了時の部分周回 %d。</p>',
 '<p class="small"><b style="color:%s">%d handovers completed but the UE context was released within 5 s</b> (call dropped right after the switch)%s. They count as OK above; see section 6 for their message flow.</p>':
   '<p class="small"><b style="color:%s">%d 件のハンドオーバは完了したが 5 秒以内に UE コンテキストが解放</b> (切替直後に切断)%s。上の集計では OK に含まれます。メッセージフローは 6 章を参照。</p>',
 " - in %d of them the DU never answered the CU's post-HO UE Context Modification Request, so the CU gave up after its timer": " - うち %d 件は HO 後の UE Context Modification Request に DU が応答せず、CU がタイマ後に諦めたもの",
}


def page(res, title=None, lang='both'):
    """Full HTML page: 'en', 'ja', or 'both' (one page with an EN / JA switch, English shown first)."""
    global LANG
    style = STYLE.format(ok=OK, ng=NG, warn=WARN, rlf=RLF, drop=DROP)
    head = '<!DOCTYPE html>\n<html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>%s</title>\n%s</head><body>\n' % (
        'ja' if lang == 'ja' else 'en', esc(title or 'Handover analysis'), style)
    if lang in ('en', 'ja'):
        LANG = lang
        return head + build(res, title) + '</body></html>\n'
    LANG = 'en'; en = build(res, title)
    LANG = 'ja'; ja = build(res, title)
    LANG = 'en'
    bar = ('<div class="langbar"><button id="btn-en" class="on" onclick="setLang(\'en\')">English</button><button id="btn-ja" onclick="setLang(\'ja\')">日本語</button></div>')
    script = ('<script>function setLang(l){document.getElementById("lang-en").hidden=l!=="en";document.getElementById("lang-ja").hidden=l!=="ja";'
              'document.getElementById("btn-en").classList.toggle("on",l==="en");document.getElementById("btn-ja").classList.toggle("on",l==="ja");'
              'document.documentElement.lang=l;try{localStorage.setItem("ho_lang",l)}catch(e){}}'
              'try{var s=localStorage.getItem("ho_lang");if(s==="ja")setLang("ja")}catch(e){}</script>')
    return head + bar + '<div id="lang-en">' + en + '</div><div id="lang-ja" hidden>' + ja + '</div>' + script + '</body></html>\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('events_json')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--title', default=None)
    ap.add_argument('--lang', default='both', choices=['en', 'ja', 'both'], help='page language: en, ja, or both (default: one page with an EN/JA switch)')
    a = ap.parse_args()
    res = json.load(open(a.events_json))
    out = a.out or os.path.join(os.path.dirname(a.events_json), 'ho_report.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(page(res, a.title, a.lang))
    print('wrote', out)
