# What happened on the lab core network

This covers 5.0 seconds of traffic recorded on 01 January 2026 at 00:00 UTC, between 4 pieces of equipment. It contains 6 exchanges and 23 messages in total. 2 of those exchanges did not succeed; they are set out below. Alongside the signalling, 2 traffic tunnels carried 1.3 kB of subscriber data.

## Who was involved

| Who | Address | What it does | Messages |
|-----|---------|--------------|----------|
| Traffic forwarder | 10.10.2.30 | Carries subscriber data between the base stations and the internet | 21 |
| Base station antenna side (site A) | 10.10.1.11 | Distributed unit of the split base station at site A | 12 |
| Core network session manager | 10.10.2.21 | Decides the rules for each subscriber's data connection | 11 |
| Core network access manager | 10.10.2.20 | Handles phones joining the network and staying reachable | 2 |

## What happened, in order

| When | What | Between | Result |
|------|------|---------|--------|
| +0.100s | The core network and the traffic forwarder introduced themselves and agreed to work together. | Core network session manager to Traffic forwarder | Accepted |
| +1.000s | The core network asked the traffic forwarder to start carrying one subscriber's traffic, and gave it the rules for doing so. | Core network session manager to Traffic forwarder | Accepted |
| +1.500s | The core network asked the traffic forwarder to start carrying one subscriber's traffic, and gave it the rules for doing so. | Core network session manager to Traffic forwarder | Refused |
| +3.000s | A keep-alive check between the two ends of a traffic tunnel. | Core network session manager to Traffic forwarder | Accepted |
| +4.000s | The core network asked the traffic forwarder to stop carrying one subscriber's traffic. | Core network session manager to Traffic forwarder | No answer |
| +5.000s | A keep-alive check between the core network and the traffic forwarder. | Core network session manager to Traffic forwarder | Accepted |

## Traffic carried

| Tunnel | Direction | Packets | Carried |
|--------|-----------|---------|---------|
| 0x00002001 | Base station antenna side (site A) to Traffic forwarder | 6 | 708 bytes |
| 0x00001001 | Traffic forwarder to Base station antenna side (site A) | 4 | 632 bytes |

## Connections between equipment

- Between Base station antenna side (site A) and Core network access manager: One side opened a connection to the other (1 time); The other side accepted the connection (1 time).

## What went wrong

- **Refused.** The core network asked the traffic forwarder to start carrying one subscriber's traffic, and gave it the rules for doing so - and it was turned down. Reason given: The forwarder has no capacity left. (Core network session manager asked Traffic forwarder, at +1.500s.)
- **No answer.** The core network asked the traffic forwarder to stop carrying one subscriber's traffic - and nothing came back, though an answer was due. This concerned subscriber connection 0x0000000000002001. (Core network session manager asked Traffic forwarder, at +4.000s.)

## What it means

What failed affected subscriber connection 0x0000000000002001. Anyone using that would have seen the service fail to start, or drop.

1 of the failures cannot be traced to one subscriber from this capture alone. They are between the equipment itself, so they affect everyone that equipment serves.

## Reference

| Frames | Protocol | Message | Outcome |
|--------|----------|---------|---------|
| 3, 4 | PFCP | PFCP Association Setup Request | completed |
| 5, 6 | PFCP | PFCP Session Establishment Request | completed |
| 7, 8 | PFCP | PFCP Session Establishment Request | failed |
| 19, 20 | GTP | Echo request | completed |
| 21 | PFCP | PFCP Session Deletion Request | no reply |
| 22, 23 | PFCP | PFCP Heartbeat Request | completed |
