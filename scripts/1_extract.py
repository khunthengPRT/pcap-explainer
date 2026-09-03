#!/usr/bin/env python3
"""Stage 1: capture -> out/events.csv, one row per signalling packet.

This is the only script that touches the capture file. Everything downstream
works from the CSV, so no raw packet ever has to be read by a human or a model.

Usage: python scripts/1_extract.py <capture.pcap> <out/events.csv>
                                   [--filter <display filter>]
"""
import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_FILTER = "ngap || f1ap || pfcp || gtp || sctp"

# CSV column -> tshark field. Order here is the column order in events.csv.
FIELDS = [
    ("frame", "frame.number"),
    ("time", "frame.time_epoch"),
    ("bytes", "frame.len"),
    ("src", "ip.src"),
    ("dst", "ip.dst"),
    ("proto", "_ws.col.Protocol"),
    ("info", "_ws.col.Info"),
    ("ngap_pdu", "ngap.NGAP_PDU"),
    ("ngap_proc", "ngap.procedureCode"),
    ("ran_ue_id", "ngap.RAN_UE_NGAP_ID"),
    ("amf_ue_id", "ngap.AMF_UE_NGAP_ID"),
    ("f1ap_pdu", "f1ap.F1AP_PDU"),
    ("f1ap_proc", "f1ap.procedureCode"),
    ("du_ue_id", "f1ap.GNB_DU_UE_F1AP_ID"),
    ("cu_ue_id", "f1ap.GNB_CU_UE_F1AP_ID"),
    ("pfcp_type", "pfcp.msg_type"),
    ("pfcp_seid", "pfcp.seid"),
    ("pfcp_seq", "pfcp.seqno"),
    ("pfcp_cause", "pfcp.cause"),
    ("gtp_type", "gtp.message"),
    ("gtp_teid", "gtp.teid"),
    ("sctp_chunk", "sctp.chunk_type"),
    ("sctp_stream", "sctp.data_sid"),
]


def run_tshark(pcap, display_filter):
    if not shutil.which("tshark"):
        sys.exit(
            "tshark not found on PATH.\n"
            "  Debian/Ubuntu: sudo apt install tshark\n"
            "  macOS:         brew install wireshark"
        )
    cmd = ["tshark", "-r", str(pcap), "-Y", display_filter, "-T", "fields",
           "-E", "separator=,", "-E", "quote=d", "-E", "occurrence=f"]
    for _, field in FIELDS:
        cmd += ["-e", field]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"tshark failed:\n{result.stderr.strip()}")
    # tshark warns on stderr about things that do not stop the read; surface
    # them rather than swallowing them, but keep going.
    for line in result.stderr.splitlines():
        if line.strip() and "Running as user" not in line:
            print(f"tshark: {line}", file=sys.stderr)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap")
    parser.add_argument("out")
    parser.add_argument("--filter", default=DEFAULT_FILTER,
                        help=f"tshark display filter (default: {DEFAULT_FILTER!r})")
    args = parser.parse_args()

    pcap = Path(args.pcap)
    if not pcap.exists():
        sys.exit(f"capture not found: {pcap}")

    raw = run_tshark(pcap, args.filter)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    columns = [name for name, _ in FIELDS]
    rows = 0
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for record in csv.reader(raw.splitlines()):
            if not record:
                continue
            # pad short rows so downstream code can index by column safely
            record += [""] * (len(columns) - len(record))
            writer.writerow(record[:len(columns)])
            rows += 1

    print(f"{rows} packets -> {out}")
    if rows == 0:
        print(f"nothing matched the filter {args.filter!r}. Run "
              f"scripts/survey.sh {pcap} to see what is actually in the capture.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
