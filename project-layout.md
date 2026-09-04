# Project layout

```
pcap-explainer/
├── CLAUDE.md                       # always loaded: the rules
├── README.md                       # what this is, and how to run it
├── pipeline.md                     # what each stage does
├── windows-setup.md                # the same, on a Windows PC
├── .gitattributes                  # LF checkout everywhere, incl. Windows
├── .claude/
│   ├── skills/
│   │   ├── pcap-analyze/SKILL.md   # run the pipeline end to end
│   │   ├── pcap-narrate/SKILL.md   # rewrite a report for a manager
│   │   └── pcap-learn/SKILL.md     # fill the unknown queue
│   └── commands/
│       └── explain.md              # /explain <file.pcap>
├── knowledge/
│   ├── nodes.yaml                  # address -> "Traffic forwarder"
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
│       ├── check_nodes.py          # the unnamed-address check in survey.sh
│       └── find_python.sh          # python3-or-python, for the shell scripts
├── references/
│   └── report-template.md          # the shape a report has to take
├── samples/
│   └── lab-session.pcap            # synthetic, built by tests/make_sample.py
├── tests/
│   ├── run_tests.sh                # everything that has to keep working
│   ├── make_sample.py              # builds the sample capture
│   ├── check_knowledge.py          # the knowledge base is well formed
│   ├── check_gaps.py               # gaps are actually detected
│   ├── fixtures/                   # checked-in CSV, so stages 2-3 test
│   │   └── ngap-attach.csv         #   without needing tshark
│   └── expected/                   # golden reports
└── out/                            # generated, gitignored
```

## Two halves

`scripts/` never decides what a message means. `knowledge/` never decides
what happened in a capture. Keeping those apart is what lets the report be
corrected by editing a YAML file instead of a program.
