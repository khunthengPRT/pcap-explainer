# F1 handover cheat-sheet (what the capture looks like)

## Transport

Ethernet / Linux SLL / SLL2 -> IPv4/IPv6 -> SCTP -> DATA chunks with **PPID 62 = F1AP** (60 = NGAP, 61 = XnAP, 64 = E1AP).
F1AP is ASN.1 **aligned PER**; RRC inside the RRC-Container IEs is **unaligned PER** (`from_uper`).
RRC-Container on SRB1/SRB2 is a **PDCP PDU**: 2-byte PDCP header (R|R|R|R|SN12) + RRC + 4-byte MAC-I -> strip `buf[2:-4]`. On SRB0 (CCCH, `INITIAL UL RRC MESSAGE TRANSFER`, `RRCSetup` in DL RRC) the container is the bare RRC message.

## F1AP procedure codes / IE ids used

| code | procedure | IE ids of interest |
|---|---|---|
| 1 / 3 | F1 Setup / gNB-DU Config Update | served-Cell-Information: nRCGI, nRPCI |
| 5 | UE Context Setup | 63 SpCell ID (NRCGI), 50 RRC-Container (HO preparation), resp: 39 DUtoCURRCInformation.cellGroupConfig, 95 C-RNTI |
| 7 | UE Context Modification | 63 SpCell ID (intra-DU HO target), 50 RRC-Container (HO command to source DU), 79 TransmissionActionIndicator=stop, resp: 39 DUtoCURRCInformation |
| 6 | UE Context Release Command | 0 Cause (normal-release after OK inter-DU HO; unspecified/other = failure) |
| 10 | UE Context Release Request (DU -> CU) | 0 Cause: rl-failure-rlc, rl-failure-others, unspecified |
| 11 | Initial UL RRC Message Transfer | 41 DU-UE id, 111 NRCGI (cell where received), 95 C-RNTI, 50 RRC-Container (RRCSetupRequest / RRCReestablishmentRequest) |
| 12 | DL RRC Message Transfer | 40/41 ids, 64 SRB id, 50 RRC-Container |
| 13 | UL RRC Message Transfer | 40/41 ids, 64 SRB id, 50 RRC-Container |

UE identity on F1: `gNB-CU-UE-F1AP-ID` (40) is stable for the life of the CU context (survives inter-DU HO and re-establishment); `gNB-DU-UE-F1AP-ID` (41) changes per DU context. The CCCH message (pc 11) has no CU id yet - the first DL message with the same (DU IP, DU-UE id) reveals it.

## Intra-DU HO on F1 (same DU, different cell)

```
UE -> DU -> CU   UL RRC: MeasurementReport (measId n, serving RSRP, neighbour PCI + RSRP)
CU -> DU         UE CONTEXT MODIFICATION REQUEST  (SpCell ID = target NRCGI, TxActionIndicator=stop)
DU -> CU         UE CONTEXT MODIFICATION RESPONSE (DUtoCU: CellGroupConfig with reconfigurationWithSync {physCellId=target, newUE-Identity})
CU -> DU -> UE   DL RRC: RRCReconfiguration (masterCellGroup with that reconfigurationWithSync, + measConfig)   <- HO COMMAND
UE -> DU -> CU   UL RRC: RRCReconfigurationComplete                                                              <- OK
CU -> DU         UE CONTEXT MODIFICATION REQUEST (resume)
```

## Inter-DU HO on F1 (target on another DU, same CU)

```
UE -> DU1 -> CU  UL RRC: MeasurementReport
CU -> DU2        UE CONTEXT SETUP REQUEST  (SpCell ID = target NRCGI, CU-UE id only)
DU2 -> CU        UE CONTEXT SETUP RESPONSE (new DU-UE id, C-RNTI, DUtoCU CellGroupConfig with reconfigurationWithSync)
CU -> DU1        UE CONTEXT MODIFICATION REQUEST (RRC-Container = RRCReconfiguration HO command, TxActionIndicator=stop)
DU1 -> CU        UE CONTEXT MODIFICATION RESPONSE
UE -> DU2 -> CU  UL RRC: RRCReconfigurationComplete  (from the target DU!)                                        <- OK
CU -> DU2        UE CONTEXT MODIFICATION REQUEST
CU -> DU1        UE CONTEXT RELEASE COMMAND (cause normal-release)
```

## Failure signatures

```
RRCReestablishmentRequest (pc 11, on whichever cell the UE picked)
   ue-Identity { c-RNTI, physCellId, shortMAC-I }  = identity in the cell the UE was LAST connected to
   reestablishmentCause: reconfigurationFailure | handoverFailure | otherFailure
CU answer:  DL RRC RRCReestablishment (context found)  ->  UL RRC RRCReestablishmentComplete -> RRCReconfiguration (measConfig) ...
        or: DL RRC RRCSetup (fallback: no context / MAC-I mismatch) -> new CU-UE id, old context released (cause unspecified)
No answer:  CU -> DU UE CONTEXT RELEASE COMMAND (unspecified) ~3 s after the HO command, UE later sends a fresh RRCSetupRequest
DU RLF:     DU -> CU UE CONTEXT RELEASE REQUEST cause rl-failure-rlc / rl-failure-others
```

## RRC field paths (pycrate value tree)

- `DL-DCCH-Message.message.c1.rrcReconfiguration.criticalExtensions.rrcReconfiguration.nonCriticalExtension.masterCellGroup` -> CellGroupConfig (pycrate decodes the CONTAINING type automatically -> tuple `('CellGroupConfig', {...})`)
- `CellGroupConfig.spCellConfig.reconfigurationWithSync.{spCellConfigCommon.physCellId, newUE-Identity, t304}`
- `UL-DCCH-Message ... measurementReport.criticalExtensions.measurementReport.measResults.{measId, measResultServingMOList[].measResultServingCell.measResult.cellResults.resultsSSB-Cell.rsrp, measResultNeighCells.measResultListNR[].{physCellId, measResult...rsrp}}`
- `measConfig.reportConfigToAddModList[].reportConfig.reportConfigNR.reportType.eventTriggered.eventId.eventA3.{a3-Offset.rsrp, hysteresis, timeToTrigger}` ; `measIdToAddModList[].{measId, measObjectId, reportConfigId}`
- `UL-CCCH-Message.message.c1.rrcReestablishmentRequest.rrcReestablishmentRequest.{ue-Identity.{c-RNTI, physCellId}, reestablishmentCause}`
- `rrcSetupRequest.rrcSetupRequest.ue-Identity` = `('ng-5G-S-TMSI-Part1', (value, 39))` or `('randomValue', ...)`; `rrcSetupComplete ... ng-5G-S-TMSI-Value` = `('ng-5G-S-TMSI', (value, 48))` (Part1 = low 39 bits) or Part2.
