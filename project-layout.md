# Project layout

```
pcap-explainer/
├── CLAUDE.md                       # always loaded: the rules
├── README.md                       # what this is, and how to run it
├── pipeline.md                     # what each stage does
├── .claude/
│   ├── skills/
│   │   ├── pcap-analyze/SKILL.md   # run the pipeline end to end
│   │   ├── pcap-narrate/SKILL.md   # rewrite a report for a manager
│   │   └── pcap-learn/SKILL.md     # fill the unknown queue
│   └── commands/
│       └── explain.md              # /explain <file.pcap>
├── knowledge/
│   ├── topology.yaml               # the equipment: "Traffic forwarder", ...
│   ├── addresses.example.yaml      # the lab profile to copy: address -> equipment
│   ├── nodes.yaml                  # the older flat form; now the test fixture
│   ├── protocols/
│   │   ├── ngap.yaml               # radio site <-> core network
│   │   ├── f1ap.yaml               # the two halves of a base station
│   │   ├── pfcp.yaml               # core -> traffic forwarder (+ causes)
│   │   ├── gtp.yaml                # the tunnels carrying subscriber data
│   │   └── sctp.yaml               # did the control connections stay up
│   ├── glossary.yaml               # the only jargon allowed in a report
│   └── _unknown.yaml               # the learning queue
├── scripts/
│   ├── survey.sh                   # stage 0: what is in this capture
│   ├── 1_extract.py                # stage 1: capture -> events.csv
│   ├── 2_sessionize.py             # stage 2: events.csv -> flows.json
│   ├── 3_render.py                 # stage 3: flows.json -> report.md
│   ├── sync_codes.py               # regenerate spec names from tshark
│   └── lib/
│       ├── knowledge.py            # loading and lookup for knowledge/
│       ├── nodes.py                # picking and loading one lab's profile
│       └── check_nodes.py          # the unnamed-address check in survey.sh
├── references/
│   └── report-template.md          # the shape a report has to take
├── samples/
│   └── lab-session.pcap            # synthetic, built by tests/make_sample.py
├── tests/
│   ├── run_tests.sh                # everything that has to keep working
│   ├── make_sample.py              # builds the sample capture
│   ├── check_knowledge.py          # the knowledge base is well formed
│   ├── check_profiles.py           # lab profiles resolve, and fail loudly
│   ├── check_no_lab_data.py        # no local lab address reached a tracked file
│   ├── check_gaps.py               # gaps are actually detected
│   ├── fixtures/                   # checked-in CSV, so stages 2-3 test
│   │   └── ngap-attach.csv         #   without needing tshark
│   └── expected/                   # golden reports
├── labs/                           # your lab profiles - gitignored
│   └── README.md                   # ...except this
└── out/                            # generated, gitignored
```

## Two halves

`scripts/` never decides what a message means. `knowledge/` never decides
what happened in a capture. Keeping those apart is what lets the report be
corrected by editing a YAML file instead of a program.

## Who-is-who, also two halves

The same split again, for a different reason. `knowledge/topology.yaml` says
what the equipment is called; a lab profile says which address it is on. Every
lab runs the same equipment, so the descriptions are worth sharing and the
numbering is not ours to publish. Writing a description once benefits every
lab, and the confidential half stays a bare list of addresses with no prose
attached to leak.
