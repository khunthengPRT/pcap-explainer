#!/usr/bin/env bash
# Stage 0: what is in this capture, and do we know who everyone is?
#
# Run this before anything else. If it lists addresses the active lab profile
# does not name, name them there first - otherwise the report will refer to
# people by IP address, which defeats the point.
#
# The profile is chosen by --nodes, else $PCAP_NODES, else $PCAP_LAB. It is
# never guessed from the capture: two labs can reuse an address for different
# equipment, so guessing would mislabel silently. See labs/README.md.
#
# Usage: bash scripts/survey.sh <capture.pcap> [--nodes PATH]
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: bash scripts/survey.sh <capture.pcap> [--nodes PATH]" >&2
    exit 2
fi

PCAP="$1"
shift
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$PCAP" ]; then
    echo "capture not found: $PCAP" >&2
    exit 1
fi
for tool in tshark capinfos; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool not found on PATH. Install tshark (Debian/Ubuntu: sudo apt install tshark)." >&2
        exit 1
    fi
done

echo "=== The capture itself ==="
capinfos -c -u -a -e "$PCAP" 2>/dev/null

echo
echo "=== Who talked to whom ==="
tshark -r "$PCAP" -q -z conv,ip 2>/dev/null

echo
echo "=== What protocols are in there ==="
tshark -r "$PCAP" -q -z io,phs 2>/dev/null

echo
echo "=== Do we know who these addresses are? ==="
# occurrence=f keeps this to the outer addresses: the inner ones inside a
# tunnel belong to subscribers and the internet, and are not ours to name
tshark -r "$PCAP" -T fields -E occurrence=f -e ip.src -e ip.dst 2>/dev/null \
    | tr '\t' '\n' | grep -v '^$' | sort -u \
    | python3 "$ROOT/scripts/lib/check_nodes.py" "$@"
