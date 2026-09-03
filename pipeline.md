# The pipeline

Four stages. Each one writes a file the next one reads, so you can stop after
any of them and look at what it produced.

## Stage 0 - who is in here?

```bash
bash scripts/survey.sh capture.pcap
```

Wraps `capinfos` and `tshark -z conv,ip -z io,phs`, then checks every address
against `knowledge/nodes.yaml` and exits non-zero if any is unnamed.

## Stage 1 - extract

```bash
python scripts/1_extract.py capture.pcap out/events.csv
```

The only stage that reads the capture. One row per signalling packet, with
the fields that matter for correlation - procedure codes, phone reference
numbers, session ids, tunnel ids - pulled out into columns.

Everything downstream works from this CSV, which is why no raw packet ever
has to be read by a person or a model.

## Stage 2 - sessionize

```bash
python scripts/2_sessionize.py out/events.csv out/flows.json
```

Groups packets into the things that actually happened:

- **Exchanges** - a request matched to the answer it got. NGAP and F1AP say
  which is which in a header field; PFCP and GTP say it in the message name.
  A request with no answer is only called a failure when `knowledge/` says an
  answer was due.
- **Tunnels** - subscriber traffic counted per tunnel, not per packet, so a
  million-packet capture still produces a readable page.
- **Links** - whether the underlying connections stayed up.
- **Gaps** - every message type seen that `knowledge/` cannot explain.

## Stage 3 - render

```bash
python scripts/3_render.py out/flows.json out/report.md --title "the lab core network"
```

Writes the report described in `references/report-template.md`. Every
sentence about a message is copied from `knowledge/`; gaps are marked
`[unrecognised]` and queued in `knowledge/_unknown.yaml`.

Warnings on stderr are real problems:

```
jargon: banned word 'upf' reached the report - rewrite that sentence.
jargon: acronym 'NGAP' is not in knowledge/glossary.yaml.
3 new message type(s) queued in knowledge/_unknown.yaml.
```

## Keeping the knowledge base honest

```bash
python scripts/sync_codes.py          # regenerate spec names from the dissector
python scripts/sync_codes.py --check  # fail if they are stale
```

The numeric code tables are generated from `tshark -G values`. Hand-written
`plain`, `reply` and `carries_traffic` fields are preserved across a sync.
