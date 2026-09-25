# How ho_analyze.py classifies handover events

## 1. What is a "HO attempt"

A `RRCReconfiguration` sent towards the UE whose `masterCellGroup` (CellGroupConfig) contains
`spCellConfig.reconfigurationWithSync`. That element names the **target PCI**
(`spCellConfigCommon.physCellId`), the **new C-RNTI** (`newUE-Identity`) and **T304**.
On F1 the message travels in one of two ways:

| path | F1AP message | typical for |
|---|---|---|
| CU -> source DU inside `UE CONTEXT MODIFICATION REQUEST` (RRC-Container IE, TransmissionActionIndicator=stop) | inter-DU HO | target is on another DU; CU first did `UE CONTEXT SETUP` on the target DU |
| CU -> DU as `DL RRC MESSAGE TRANSFER` (SRB1) | intra-DU HO | same DU; CU first did `UE CONTEXT MODIFICATION` (SpCell ID = target cell) and the DU answered with the new CellGroupConfig |

The source PCI is the UE's tracked serving cell; the trigger is the last `MeasurementReport` of that UE within `--trigger-window` seconds (default 3 s) before the command.

## 2. Verdict

| verdict | condition |
|---|---|
| **OK** | `RRCReconfigurationComplete` with the same `rrc-TransactionIdentifier` arrives from the UE (via the target DU for inter-DU) and no re-establishment / new setup of this UE happened in between. Latency = complete - command. |
| **NG - Reestablishment/handoverFailure** | an `RRCReestablishmentRequest` whose `ue-Identity` = (source PCI, source C-RNTI) or (target PCI, new C-RNTI) arrives before any Complete, with `reestablishmentCause = handoverFailure`. Per TS 38.331 this is the UE's reaction to T304 expiry: it could not complete random access / sync on the target and reverted to the source configuration. |
| **NG - Reestablishment/otherFailure** | same, but `reestablishmentCause = otherFailure` - the UE declared radio link failure (RLF: N310/T310, RLC max retx, or RA problem on the serving cell) around the HO. If the UE identifies itself with the *target* PCI + new C-RNTI it had already applied the HO configuration and lost the link on the target before the Complete could be delivered. |
| **NG - Reestablishment/reconfigurationFailure** | UE could not comply with the configuration (rare; usually a config bug). |
| **NG - NoResponse/UEContextRelease** | no Complete and no re-establishment matching this UE; the CU sent `UE CONTEXT RELEASE COMMAND` (cause other than normal-release) for the UE. Many CUs do this ~3 s after an unanswered HO command. If a brand-new `RRCSetupRequest` appears within 30 s, the detail line mentions it ("same UE" only when the 5G-S-TMSI matches, otherwise "probably the same UE"). |
| **NG - NoResponse/UEContextReleaseRequest** | same but the DU asked for release first (`UE CONTEXT RELEASE REQUEST`, cause e.g. rl-failure-rlc, rl-failure-others). |
| **NG - NoResponse / NoResponse/EndOfCapture** | nothing at all after the command (capture ended within 15 s -> EndOfCapture). |

`OK but dropped` (`post_ho_drop`): the HO completed but a `UE CONTEXT RELEASE COMMAND` (cause other than normal-release) for the UE followed within 5 s and it was the UE's latest HO. `mod_unanswered=true` means the CU's post-HO `UE CONTEXT MODIFICATION REQUEST` (the one that resumes transmission / confirms the switch) never got a response from the DU before the release - the CU timed out on the DU, so this is an F1 / DU software problem rather than radio. Such events count as OK in the HO statistics but are listed with the NG events in the report.

`OK but RLF right after` (`post_ho_rlf`): the HO completed but a matching `RRCReestablishmentRequest` followed within `--rlf-window` seconds (default 5 s). Reported as OK in the counts, flagged separately; in a field test treat it as a weak spot (the HO was late or the target was not really better).

## 3. Attaching a re-establishment to the right HO

