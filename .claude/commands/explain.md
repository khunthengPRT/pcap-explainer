---
description: Turn a capture file into a one-page report anyone can read
argument-hint: <file.pcap> [network name]
---

Analyse the capture at `$1` using the `pcap-analyze` skill, and call the
network "$2" in the report title (if that is empty, ask what to call it).

Work through every stage of the pipeline in order, fix anything the scripts
warn about, and show me the finished `out/report.md`. Tell me plainly whether
anything in the capture failed, and list any message types the knowledge base
could not explain.
