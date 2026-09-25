---
name: "ho-pcap-analyzer"
description: Analyze 5G NR handover (HO) events in a pcap/pcapng capture from the F1 interface (gNB-CU to DU, F1AP + NR RRC) and produce a summary plus simplified diagrams - for every HO attempt the serving cell (PCI) to target cell, the RSRP values in the triggering measurement report, whether the HO was OK or NG, and for NG whether the UE re-established with cause handoverFailure or otherFailure (or never answered). Use this whenever the user uploads or mentions a .pcap/.pcapng from a CU/DU/gNB and asks about handover, HO, mobility, cell change, ping-pong, RLF, re-establishment, "OK/NG" HO results, RSRP at HO, InterHO/IntraHO test results, or wants a management-friendly diagram/report of what happened in a drive/field test capture - even if they only say "check this capture" or "summarize this trace" and the file name hints at HO testing.
---

# ho-pcap-analyzer

Turns an F1-interface capture into a handover verdict per event, with diagrams a non-specialist can follow.
Everything runs in pure Python (`pycrate` for the ASN.1) - no tshark/Wireshark needed, no root.

## What you get

`scripts/ho_analyze.py capture.pcapng --out ho_out --tz Asia/Tokyo` writes:

| file | what it is |
|---|---|
| `summary.txt` | headline numbers, NG breakdown, per-cell-pair OK/NG table, one line per HO event, lap count (drive tests on a loop), measurement reports that got no HO command, RLFs not linked to a HO |
| `ho_events.csv` | one row per HO attempt (opens in Excel): time, UE, source PCI -> target PCI, serving/target RSRP, trigger event (A3...), intra/inter-DU, OK/NG, failure class, latency, re-establishment cause/cell |
| `ho_events.json` | same plus per-UE message logs; input for the report |
| `f1_timeline.txt` | every F1AP/RRC message decoded on one line (frame, time, DU IP, CU/DU UE ids, decoded RRC) - grep this when you need to show the raw evidence |

`scripts/ue_events.py capture.pcapng --out ue_out --tz Asia/Tokyo` answers the per-UE question - for each UE and each lap: how many handovers (OK/NG), how many UE context releases *excluding* the housekeeping release of the source DU after an inter-DU handover, their F1AP and NGAP causes, and how many RRC re-establishments with their causes. It keys everything to a stable UE identity: it looks for a SUCI/SUPI (MSIN) in NAS, and when the UEs were already registered before the capture started - so no SUCI is ever sent - it builds a **5G-TMSI chain** instead (each Registration Accept / Configuration Update Command hands out a new GUTI, and the next Registration Request quotes the old one), which stitches all the RRC connections of one physical UE together. It writes `ue_events.csv`, `ue_events.md` (paste-ready), `ue_identity.csv` (every CU/DU/C-RNTI/AMF id mapped to the UE) and `ue_events.json`. Say plainly that MSIN is *not in the capture* when no SUCI appears - never guess one from a TMSI.

`scripts/ho_report.py ho_out/ho_events.json --title "..." [--lang en|ja|both]` writes `ho_out/ho_report.html` (default `both` = one page with an English / 日本語 switch; `ja` or `en` for a single-language page), self-contained (inline SVG, no external resources): stat tiles, a "how to read a handover" explainer ladder (OK / handoverFailure / otherFailure), a cell map with OK/NG counts on each arrow, a serving-cell-over-time journey chart, the full event table, one real message-flow diagram per NG event, and the RLF list.

## Workflow

1. **Set up** - `python3 -c "import pycrate_asn1dir"` ; if missing: `pip install pycrate` (fallback: `pip install git+https://github.com/pycrate-org/pycrate`, or clone it and add the folder to a `.pth`). Check the capture actually carries F1AP: `python3 scripts/ho_analyze.py capture.pcapng` prints "F1AP messages: N"; N=0 means the capture is not from the F1 interface (see *Limits*).
2. **Analyze** - run `ho_analyze.py` with the user's timezone (`--tz Asia/Tokyo` for Japan). Read `summary.txt` fully before writing anything. For a drive test on a loop (car/train passing the same cells again and again) the LAPS block counts complete laps; the route is learned from the dominant HO direction - if the user names the route or the start cell, pass `--ring 101,202,...` / `--lap-start 101` instead of trusting the learned one.
3. **Sanity-check the verdicts** before trusting them (the script is deterministic, but the capture may contain sequences it has not seen) - open `f1_timeline.txt` around 2-3 events (one OK, every NG) and confirm the story matches: HO command frame -> RRCReconfigurationComplete (OK) or RRCReestablishmentRequest / UE Context Release (NG). Also check the `Cells (PCI) ... cell-id map` line: if a PCI shows as `None`/`?`, the NR Cell Identity -> PCI mapping could not be learned (capture has no F1 Setup and no HO into that cell); say so instead of guessing.
4. **Report** - run `ho_report.py` (default output is bilingual EN/JA with a switch at the top; use `--lang ja` when the audience is Japanese-only), then look at it (render a screenshot with Playwright/Chromium when available; otherwise at least open the HTML text and check the tiles and table are populated). Deliver `ho_report.html`, `ho_events.csv` and `summary.txt`; publish the HTML as an artifact when the session has that tool, since these reports get shared with the team.
5. **Explain in words** - a short narrative on top of the numbers (see *Writing the summary*). The diagram is the "what", the narrative is the "so what".

