# stage 0 - who?
```bash
capinfos capture.pcap
tshark -r capture.pcap -q -z conv,ip
tshark -r capture.pcap -q -z io,phs
```
# stage 1 - extract and format

```bash
tshark -r capture.pcap \
  -Y "ngap || f1ap || pfcp || gtp || sctp" \
  -T fields -E separator=, -E quote=d \
  -e frame.number -e frame.time_epoch \
  -e ip.src -e ip.dst \
  -e _ws.col.Protocol -e _ws.col.Info \
  -e ngap.procedureCode -e ngap.RAN_UE_NGAP_ID \
  -e f1ap.procedureCode -e pfcp.seid -e gtp.teid \
  > out/events.csv
```
# stage 2 - group rows into procedure
```bash
...
```
