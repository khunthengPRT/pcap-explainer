# Report shape

One page. A reader who has never heard of a base station should finish it
knowing what happened and whether it matters. Written by
`scripts/3_render.py`, then read and tightened by hand.

```markdown
# What happened on <network name>

<Two to four sentences. When the capture was taken, how long it covers, how
many exchanges it contains, and the single most important thing in it.>

## Who was involved

| Who | Address | What it does | Messages |
|-----|---------|--------------|----------|
| Base station antenna side (site A) | 10.10.1.11 | ... | 42 |

## What happened, in order

| When | What | Between | Result |
|------|------|---------|--------|
| +0.000s | A radio site introduced itself to the core network. | ... to ... | Accepted |

## What went wrong

<Each failure as a sentence a manager can act on, or "Nothing in this
capture failed." Never leave this section empty.>

## What it means

<The consequence, in the reader's terms: who could not do what, and for how
long. If nothing failed, say what the capture does confirm.>

## What this report could not explain

<Message types with no entry in knowledge/. Marked [unrecognised]. Omitted
entirely when there are none.>

## Reference

<Frame numbers and spec message names, for whoever opens the capture next.
The only section allowed to contain jargon.>
```

## Rules

- Every number comes from the pipeline, never from the writer.
- A message type with no `plain` text in `knowledge/` is `[unrecognised]`.
  It is never described from guesswork.
- No acronym reaches the reader outside the Reference section.