`references/ho-classification.md` has the exact rules the script applies (what counts as OK/NG, how a re-establishment is tied to a HO, RSRP conversion, known ambiguities). Read it when a verdict looks odd or the user challenges one.
`references/f1-ho-cheatsheet.md` explains what an intra-DU vs inter-DU HO looks like on F1AP and which RRC messages carry what - read it when digging into `f1_timeline.txt` or extending the script.
`references/wireshark-filters.md` has display filters to reproduce every finding in Wireshark/tshark (users often want to double-check in the GUI).

## Writing the summary

Readers are usually mixed: the engineer who ran the test and a manager who wants "did it work?". Lead with the verdict, then the pattern, then the evidence.

- Verdict: attempts, OK, NG, success rate, and the NG split by class (`Reestablishment/handoverFailure`, `Reestablishment/otherFailure`, `NoResponse/...`).
- Pattern: which cell pairs fail, and what the RSRP at trigger looked like. A serving RSRP below about -115 dBm at the moment of the measurement report is the most common reason for `otherFailure` (link drops before the HO completes); `handoverFailure` after ~T304 (often 10 s here) means the UE could not access the target cell (random access / coverage / target not ready). "NoResponse + new RRCSetupRequest a few seconds later" is the UE silently dropping and re-attaching - count it as a failed HO.
- The headline OK/NG split only judges the HO procedure itself. The summary also lists three things that hide behind an "OK" and matter just as much in a field test - always report them:
  - `OK but dropped within 5 s`: the HO completed but the CU released the UE context right after. When the line says the DU never answered the post-HO UE Context Modification Request, that is a DU/CU software issue (the CU's procedure timer expired), not radio - do not blame coverage for it.
  - `OK but RLF right after`: the UE re-established within a few seconds of the HO - the HO was late or the target was not really better.
  - `MEASUREMENT REPORTS NOT FOLLOWED BY A HO COMMAND` and `RADIO LINK FAILURES NOT LINKED TO A HANDOVER`: the UE asked for a HO (A3) and got none, then dragged until RLF and changed cell by re-establishment ("was on PCI X -> sent on PCI Y"). A cluster marked *after re-establishment* means the CU stops handing over once a UE has re-established - a CU bug worth naming explicitly.
- For loop drive tests, report laps: complete laps, how many were *clean* (every cell change a successful HO), and what broke the others (re-establishments, dropped-and-reconnected, NG). "15 laps, 0 clean" says more to a manager than the 93 % HO success rate.
- Timer fingerprints are worth calling out: a release consistently N s after an unanswered command is the CU's HO/procedure guard timer; compare it with T304 in the HO command (e.g. 3 s guard vs T304 = 10 s means a late re-establishment can only be answered with RRCSetup, turning a recoverable failure into a full reconnect).
- Evidence: cite frame numbers and times from `f1_timeline.txt` for each NG event so the engineer can jump to them in Wireshark.
- Keep the language plain: "the phone lost the signal before the switch finished", not just "RLF".

Tell the user the RSRP values are SS-RSRP from the UE's measurement report (index - 156 dBm), i.e. what the UE saw, not what the RU transmitted.

## Limits (say them when relevant)

- Only F1AP-carried RRC is decoded (CU-side or DU-side F1 capture, SCTP PPID 62). Xn/NG-based inter-gNB handovers (XnAP/NGAP HandoverRequest) and Uu-side (UE log) captures are not analyzed by the script; NGAP messages are only counted.
- Encrypted/ciphered RRC (nea1-3) cannot be decoded - the script assumes nea0, which is standard in lab/PoC setups. Integrity-only is fine.
- Serving-cell PCI comes from tracking the UE (RRCSetup cell -> each OK HO target), not from the measurement report, which only carries the serving RSRP. A capture that starts mid-session can leave the first HO of a UE with an unknown source PCI.
- Intra-DU handovers keep the same C-RNTI, so a re-establishment is attributed to the latest HO attempt of that (PCI, C-RNTI); this is right in practice but is a heuristic.
- MSIN/SUPI only appears if a UE sends a SUCI (initial registration with the null protection scheme). A UE that was already registered when the capture started identifies itself with a 5G-GUTI or 5G-S-TMSI, so the capture contains no MSIN - report the TMSI chain and say so, and tell the user that getting MSIN needs either a capture that starts at UE power-on or a TMSI-to-IMSI mapping from the core (Open5GS logs it).
- 5G-S-TMSI is used to recognise the same UE across RRC connections; when the core re-allocates the TMSI on every registration (common), UE labels change and the "next RRCSetupRequest, probably the same UE" hint is only a hint (true in single-UE drive tests).
