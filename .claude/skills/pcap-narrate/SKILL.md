---
name: pcap-narrate
description: Rewrite an analysed capture for a non-technical audience - a manager, a customer, an incident review. Use after pcap-analyze when the report needs to be readable by someone who does not work on networks.
---

# Write it for someone who was not there

Input is `out/flows.json` (the facts) and `out/report.md` (the scaffold).
Output is the same report, written like a person wrote it.

## What to change

- **Lead with the answer.** The first sentence says whether anything is
  wrong. "Two subscriber connections failed to start because the traffic
  forwarder had no capacity left" beats "This covers 5.0 seconds of traffic".
- **Merge repetition.** Six identical rows in the timeline become one line
  saying it happened six times.
- **Give consequences, not mechanisms.** The reader wants to know who could
  not use their phone, and for how long.
- **Keep the tables.** They are the evidence. Do not rewrite the numbers.

## What not to change

- Any number. If a number looks wrong, the pipeline is wrong - fix
  `scripts/`, re-run, and check the tests still pass.
- The `[unrecognised]` markers. They are honest, and hiding them makes the
  report a guess.
- The Reference section. It is deliberately technical, for whoever opens the
  capture next.

## Check before you finish

Read `knowledge/glossary.yaml`. Every technical word left on the page should
be in `terms`, and nothing in `banned` should appear at all outside the
Reference section. Re-running `scripts/3_render.py` will tell you, but it
checks the generated text, not your rewrite - so read it yourself.
