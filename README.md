# pcap-explainer

Turn a network capture into a page someone outside the network team can read.

Point it at a `.pcap` from a 5G core or radio network and it produces a
one-page report: what happened, who was involved, the timeline, what went
wrong, and what that means for people using the network.

```
$ python scripts/1_extract.py capture.pcap out/events.csv
$ python scripts/2_sessionize.py out/events.csv out/flows.json
$ python scripts/3_render.py out/flows.json out/report.md --title "the lab core network"
```

```markdown
| When    | What                                                    | Result  |
|---------|---------------------------------------------------------|---------|
| +1.000s | The core network asked the traffic forwarder to start    | Accepted|
|         | carrying one subscriber's traffic.                       |         |
| +1.500s | The core network asked the traffic forwarder to start    | Refused |
|         | carrying one subscriber's traffic.                       |         |

## What went wrong

- **Refused.** ... Reason given: The forwarder has no capacity left.
```

A full example is in [`tests/expected/`](tests/expected/).

## The idea

Two rules make this useful rather than another packet printer:

1. **Nothing is described from memory.** Every message the report explains
   has a hand-written plain-English sentence in `knowledge/`. A message type
   with no sentence comes out marked `[unrecognised]` and goes into a queue
   to be described later. The pipeline never fills a gap with a guess.

2. **The spec names come from the dissector, not from a person.** The numeric
   code tables in `knowledge/protocols/*.yaml` are generated from Wireshark's
   own tables by `scripts/sync_codes.py`. Only the plain-English half is
   written by hand.

The result is a report where every number traces back to a script, and every
sentence traces back to a file you can read and correct.

## Getting started

Needs Python 3.9+, `pyyaml`, and `tshark` (Debian/Ubuntu:
`sudo apt install tshark`; macOS: `brew install wireshark`).

```bash
bash scripts/survey.sh capture.pcap      # what is in here, and do we know who is who?
```

The survey fails if the capture contains addresses that are not named in
`knowledge/nodes.yaml`. Name them first - a report full of IP addresses is
the thing this project exists to avoid.

Then run the three stages above, or ask Claude: `/explain capture.pcap`.

## What is where

| Path | What it holds |
|------|---------------|
| `knowledge/nodes.yaml` | Which address is which piece of equipment |
| `knowledge/protocols/` | What each message type means, in plain English |
| `knowledge/glossary.yaml` | The only technical words allowed in a report |
| `knowledge/_unknown.yaml` | Message types still waiting for a description |
| `scripts/` | The pipeline: survey, extract, sessionize, render |
| `references/report-template.md` | The shape a report has to take |
| `samples/`, `tests/` | A synthetic capture and the golden reports |

Protocols covered: NGAP, F1AP, PFCP, GTP-U, and enough SCTP to tell whether
the control connections stayed up.

## Working on it

```bash
bash tests/run_tests.sh              # golden reports, knowledge base, jargon check
python scripts/sync_codes.py         # refresh spec names after a tshark upgrade
```

`samples/lab-session.pcap` is built by `tests/make_sample.py`, not recorded,
so nothing here comes from a real network.

## Known limits

- NGAP and F1AP failures are reported as refusals without the specific
  reason: the cause is a nested choice in the message, and the pipeline does
  not yet unpack it. PFCP failures do carry their reason.
- Phones are correlated by whichever reference number is present in a
  message. A capture that only ever shows one side's number will split one
  phone's activity into two.
- Only the message types with a `plain` entry are explained. The rest are
  visible in the report, but as gaps rather than sentences.
