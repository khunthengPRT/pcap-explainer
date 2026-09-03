# PCAP Analyze

Turn a capture into documentation. Never read raw packets into context.

## Rules

- Run the scripts. Do not eyeball packets and describe them from memory.
- Every number in the output must come from a script, not from you.
- If a message type is not in `knowledge/`, do NOT guess its meaning.
  `scripts/3_render.py` appends it to `knowledge/_unknown.yaml` and marks it
  `[unrecognised]` in the output. Leave it that way until someone confirms
  what it means.
- Fix meaning in `knowledge/`, never in the report. The next capture should
  benefit.
- Run `bash tests/run_tests.sh` after changing anything in `scripts/` or
  `knowledge/`.
- Never commit a lab's addressing. Names and descriptions go in
  `knowledge/topology.yaml`, which is shared; addresses go in a lab profile
  under `labs/` or `~/.config/pcap-explainer/labs/`, which is not. Anything
  you write into a tracked file — a test fixture, a sample, an example — uses
  made-up numbering.

## Steps

1. Survey: `bash scripts/survey.sh <pcap>` — it exits non-zero if any address
   is missing from the active lab profile. Add them, asking the user when you
   cannot tell what a piece of equipment is. If the user has more than one lab,
   ask which one this capture is from and pass `--nodes` or set `$PCAP_LAB`;
   never infer it from the addresses.
2. Extract: `python scripts/1_extract.py <pcap> out/events.csv`
3. Sessionize: `python scripts/2_sessionize.py out/events.csv out/flows.json`
4. Render: `python scripts/3_render.py out/flows.json out/report.md --title "<network>"`
5. Read `out/report.md` and check the narrative reads plainly. Rewrite any
   sentence containing jargon not in `knowledge/glossary.yaml`; the renderer
   warns on stderr about the ones it can spot itself.
6. If `knowledge/_unknown.yaml` is non-empty, tell the user how many gaps
   there are and offer to run the `pcap-learn` skill.

## Output shape

See `references/report-template.md`. One page: what happened, who was
involved, the timeline, what went wrong, what it means.

## Who is who

Split in two, because every lab runs the same equipment on different numbering:

- `knowledge/topology.yaml` — the equipment and its plain-English names.
  Committed and shared. Fix a description here and every lab benefits.
- a lab profile — address → equipment id, nothing else. Local, never
  committed.

One profile is loaded per run, chosen on purpose (`--nodes`, `$PCAP_NODES`,
`$PCAP_LAB`). Loading the wrong one is not a visible error — the report simply
names the wrong equipment — which is why a `$PCAP_LAB` that matches no profile
stops the run instead of falling back.

For a report leaving the user's machine, offer
`3_render.py --redact-addresses`.

## The knowledge base

`knowledge/protocols/*.yaml` has two halves. The `name` of each numeric code
is generated from the Wireshark dissector by `scripts/sync_codes.py` — never
edit those by hand, and never trust your own memory of a code table over
what that script produces. The `plain`, `reply` and `carries_traffic` fields
are hand-written and survive a sync.
