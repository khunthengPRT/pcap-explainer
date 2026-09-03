---
name: pcap-analyze
description: Turn a network capture (.pcap/.pcapng) into a one-page report anyone can read. Use when the user points at a capture file and wants to know what happened, what went wrong, or wants documentation of a network trace.
---

# Analyse a capture

Run the pipeline. Do not read packets and describe them from memory - every
number in the report has to come out of a script.

## Steps

1. **Survey.** `bash scripts/survey.sh <pcap>`

   It exits non-zero if any address is missing from the active lab profile.
   That is not a failure to work around: add the addresses, pointing each at
   equipment in `knowledge/topology.yaml`, and ask the user if you cannot tell
   what a piece of equipment is. A report full of bare IP addresses is a bad
   report.

   If the user works with more than one lab, ask which lab this capture is
   from and pass `bash scripts/survey.sh <pcap> --nodes <profile>`, or set
   `$PCAP_LAB`. Do not infer it from the addresses: labs reuse ranges, and
   the wrong profile produces a report that names the wrong equipment without
   anything looking amiss.

   Put names and descriptions in `knowledge/topology.yaml` (shared, committed)
   and addresses in the lab profile (local, never committed). Never write a
   real lab's addresses into a tracked file.

2. **Extract.** `python scripts/1_extract.py <pcap> out/events.csv`

   If nothing matches, widen the filter with `--filter` rather than guessing
   what the capture holds - the survey output tells you which protocols are
   in there.

3. **Sessionize.** `python scripts/2_sessionize.py out/events.csv out/flows.json`

4. **Render.** `python scripts/3_render.py out/flows.json out/report.md --title "<network>"`

   Anything it prints to stderr is a real problem:
   - `jargon:` means a word the reader will not understand reached the page.
     Rewrite that sentence, or add the word to `knowledge/glossary.yaml` with
     a plain meaning if it genuinely belongs there.
   - `queued in knowledge/_unknown.yaml` means the capture contained message
     types we cannot explain.

5. **Read `out/report.md`.** Check it reads plainly and that the "What it
   means" section actually says something. Tighten the wording. Do not add
   facts that are not in `out/flows.json`.

6. **Report the gaps.** If `knowledge/_unknown.yaml` is non-empty, tell the
   user how many gaps there are and offer to run the `pcap-learn` skill.

7. **If the report is going anywhere.** The address column is the one place a
   report carries a lab's numbering. If the user mentions sending it on, offer
   `--redact-addresses`, which prints the names without the numbers.

## Rules

- A message type with no `plain` text in `knowledge/protocols/` is
  `[unrecognised]`. Never describe it from your own knowledge of the spec -
  that is exactly the guess this project exists to avoid.
- If you need to change what a procedure means, edit `knowledge/`, not the
  report. The next capture should benefit from the fix.
- Run `bash tests/run_tests.sh` after touching anything in `scripts/` or
  `knowledge/`.
