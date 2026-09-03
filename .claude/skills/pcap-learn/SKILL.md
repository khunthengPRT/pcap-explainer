---
name: pcap-learn
description: Fill in the plain-English descriptions for message types the knowledge base cannot yet explain. Use when knowledge/_unknown.yaml has entries, or when a report came out with [unrecognised] markers.
---

# Close the gaps

`knowledge/_unknown.yaml` lists every message type a capture contained that
`knowledge/protocols/` has no words for. Work through it.

## For each entry

1. Look up what the message actually is. The `name` field holds the spec
   name from the Wireshark dissector (for example `id-UEContextResume`), and
   each protocol file names its spec at the top - `ngap.yaml` is TS 38.413,
   `f1ap.yaml` is TS 38.473, `pfcp.yaml` is TS 29.244, `gtp.yaml` is
   TS 29.281.

2. **Confirm it with the user if you are not certain.** A wrong description
   is worse than a gap: a gap is visible in the report, a wrong description
   is not. Ask rather than infer from the name alone.

3. Write the `plain` text into the right code in
   `knowledge/protocols/<protocol>.yaml`. One or two sentences, no acronyms,
   phrased as something that happened:

   > A phone appeared at a radio site, and the site passed its first message
   > to the core network.

   Not "InitialUEMessage is sent by the NG-RAN node to transfer the initial
   NAS message". That is the spec talking, not us.

4. For NGAP and F1AP, also set `reply:` - `expected` if the message is
   supposed to get an answer, `none` if it never does. Without it the report
   cannot tell a silent failure from a message that never had an answer
   coming. PFCP and GTP do not need it; their names say which is which.

5. Remove the entry from `knowledge/_unknown.yaml`.

## Then

- `python scripts/sync_codes.py --check` - your edit must not have disturbed
  the generated `name` fields.
- `bash tests/run_tests.sh` - the golden reports change if you have described
  something they contain. If the change is right, regenerate them and say so
  in the commit.
- Re-render the report that had the gap and confirm the `[unrecognised]`
  marker is gone.

## Never

Do not invent a description to empty the queue. An entry you cannot confirm
stays in the queue, and the report keeps saying so.
