# What happened on the lab radio site

This covers 3.5 seconds of traffic recorded on 01 January 2026 at 00:00 UTC, between 4 pieces of equipment. It contains 10 exchanges and 14 messages in total. 2 of those exchanges did not succeed; they are set out below.

## Who was involved

| Who | Address | What it does | Messages |
|-----|---------|--------------|----------|
| Base station brain (site A) | 10.10.1.10 | Central unit of the split base station at site A | 13 |
| Core network access manager | 10.10.2.20 | Handles phones joining the network and staying reachable | 11 |
| Base station antenna side (site A) | 10.10.1.11 | Distributed unit of the split base station at site A | 3 |
| 10.10.9.9 (not yet named) | 10.10.9.9 |  | 1 |

## What happened, in order

| When | What | Between | Result |
|------|------|---------|--------|
| +0.000s | The antenna side introduced itself to the base station's brain and asked to join it. | Base station antenna side (site A) to Base station brain (site A) | Accepted |
| +0.100s | A radio site introduced itself to the core network and asked to be allowed to serve traffic. | Base station brain (site A) to Core network access manager | Accepted |
| +1.000s | A phone made first contact with the antenna side, which passed it to the brain. | Base station antenna side (site A) to Base station brain (site A) | No answer expected |
| +1.010s | A phone appeared at a radio site, and the site passed its first message to the core network. | Base station brain (site A) to Core network access manager | No answer expected |
| +1.200s | The core network sent a message to a phone, relayed by the radio site. | Core network access manager to Base station brain (site A) | No answer expected |
| +1.260s | A phone sent a message to the core network, relayed by the radio site. | Base station brain (site A) to Core network access manager | No answer expected |
| +1.400s | The core network gave the radio site everything it needs to serve this phone, including its security settings. | Core network access manager to Base station brain (site A) | Accepted |
| +2.000s | The core network asked the radio site to set aside radio and transport capacity so a phone can carry data. | Core network access manager to Base station brain (site A) | Refused |
| +3.000s | The core network told the radio site to forget about a phone and free its resources. | Core network access manager to Base station brain (site A) | No answer |
| +3.500s | [unrecognised] A message this report has no plain description for yet; it is named in the reference below. | 10.10.9.9 to Core network access manager | No answer seen |

## What went wrong

- **Refused.** The core network asked the radio site to set aside radio and transport capacity so a phone can carry data - and it was turned down. This concerned phone (reference 1). (Core network access manager asked Base station brain (site A), at +2.000s.)
- **No answer.** The core network told the radio site to forget about a phone and free its resources - and nothing came back, though an answer was due. This concerned phone (reference 1). (Core network access manager asked Base station brain (site A), at +3.000s.)

## What it means

What failed affected phone (reference 1). Anyone using that would have seen the service fail to start, or drop.

1 address in this capture is not yet named in the knowledge base, so it appears as a bare number above. Add it to knowledge/nodes.yaml.

## What this report could not explain

- [unrecognised] NGAP id-UEContextResume, seen 1 time (frames 14).

## Reference

| Frames | Protocol | Message | Outcome |
|--------|----------|---------|---------|
| 1, 2 | F1AP | id-F1Setup | completed |
| 3, 4 | NGAP | id-NGSetup | completed |
| 5 | F1AP | id-InitialULRRCMessageTransfer | one-way |
| 6 | NGAP | id-InitialUEMessage | one-way |
| 7 | NGAP | id-DownlinkNASTransport | one-way |
| 8 | NGAP | id-UplinkNASTransport | one-way |
| 9, 10 | NGAP | id-InitialContextSetup | completed |
| 11, 12 | NGAP | id-PDUSessionResourceSetup | failed |
| 13 | NGAP | id-UEContextRelease | no reply |
| 14 | NGAP | id-UEContextResume | no reply, and we do not know if one was due |
