# Reproducing the findings in Wireshark / tshark

Wireshark decodes F1AP on SCTP PPID 62 automatically (if not: Analyze > Decode As > SCTP PPID 62 = F1AP). The RRC inside is dissected as NR RRC.

| what | display filter |
|---|---|
| HO commands (the real over-the-air ones) | `nr-rrc.reconfigurationWithSync_element and nr-rrc.rrcReconfiguration_element` |
| ... only the DL RRC copy / only the UE Context Modification copy | add `and f1ap.procedureCode == 12` / `and f1ap.procedureCode == 7` (do not count both - same command) |
| target PCI of a HO command | column `nr-rrc.physCellId` inside `reconfigurationWithSync` (custom column, or expand `spCellConfigCommon`) |
| measurement reports | `nr-rrc.measurementReport_element` ; columns `nr-rrc.measId`, `nr-rrc.physCellId`, `nr-rrc.rsrp` (serving in `measResultServingCell_element`, neighbours in `MeasResultNR_element`) |
| HO complete | `nr-rrc.rrcReconfigurationComplete_element` |
| re-establishment requests + cause | `nr-rrc.rrcReestablishmentRequest_element` ; fields `nr-rrc.reestablishmentCause`, `nr-rrc.physCellId`, `nr-rrc.c_RNTI` |
| only HO failures | `nr-rrc.reestablishmentCause == 1` (0 reconfigurationFailure, 1 handoverFailure, 2 otherFailure) |
| new connections | `nr-rrc.rrcSetupRequest_element` |
| UE context release with cause | `f1ap.UEContextReleaseCommand_element` / `f1ap.UEContextReleaseRequest_element` ; `f1ap.Cause` |
| one UE | `f1ap.GNB_CU_UE_F1AP_ID == 65582` |
| inter-DU HO preparation | `f1ap.UEContextSetupRequest_element and f1ap.SpCell_ID_element` |

tshark one-liners (the classic approach; PDML is more reliable than `-T fields` because `nr-rrc.physCellId` occurs many times per frame):

```bash
# list HO commands with time and target PCI
tshark -r cap.pcapng -Y 'nr-rrc.reconfigurationWithSync_element and f1ap.procedureCode == 12' \
  -T fields -e frame.number -e frame.time -e f1ap.GNB_CU_UE_F1AP_ID -e nr-rrc.physCellId

# re-establishment requests with cause (0 reconfigurationFailure, 1 handoverFailure, 2 otherFailure)
tshark -r cap.pcapng -Y 'nr-rrc.rrcReestablishmentRequest_element' \
  -T fields -e frame.number -e frame.time -e nr-rrc.reestablishmentCause -e nr-rrc.physCellId -e nr-rrc.c_RNTI

# full tree of a frame
tshark -r cap.pcapng -Y 'frame.number == 5019' -V
```

RSRP shown by Wireshark is the raw index; dBm = index - 156.
