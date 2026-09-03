#!/usr/bin/env python3
"""Stage 3: out/flows.json -> out/report.md.

Turns grouped exchanges into a page someone outside the network team can
read. Every sentence about a message is copied from knowledge/; anything the
knowledge base cannot explain is marked [unrecognised] and queued for
learning rather than guessed at.

Usage: python scripts/3_render.py <out/flows.json> <out/report.md>
                                  [--title "..."] [--no-learn]
                                  [--nodes PATH] [--redact-addresses]
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import knowledge  # noqa: E402
from lib import nodes as node_lib  # noqa: E402

UNRECOGNISED = "[unrecognised]"

# Sections that exist to be read by engineers. Everything above them must be
# free of jargon; inside them, spec names are the whole point.
TECHNICAL_SECTIONS = ("## What this report could not explain", "## Reference")

RESULT_TEXT = {
    "completed": "Accepted",
    "failed": "Refused",
    "one-way": "No answer expected",
    "no reply": "No answer",
    "no reply, and we do not know if one was due": "No answer seen",
    "reply seen, but the request was not captured": "Answer only",
}

ROLE_TEXT = {
    "radio": "Talks to phones over the air",
    "core": "Decides who may connect and where their traffic goes",
    "forwarder": "Carries subscriber traffic",
    "subscriber": "A device using the network",
    "other": "",
}


def plural(count, singular, suffix="s"):
    return f"{count} {singular}{'' if count == 1 else suffix}"


def human_bytes(count):
    for unit in ("bytes", "kB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "bytes" else f"{count:.1f} {unit}"
        count /= 1024.0


def offset(time, start):
    return f"+{time - start:.3f}s"


def describe_flow(flow):
    """The one sentence the report is allowed to say about a flow."""
    if flow.get("plain"):
        return flow["plain"]
    # no entry in knowledge/ means no words for it - say so rather than guess
    return (f"{UNRECOGNISED} A message this report has no plain description "
            f"for yet; it is named in the reference below.")


def between(nodes, flow):
    return (f"{knowledge.node_name(nodes, flow['from'])} to "
            f"{knowledge.node_name(nodes, flow['to'])}")


def link_lines(data, nodes):
    """What happened to the connections carrying the control conversations."""
    lines = []
    for link in data["links"]:
        left, right = link["between"]
        names = f"{knowledge.node_name(nodes, left)} and {knowledge.node_name(nodes, right)}"
        described = [chunk for chunk in link["chunks"] if chunk.get("plain")]
        if not described:
            continue
        events = "; ".join(
            f"{chunk['plain'].rstrip('.')} ({plural(chunk['count'], 'time')})"
            for chunk in described
        )
        lines.append(f"- Between {names}: {events}.")
    return lines


def summary(data, nodes, failures):
    start = datetime.fromtimestamp(data["span"]["start"], timezone.utc)
    lines = [
        f"This covers {data['span']['seconds']:.1f} seconds of traffic recorded on "
        f"{start.strftime('%d %B %Y at %H:%M UTC')}, "
        f"between {len(data['nodes'])} pieces of equipment.",
        f"It contains {plural(len(data['flows']), 'exchange')} and "
        f"{plural(data['packets'], 'message')} in total.",
    ]
    if failures:
        lines.append(
            f"{len(failures)} of those exchanges did not succeed; "
            f"they are set out below."
        )
    else:
        lines.append("Every exchange that expected an answer got one.")
    if data.get("tunnels"):
        carried = sum(tunnel["bytes"] for tunnel in data["tunnels"])
        lines.append(
            f"Alongside the signalling, {plural(len(data['tunnels']), 'traffic tunnel')} "
            f"carried {human_bytes(carried)} of subscriber data."
        )
    return " ".join(lines)


def who_table(data, nodes, redact=False):
    """Who appeared in the capture. The address column is the one place a
    report carries a lab's numbering, so it can be left out for a report that
    is going somewhere else."""
    header = "| Who | What it does | Messages |" if redact else \
             "| Who | Address | What it does | Messages |"
    rule = "|-----|--------------|----------|" if redact else \
           "|-----|---------|--------------|----------|"
    rows = [header, rule]
    unnamed = []
    for node in data["nodes"]:
        ip = node["ip"]
        entry = nodes.get(ip) or {}
        if not entry:
            unnamed.append(ip)
        name = entry.get("name") or (nodes.name(ip) if redact
                                     else f"{ip} (not yet named)")
        role = entry.get("note") or ROLE_TEXT.get(entry.get("role"), "")
        total = node["sent"] + node["received"]
        if redact:
            rows.append(f"| {name} | {role} | {total} |")
        else:
            rows.append(f"| {name} | {ip} | {role} | {total} |")
    return "\n".join(rows), unnamed


def timeline_table(data, nodes):
    start = data["span"]["start"]
    rows = ["| When | What | Between | Result |",
            "|------|------|---------|--------|"]
    for flow in data["flows"]:
        result = RESULT_TEXT.get(flow["outcome"], flow["outcome"])
        if flow.get("cause") is not None and flow["outcome"] == "failed":
            result = "Refused"
        rows.append(
            f"| {offset(flow['start'], start)} | {describe_flow(flow)} | "
            f"{between(nodes, flow)} | {result} |"
        )
    return "\n".join(rows)


def tunnel_table(data, nodes):
    rows = ["| Tunnel | Direction | Packets | Carried |",
            "|--------|-----------|---------|---------|"]
    for tunnel in data["tunnels"]:
        rows.append(
            f"| {tunnel['teid'] or 'unknown'} | "
            f"{knowledge.node_name(nodes, tunnel['from'])} to "
            f"{knowledge.node_name(nodes, tunnel['to'])} | "
            f"{tunnel['packets']} | {human_bytes(tunnel['bytes'])} |"
        )
    return "\n".join(rows)


def failure_lines(data, nodes, protocols):
    lines = []
    for flow in data["flows"]:
        if flow["outcome"] not in ("failed", "no reply"):
            continue
        who = f"{knowledge.node_name(nodes, flow['from'])} asked " \
              f"{knowledge.node_name(nodes, flow['to'])}"
        what = describe_flow(flow).rstrip(".")
        if flow["outcome"] == "failed":
            reason = ""
            if flow.get("cause") is not None:
                _, plain = knowledge.describe(protocols, flow["protocol"],
                                              flow["cause"], block="causes")
                reason = f" Reason given: {plain}" if plain else \
                         f" Reason given: {UNRECOGNISED} code {flow['cause']}."
            subject = f" This concerned {flow['subject']}." if flow.get("subject") else ""
            lines.append(f"- **Refused.** {what} - and it was turned down."
                         f"{reason}{subject} ({who}, at "
                         f"{offset(flow['start'], data['span']['start'])}.)")
        else:
            subject = f" This concerned {flow['subject']}." if flow.get("subject") else ""
            lines.append(f"- **No answer.** {what} - and nothing came back, "
                         f"though an answer was due.{subject} ({who}, at "
                         f"{offset(flow['start'], data['span']['start'])}.)")
    return lines


def meaning_lines(data, failures, unnamed, profile=None):
    lines = []
    if failures:
        subjects = {flow["subject"] for flow in data["flows"]
                    if flow["outcome"] in ("failed", "no reply") and flow.get("subject")}
        untied = len(failures) - sum(
            1 for flow in data["flows"]
            if flow["outcome"] in ("failed", "no reply") and flow.get("subject")
        )
        if subjects:
            named = ", ".join(sorted(subjects))
            lines.append(
                f"What failed affected {named}. Anyone using "
                f"{'those' if len(subjects) > 1 else 'that'} would have seen the "
                "service fail to start, or drop."
            )
        if untied:
            lines.append(
                f"{untied} of the failures cannot be traced to one subscriber from "
                "this capture alone. They are between the equipment itself, so they "
                "affect everyone that equipment serves."
            )
    else:
        lines.append(
            "Nothing in this capture failed. It confirms the equipment involved was "
            "reachable and answering within the window recorded."
        )
    if data.get("links"):
        aborted = [link for link in data["links"]
                   if any(chunk["name"] in ("ABORT", "SHUTDOWN") for chunk in link["chunks"])]
        if aborted:
            lines.append(
                f"{len(aborted)} of the underlying connections were torn down during "
                "the capture, which is worth checking against the timeline above."
            )
    if unnamed:
        where = profile or "the lab node profile"
        one = len(unnamed) == 1
        lines.append(
            f"{plural(len(unnamed), 'address', 'es')} in this capture "
            f"{'is' if one else 'are'} not yet named in the knowledge base, so "
            f"{'it appears' if one else 'they appear'} as a bare number above. "
            f"Add {'it' if one else 'them'} to {where}."
        )
    return lines


def reference_table(data):
    rows = ["| Frames | Protocol | Message | Outcome |",
            "|--------|----------|---------|---------|"]
    for flow in data["flows"]:
        frames = ", ".join(str(frame) for frame in flow["frames"][:6])
        if len(flow["frames"]) > 6:
            frames += ", ..."
        message = flow["name"] or f"code {flow['code']}"
        rows.append(f"| {frames} | {flow['protocol'].upper()} | {message} | "
                    f"{flow['outcome']} |")
    return "\n".join(rows)


def check_jargon(text, terms, banned):
    """Flag anything the reader would not understand. Warnings only - the fix
    is to rewrite the sentence, which is a person's job, not a script's."""
    prose = text
    for heading in TECHNICAL_SECTIONS:
        prose = prose.split(heading)[0]
    found = sorted({word for word in banned
                    if re.search(rf"\b{re.escape(word)}\b", prose.lower())})
    allowed = {term.lower() for term in terms}
    acronyms = sorted({
        token for token in re.findall(r"\b[A-Z]{2,}\b", prose)
        if token.lower() not in allowed and token not in ("UTC",)
    })
    return found, acronyms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flows")
    parser.add_argument("out")
    parser.add_argument("--title", default="the captured network")
    parser.add_argument("--no-learn", action="store_true",
                        help="do not append gaps to knowledge/_unknown.yaml")
    parser.add_argument("--redact-addresses", action="store_true",
                        help="leave IP addresses out of the report, for a copy "
                             "that is leaving this machine")
    node_lib.add_argument(parser)
    args = parser.parse_args()

    path = Path(args.flows)
    if not path.exists():
        sys.exit(f"flows file not found: {path}. Run scripts/2_sessionize.py first.")
    data = json.loads(path.read_text())

    try:
        nodes = knowledge.load_nodes(args.nodes)
    except node_lib.ProfileError as error:
        sys.exit(f"node profile: {error}")
    # stderr, not the report: which lab this was is not the reader's business,
    # and a report is the thing most likely to be forwarded on
    print(f"naming equipment from {nodes.origin}", file=sys.stderr)
    if args.redact_addresses:
        nodes = nodes.redacted()
    terms, banned = knowledge.load_glossary()
    protocols = knowledge.load_protocols()

    failures = [flow for flow in data["flows"]
                if flow["outcome"] in ("failed", "no reply")]
    who, unnamed = who_table(data, nodes, args.redact_addresses)

    parts = [
        f"# What happened on {args.title}",
        "",
        summary(data, nodes, failures),
        "",
        "## Who was involved",
        "",
        who,
        "",
        "## What happened, in order",
        "",
        timeline_table(data, nodes),
        "",
    ]
    if data.get("tunnels"):
        parts += ["## Traffic carried", "", tunnel_table(data, nodes), ""]
    links = link_lines(data, nodes)
    if links:
        parts += ["## Connections between equipment", ""] + links + [""]
    parts += ["## What went wrong", ""]
    parts += failure_lines(data, nodes, protocols) or \
        ["Nothing in this capture failed."]
    parts += ["", "## What it means", ""]
    # blank lines between them so each reads as its own paragraph
    for index, line in enumerate(meaning_lines(data, failures, unnamed, nodes.where)):
        if index:
            parts.append("")
        parts.append(line)

    if data.get("gaps"):
        parts += ["", "## What this report could not explain", ""]
        for gap in data["gaps"]:
            name = gap["name"] or f"code {gap['code']}"
            parts.append(
                f"- {UNRECOGNISED} {gap['protocol'].upper()} {name}, seen "
                f"{plural(gap['count'], 'time')} (frames "
                f"{', '.join(str(f) for f in gap['frames'])})."
            )

    parts += ["", "## Reference", "", reference_table(data), ""]
    report = "\n".join(parts)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(f"{len(data['flows'])} exchanges -> {out}")

    if data.get("gaps") and not args.no_learn:
        added = knowledge.record_unknown([
            {"protocol": gap["protocol"], "code": gap["code"],
             "name": gap["name"], "seen_in": data["source"],
             "frames": gap["frames"], "plain": None}
            for gap in data["gaps"]
        ])
        if added:
            print(f"{added} new message type(s) queued in knowledge/_unknown.yaml. "
                  f"Run the pcap-learn skill to describe them.", file=sys.stderr)

    found, acronyms = check_jargon(report, terms, banned)
    for word in found:
        print(f"jargon: banned word {word!r} reached the report - rewrite that "
              f"sentence.", file=sys.stderr)
    for word in acronyms:
        print(f"jargon: acronym {word!r} is not in knowledge/glossary.yaml.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
