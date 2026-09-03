#!/usr/bin/env python3
"""Stage 2: out/events.csv -> out/flows.json.

Packets on their own say nothing. This groups them into the things that
actually happened: a request and the answer it got, a tunnel and how much it
carried, a connection that stayed up or did not.

Nothing here invents meaning. It matches messages to each other and counts
what it sees; the words come from knowledge/ at stage 3.

Usage: python scripts/2_sessionize.py <out/events.csv> <out/flows.json>
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import knowledge  # noqa: E402

# ngap.NGAP_PDU / f1ap.F1AP_PDU: 0 initiating, 1 successful, 2 unsuccessful.
# Verified against the dissector value table, not assumed.
PDU_KIND = {0: "request", 1: "success", 2: "failure"}

# PFCP cause values below 64 are acceptances, 64 and above are rejections
# (3GPP TS 29.244 table 8.2.1-1). The cause text itself comes from knowledge/.
PFCP_REJECT_FROM = 64


def as_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    except ValueError:
        return None


def classify(row):
    """Turn one CSV row into an event, or None if it is not one we track."""
    event = {
        "frame": as_int(row.get("frame")) or 0,
        "time": float(row.get("time") or 0.0),
        "bytes": as_int(row.get("bytes")) or 0,
        "src": row.get("src") or "",
        "dst": row.get("dst") or "",
    }
    ngap_proc = as_int(row.get("ngap_proc"))
    f1ap_proc = as_int(row.get("f1ap_proc"))
    pfcp_type = as_int(row.get("pfcp_type"))
    gtp_type = as_int(row.get("gtp_type"))
    sctp_chunk = as_int(row.get("sctp_chunk"))

    if ngap_proc is not None:
        event.update(
            protocol="ngap", code=ngap_proc,
            kind=PDU_KIND.get(as_int(row.get("ngap_pdu")), "request"),
            subject_ids={"ran": row.get("ran_ue_id") or "",
                         "amf": row.get("amf_ue_id") or ""},
        )
    elif f1ap_proc is not None:
        event.update(
            protocol="f1ap", code=f1ap_proc,
            kind=PDU_KIND.get(as_int(row.get("f1ap_pdu")), "request"),
            subject_ids={"du": row.get("du_ue_id") or "",
                         "cu": row.get("cu_ue_id") or ""},
        )
    elif pfcp_type is not None:
        event.update(
            protocol="pfcp", code=pfcp_type,
            kind="pending",  # decided from the message name, below
            seq=row.get("pfcp_seq") or "",
            seid=row.get("pfcp_seid") or "",
            cause=as_int(row.get("pfcp_cause")),
        )
    elif gtp_type is not None:
        event.update(protocol="gtp", code=gtp_type, kind="data",
                     teid=row.get("gtp_teid") or "")
    elif sctp_chunk is not None:
        event.update(protocol="sctp", code=sctp_chunk, kind="transport")
    else:
        return None
    return event


def kind_from_name(name):
    """PFCP and GTP messages say in their own name whether they are a request
    or the reply to one. NGAP and F1AP say it in a header field instead."""
    lowered = (name or "").lower()
    if lowered.endswith("response"):
        return "success"
    if lowered.endswith("request"):
        return "request"
    return "indication"


def family_of(name):
    """"Echo request" and "Echo response" belong to the same exchange."""
    lowered = (name or "").lower()
    if lowered.endswith(("request", "response")):
        return lowered.rsplit(" ", 1)[0]
    return lowered


def peer_key(event):
    return "|".join(sorted([event["src"], event["dst"]]))


def subject_of(event):
    """A stable identifier for whose conversation this is, and a label for it.

    A phone is identified by whichever side's reference number is present.
    Downlink-only messages sometimes carry just the core network's number, so
    both are kept and either can match.
    """
    ids = event.get("subject_ids") or {}
    if event["protocol"] == "ngap":
        ran, amf = ids.get("ran", ""), ids.get("amf", "")
        if ran or amf:
            return f"ngap-ue-{ran or amf}", f"phone (reference {ran or amf})"
    elif event["protocol"] == "f1ap":
        du, cu = ids.get("du", ""), ids.get("cu", "")
        if du or cu:
            return f"f1ap-ue-{du or cu}", f"phone (reference {du or cu})"
    elif event["protocol"] == "pfcp":
        seid = event.get("seid") or ""
        # a request that is setting a session up carries an all-zero id: it
        # does not identify anyone yet, so do not pretend it does
        if seid and int(seid, 16) != 0:
            return f"pfcp-session-{seid}", f"subscriber connection {seid}"
    return None, None


def new_flow(event, protocols):
    name, plain = knowledge.describe(protocols, event["protocol"], event["code"])
    entry = knowledge.lookup(protocols, event["protocol"], event["code"])
    subject_id, subject_label = subject_of(event)
    return {
        "protocol": event["protocol"],
        "code": event["code"],
        "name": name,
        "plain": plain,
        "reply": entry.get("reply"),
        "subject": subject_label,
        "subject_id": subject_id,
        "from": event["src"],
        "to": event["dst"],
        "start": event["time"],
        "end": event["time"],
        "packets": 0,
        "bytes": 0,
        "frames": [],
        "outcome": "no reply",
        "cause": None,
        "events": [],
    }


def add_event(flow, event, kind):
    flow["end"] = max(flow["end"], event["time"])
    flow["packets"] += 1
    flow["bytes"] += event["bytes"]
    flow["frames"].append(event["frame"])
    flow["events"].append({
        "frame": event["frame"],
        "time": event["time"],
        "from": event["src"],
        "to": event["dst"],
        "kind": kind,
    })


def finalize(flow):
    """Decide what an unanswered request means, once we know none is coming.

    Some messages never get an answer by design; for those, silence is normal.
    Where knowledge/ does not say, we say we do not know rather than calling it
    a failure.
    """
    if flow["outcome"] != "no reply":
        return
    if flow["reply"] == "none":
        flow["outcome"] = "one-way"
    elif flow["reply"] != "expected":
        flow["outcome"] = "no reply, and we do not know if one was due"


def sessionize(events, protocols):
    flows = []
    open_flows = {}  # correlation key -> index into flows

    for event in sorted(events, key=lambda e: (e["time"], e["frame"])):
        proto = event["protocol"]
        if proto == "sctp":
            continue  # summarised as a link, not as an exchange
        entry = knowledge.lookup(protocols, proto, event["code"])
        if entry.get("carries_traffic"):
            continue  # subscriber traffic is counted per tunnel, not per packet

        subject_id, _ = subject_of(event)
        if proto == "pfcp":
            event["kind"] = kind_from_name(entry.get("name"))
            # the sequence number pairs a PFCP request with its own answer
            key = (proto, event.get("seq"), peer_key(event))
        elif proto == "gtp":
            event["kind"] = kind_from_name(entry.get("name"))
            key = (proto, family_of(entry.get("name")), peer_key(event))
        else:
            key = (proto, event["code"], subject_id or peer_key(event))
        kind = event["kind"]

        if kind in ("success", "failure") and key in open_flows:
            flow = flows[open_flows.pop(key)]
            add_event(flow, event, kind)
            cause = event.get("cause")
            if cause is not None:
                flow["cause"] = cause
                flow["outcome"] = "failed" if cause >= PFCP_REJECT_FROM else "completed"
            else:
                flow["outcome"] = "failed" if kind == "failure" else "completed"
            continue

        flow = new_flow(event, protocols)
        if proto in ("pfcp", "gtp") and kind == "request":
            # these protocols name their replies, so an unanswered request is
            # unambiguous without needing a hand-written `reply:` field
            flow["reply"] = "expected"
        add_event(flow, event, kind)
        flows.append(flow)

        if kind in ("success", "failure"):
            # an answer with no question: the request is outside the capture
            flow["outcome"] = "reply seen, but the request was not captured"
        elif kind == "indication":
            flow["outcome"] = "one-way"
        else:
            if key in open_flows:
                # the previous request on this key was never answered
                finalize(flows[open_flows[key]])
            open_flows[key] = len(flows) - 1

    for index in open_flows.values():
        finalize(flows[index])
    return flows


def aggregate_tunnels(events, protocols):
    """One entry per tunnel and direction, not one per data packet."""
    buckets = defaultdict(lambda: {"packets": 0, "bytes": 0, "frames": [],
                                   "start": None, "end": None, "codes": set()})
    for event in events:
        if event["protocol"] != "gtp":
            continue
        if not knowledge.lookup(protocols, "gtp", event["code"]).get("carries_traffic"):
            continue
        key = (event.get("teid", ""), event["src"], event["dst"])
        bucket = buckets[key]
        bucket["packets"] += 1
        bucket["bytes"] += event["bytes"]
        bucket["codes"].add(event["code"])
        if len(bucket["frames"]) < 5:
            bucket["frames"].append(event["frame"])
        bucket["start"] = event["time"] if bucket["start"] is None else min(bucket["start"], event["time"])
        bucket["end"] = event["time"] if bucket["end"] is None else max(bucket["end"], event["time"])

    tunnels = []
    for (teid, src, dst), bucket in buckets.items():
        kinds = []
        for code in sorted(bucket["codes"]):
            name, plain = knowledge.describe(protocols, "gtp", code)
            kinds.append({"code": code, "name": name, "plain": plain})
        tunnels.append({
            "teid": teid, "from": src, "to": dst,
            "packets": bucket["packets"], "bytes": bucket["bytes"],
            "start": bucket["start"], "end": bucket["end"],
            "frames": bucket["frames"], "kinds": kinds,
        })
    return sorted(tunnels, key=lambda t: -t["packets"])


def aggregate_transport(events, protocols):
    """Did the control connections stay up? Counts per pair of addresses."""
    buckets = defaultdict(lambda: defaultdict(int))
    for event in events:
        if event["protocol"] != "sctp":
            continue
        buckets[peer_key(event)][event["code"]] += 1

    links = []
    for pair, codes in buckets.items():
        left, right = pair.split("|")
        chunks = []
        for code, count in sorted(codes.items()):
            name, plain = knowledge.describe(protocols, "sctp", code)
            chunks.append({"code": code, "name": name, "plain": plain, "count": count})
        links.append({"between": [left, right], "chunks": chunks})
    return links


def find_gaps(events, protocols):
    """Every message type seen that knowledge/ cannot explain."""
    gaps = {}
    for event in events:
        entry = knowledge.lookup(protocols, event["protocol"], event["code"])
        if entry.get("plain"):
            continue
        key = (event["protocol"], event["code"])
        gap = gaps.setdefault(key, {
            "protocol": event["protocol"],
            "code": event["code"],
            "name": entry.get("name"),
            "count": 0,
            "frames": [],
        })
        gap["count"] += 1
        if len(gap["frames"]) < 5:
            gap["frames"].append(event["frame"])
    return sorted(gaps.values(), key=lambda g: -g["count"])


def summarise_nodes(events):
    stats = defaultdict(lambda: {"sent": 0, "received": 0, "bytes": 0})
    for event in events:
        if event["src"]:
            stats[event["src"]]["sent"] += 1
            stats[event["src"]]["bytes"] += event["bytes"]
        if event["dst"]:
            stats[event["dst"]]["received"] += 1
    nodes = [{"ip": ip, **values} for ip, values in stats.items()]
    return sorted(nodes, key=lambda n: -(n["sent"] + n["received"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events")
    parser.add_argument("out")
    args = parser.parse_args()

    path = Path(args.events)
    if not path.exists():
        sys.exit(f"events file not found: {path}. Run scripts/1_extract.py first.")

    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    events = [event for event in (classify(row) for row in rows) if event]
    if not events:
        sys.exit(f"{path} has no signalling packets to group.")

    protocols = knowledge.load_protocols()
    flows = sessionize(events, protocols)
    times = [event["time"] for event in events]

    result = {
        "source": str(path),
        "packets": len(events),
        "span": {
            "start": min(times),
            "end": max(times),
            "seconds": round(max(times) - min(times), 3),
        },
        "nodes": summarise_nodes(events),
        "flows": sorted(flows, key=lambda f: (f["start"], f["frames"][0])),
        "tunnels": aggregate_tunnels(events, protocols),
        "links": aggregate_transport(events, protocols),
        "gaps": find_gaps(events, protocols),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{len(events)} packets -> {len(result['flows'])} procedures, "
          f"{len(result['tunnels'])} tunnels, {len(result['gaps'])} unexplained "
          f"message types -> {out}")


if __name__ == "__main__":
    main()
