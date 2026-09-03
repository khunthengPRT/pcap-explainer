pcap-explainer/
├── CLAUDE.md                      # always loaded: project rules
├── .claude/
│   ├── skills/
│   │   ├── pcap-analyze/SKILL.md  # run the pipeline end to end
│   │   ├── pcap-narrate/SKILL.md  # flows -> management language
│   │   └── pcap-learn/SKILL.md    # fill the unknown queue
│   └── commands/
│       └── explain.md             # /explain <file.pcap>
├── knowledge/
│   ├── nodes.yaml                 # IP/MAC -> "gNB DU", "AMF", "UE-01"
│   ├── protocols/
│   │   ├── ngap.yaml
│   │   ├── f1ap.yaml
│   │   ├── pfcp.yaml
│   │   └── gtp.yaml
│   ├── glossary.yaml              # jargon -> plain English for management
│   └── _unknown.yaml              # the learning queue
├── scripts/
│   ├── 1_extract.py
│   ├── 2_sessionize.py
│   └── 3_render.py
├── samples/                       # small pcaps, committed
├── tests/expected/                # golden outputs
└── out/                           # generated, gitignored