`RRCReestablishmentRequest.ue-Identity` carries the PCI and C-RNTI of the cell the UE was last connected on. The script keeps every UE's current PCI/C-RNTI (set at RRCSetup from the F1AP C-RNTI IE + cell, updated on every OK HO with `newUE-Identity`). Because **intra-DU HOs frequently keep the same C-RNTI**, one identity can match several HO attempts; the re-establishment is attached to the **latest** attempt that precedes it. Repeated requests with the same identity within 3 s are collapsed (`repeat_of`), which happens when the first attempt gets an RRCSetup fallback.

A re-establishment that matches no HO attempt is listed under *radio link failures not linked to a handover*. When "was on PCI X" differs from the cell it was sent on, the UE effectively moved cell by re-establishment - a HO that should have happened but did not (usually the link died before the A3 report or before the CU reacted).

## 3b. Measurement reports that got no handover

Every `MeasurementReport` that is not followed by a HO command for the same UE within 2 s (and is not a stale report right after a command) is listed under `unanswered_meas`, with the serving and best-neighbour RSRP and whether the UE context was created by a re-establishment. Reasons seen in practice: the CU already released the UE (drop), the UE dropped before the CU reacted, or the CU stops handing over for re-established contexts (cluster of *after re-establishment* entries, often with a growing measConfig on each re-establishment). These are the "should have been a HO" cases; combined with the RLF list they explain cell changes that happened without a HO.

## 3c. Laps (loop drive tests)

Cell *entries* are collected in time order across all UE contexts (single-UE test assumption): every OK HO (entry into the target), every re-establishment (entry into the cell it was sent on) and every new RRCSetupRequest. The route is learned from the most frequent OK-HO successor of each cell starting at the lowest PCI (or `--ring` / `--lap-start`). A lap closes whenever the start cell is entered; it is **complete** if all other ring cells were entered during the lap and **clean** if no re-establishment, new connection or NG HO occurred in it. Re-entering an already visited cell counts as ping-pong; a start<->neighbour ping-pong right at the lap boundary is merged into the previous lap instead of opening a fake one. The capture's first and last laps are usually partial and are reported as such.

## 4. Cell identity to PCI

F1AP identifies cells by NR-CGI (36-bit NR Cell Identity); RRC uses PCI. The map is learned from, in order of preference: `F1 SETUP REQUEST` / `GNB-DU CONFIGURATION UPDATE` served-cell lists (NRCGI + NRPCI), then every (`UE CONTEXT SETUP/MODIFICATION REQUEST` SpCell NRCGI, response `DUtoCURRCInformation.cellGroupConfig ... reconfigurationWithSync.physCellId`) pair. With a capture that starts mid-test the map fills in as HOs happen; cells that never receive a HO stay unknown and show as `None`.

## 5. Numbers

- RSRP: `measQuantityResults.rsrp` is an SS-RSRP index; dBm = index - 156 (TS 38.133 Table 10.1.6.1-1; 0 = below -156, 127 = -29 or better). Rough guide: > -95 good, -95..-110 fair, -110..-115 weak, < -115 edge of coverage.
- Event labels (A3 off=+1.5dB hys=2.5dB TTT=ms40) come from the `measConfig` the CU sent to that UE (`reportConfigToAddModList` joined via `measIdToAddModList`); offsets/hysteresis are in 0.5 dB steps and are already converted.
- Latency = HO command sent by CU -> RRCReconfigurationComplete received by CU, so it includes the DU's air-interface scheduling and the UE's random access on the target; 50-300 ms is normal, > 1 s means retransmissions or a slow RACH.

## 6. Known ambiguities

- A UE that re-establishes and gets `RRCSetup` back (context not found / rejected) becomes a new CU-UE context; the old context is released with cause unspecified a moment later. The script keeps the HO verdict on the old context and links the new one through the 5G-S-TMSI when available.
- If the CU sends a second HO command to the same UE before the first is answered, the first ends as NoResponse.
- Serving RSRP in the report is the value in the triggering MeasurementReport; the target RSRP is the neighbour entry with the target PCI. If the CU picked a target that was not the best neighbour, that shows as a negative or small delta - worth pointing out.
