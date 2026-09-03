#!/usr/bin/env python3
"""Build samples/lab-session.pcap: a small, synthetic 5G core capture.

Hand-built rather than recorded so the golden outputs are stable and the
repository stays free of anything from a real network. It contains the cases
the pipeline has to get right: a request that is answered, one that is
refused with a reason, one that is never answered, keep-alives, traffic
tunnels, and a control connection being set up.

Usage: python tests/make_sample.py [samples/lab-session.pcap]
"""
import struct
import sys
from pathlib import Path

CP = "10.10.2.21"     # session manager (control plane)
UP = "10.10.2.30"     # traffic forwarder (user plane)
GNB = "10.10.1.11"    # base station, antenna side
AMF = "10.10.2.20"    # access manager

MAC_A = bytes.fromhex("020000000001")
MAC_B = bytes.fromhex("020000000002")

T0 = 1_767_225_600.0  # 2026-01-01 00:00:00 UTC, fixed so output is repeatable


def ip_to_bytes(address):
    return bytes(int(part) for part in address.split("."))


def checksum16(data):
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for index in range(0, len(data), 2):
        total += (data[index] << 8) + data[index + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def ipv4(src, dst, protocol, payload):
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45, 0, 20 + len(payload), 0, 0x4000, 64, protocol, 0,
        ip_to_bytes(src), ip_to_bytes(dst),
    )
    header = header[:10] + struct.pack("!H", checksum16(header)) + header[12:]
    return header + payload


def udp(sport, dport, payload):
    # checksum 0 is legal for IPv4 UDP and keeps this builder simple
    return struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload


def frame(src, dst, protocol, payload):
    return MAC_A + MAC_B + b"\x08\x00" + ipv4(src, dst, protocol, payload)


def ie(tag, value):
    return struct.pack("!HH", tag, len(value)) + value


NODE_ID, CAUSE, F_SEID, RECOVERY = 60, 19, 57, 96


def node_id(address):
    return ie(NODE_ID, b"\x00" + ip_to_bytes(address))


def f_seid(seid, address):
    return ie(F_SEID, b"\x02" + struct.pack("!Q", seid) + ip_to_bytes(address))


def pfcp(msg_type, seq, ies, seid=None):
    """TS 29.244 section 7.2: 4-octet mandatory part, then SEID if the S flag
    is set, then a 3-octet sequence number and one spare octet."""
    body = b"".join(ies)
    if seid is None:
        flags, tail = 0x20, struct.pack("!I", seq)[1:] + b"\x00"
    else:
        flags, tail = 0x21, struct.pack("!Q", seid) + struct.pack("!I", seq)[1:] + b"\x00"
    length = len(tail) + len(body)
    return struct.pack("!BBH", flags, msg_type, length) + tail + body


def gtpu(msg_type, teid, payload=b""):
    return struct.pack("!BBHI", 0x30, msg_type, len(payload), teid) + payload


def sctp_chunk(chunk_type, value):
    padded = value + b"\x00" * (-len(value) % 4)
    return struct.pack("!BBH", chunk_type, 0, 4 + len(value)) + padded


def sctp(sport, dport, vtag, chunks):
    # checksum left at zero: tshark dissects regardless and nothing here
    # depends on it being valid
    return struct.pack("!HHII", sport, dport, vtag, 0) + b"".join(chunks)


def init_chunk():
    return sctp_chunk(1, struct.pack("!IIHHI", 0x1234ABCD, 62464, 10, 10, 1))


def init_ack_chunk():
    return sctp_chunk(2, struct.pack("!IIHHI", 0x5678BEEF, 62464, 10, 10, 1)
                      + b"\x00\x07\x00\x0ccookie!!")


def build():
    packets = []  # (timestamp, ethernet frame)

    def add(offset, src, dst, protocol, payload):
        packets.append((T0 + offset, frame(src, dst, protocol, payload)))

    def add_pfcp(offset, src, dst, payload):
        sport, dport = (8805, 8805)
        add(offset, src, dst, 17, udp(sport, dport, payload))

    # The control connection between the base station and the core comes up.
    add(0.000, GNB, AMF, 132, sctp(50000, 38412, 0, [init_chunk()]))
    add(0.012, AMF, GNB, 132, sctp(38412, 50000, 0x1234ABCD, [init_ack_chunk()]))

    # The session manager and the traffic forwarder agree to work together.
    add_pfcp(0.100, CP, UP, pfcp(5, 1, [node_id(CP), ie(RECOVERY, b"\x00\x00\x00\x01")]))
    add_pfcp(0.118, UP, CP, pfcp(6, 1, [node_id(UP), ie(CAUSE, b"\x01"),
                                        ie(RECOVERY, b"\x00\x00\x00\x02")]))

    # A subscriber connection is set up, and accepted.
    add_pfcp(1.000, CP, UP, pfcp(50, 2, [node_id(CP), f_seid(0x1001, CP)], seid=0))
    add_pfcp(1.031, UP, CP, pfcp(51, 2, [node_id(UP), ie(CAUSE, b"\x01"),
                                         f_seid(0x2001, UP)], seid=0x1001))

    # A second one is refused: the forwarder has no capacity left (cause 75).
    add_pfcp(1.500, CP, UP, pfcp(50, 3, [node_id(CP), f_seid(0x1002, CP)], seid=0))
    add_pfcp(1.544, UP, CP, pfcp(51, 3, [node_id(UP), ie(CAUSE, b"\x4b")], seid=0x1002))

    # Subscriber traffic flows through the tunnel that was set up.
    inner = ipv4("10.45.0.2", "8.8.8.8", 17, udp(40000, 53, b"\x00" * 40))
    for index in range(6):
        add(2.0 + index * 0.05, GNB, UP, 17, udp(2152, 2152, gtpu(255, 0x2001, inner)))
    reply = ipv4("8.8.8.8", "10.45.0.2", 17, udp(53, 40000, b"\x00" * 80))
    for index in range(4):
        add(2.1 + index * 0.05, UP, GNB, 17, udp(2152, 2152, gtpu(255, 0x1001, reply)))

    # Keep-alives on the tunnel path.
    add(3.000, CP, UP, 17, udp(2152, 2152, gtpu(1, 0)))
    add(3.020, UP, CP, 17, udp(2152, 2152, gtpu(2, 0)))

    # The first subscriber connection is torn down - and nothing answers.
    add_pfcp(4.000, CP, UP, pfcp(54, 4, [], seid=0x2001))

    # A keep-alive between the two control-plane nodes.
    add_pfcp(5.000, CP, UP, pfcp(1, 5, [ie(RECOVERY, b"\x00\x00\x00\x01")]))
    add_pfcp(5.009, UP, CP, pfcp(2, 5, [ie(RECOVERY, b"\x00\x00\x00\x02")]))

    return packets


def write_pcap(path, packets):
    with open(path, "wb") as handle:
        handle.write(struct.pack("!IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for timestamp, data in packets:
            handle.write(struct.pack("!IIII", int(timestamp),
                                     int(round((timestamp % 1) * 1_000_000)),
                                     len(data), len(data)))
            handle.write(data)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "samples/lab-session.pcap")
    out.parent.mkdir(parents=True, exist_ok=True)
    packets = build()
    write_pcap(out, packets)
    print(f"{len(packets)} packets -> {out}")
