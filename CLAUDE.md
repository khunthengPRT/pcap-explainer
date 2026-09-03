---
name: pcap-analyze
description: Convert a .pcap or .pcapng capture into a network diagram and a
  step-by-step call flow that non-engineers can read. Use this skill whenever
  the user mentions a pcap, a packet capture, a tshark or Wireshark trace, or
  asks to explain, document, diagram, or summarise network traffic — even if
  they don't say the word "pcap". Also use it for "what happened on the
  network", "why did the call fail", or "make this into a slide".
---

# PCAP Analyze

Turn a capture into documentation. Never read raw packets into context.

## Rules

- Run the scripts. Do not eyeball packets and describe them from memory.
- Every number in the output must come from a script, not from you.
- If a message type is not in `knowledge/`, do NOT guess its meaning.
  Append it to `knowledge/_unknown.yaml` and mark it `[unrecognised]`
  in the output.

## Steps

1. Survey: `bash scripts/survey.sh <pcap>` — confirm node list with the user
   if any IP is missing from `knowledge/nodes.yaml`.
2. Extract: `python scripts/1_extract.py <pcap> out/events.csv`
3. Sessionize: `python scripts/2_sessionize.py out/events.csv out/flows.json`
4. Render: `python scripts/3_render.py out/flows.json out/report.md`
5. Read `out/report.md` and check the narrative reads plainly. Rewrite any
   sentence containing jargon not in `knowledge/glossary.yaml`.
6. If `knowledge/_unknown.yaml` is non-empty, tell the user how many gaps
   there are and offer to run the `pcap-learn` skill.

## Output shape

See `references/report-template.md`. One page: what happened, who was
involved, the timeline, what went wrong, what it means.
