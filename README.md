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

The survey fails if the capture contains addresses the active lab profile
does not name. Name them first - a report full of IP addresses is the thing
this project exists to avoid.

Then run the three stages above, or ask Claude: `/explain capture.pcap`.

## Captures from more than one lab

Labs run the same equipment on different numbering, so who-is-who is split in
two:

- `knowledge/topology.yaml` - the equipment and its plain-English names.
  Committed, shared by every lab, and contains no addresses.
- a **lab profile** - which address is which piece of equipment, and nothing
  else. Local to the machine it was written on, never committed.

```bash
mkdir -p ~/.config/pcap-explainer/labs
cp knowledge/addresses.example.yaml ~/.config/pcap-explainer/labs/node-lab-1.yaml
export PCAP_LAB=node-lab-1
bash scripts/survey.sh capture.pcap
```

A profile is a list of numbers pointing at equipment ids, so improving a
description benefits every lab at once:

```yaml
addresses:
  10.1.3.1: core.n3          # subnets work too, most specific wins
  10.1.4.1: gnb-cu.f1
  1.1.1.0/24: subscriber
```

The profile is chosen by `--nodes`, then `$PCAP_NODES`, then `$PCAP_LAB`; it
is never guessed from the capture. Two labs can reuse an address for
different equipment, so a guess here would mislabel silently - and a report
whose equipment names are wrong looks exactly like one whose names are right.
If `$PCAP_LAB` names a profile that does not exist, the run stops rather than
falling back. See [`labs/README.md`](labs/README.md).

For a report that is leaving your machine, `3_render.py --redact-addresses`
prints the names without the numbering.

## What is where

| Path | What it holds |
|------|---------------|
| `knowledge/topology.yaml` | The equipment and its names, shared by every lab |
| `knowledge/addresses.example.yaml` | The lab profile to copy: address -> equipment |
| `labs/` | Your lab profiles. Gitignored, except the README |
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
so nothing here comes from a real network. `tests/check_no_lab_data.py` keeps
it that way: it reads whichever lab profiles exist on your machine and fails
if any of their addresses have reached a tracked file - including inside the
checked-in capture, where an address is four bytes rather than text.

## Known limits

- NGAP and F1AP failures are reported as refusals without the specific
  reason: the cause is a nested choice in the message, and the pipeline does
  not yet unpack it. PFCP failures do carry their reason.
- Phones are correlated by whichever reference number is present in a
  message. A capture that only ever shows one side's number will split one
  phone's activity into two.
- Only the message types with a `plain` entry are explained. The rest are
  visible in the report, but as gaps rather than sentences.
