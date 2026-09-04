#!/usr/bin/env bash
# Everything that has to keep working. Run before committing.
#
#   bash tests/run_tests.sh
#
# Stages 2 and 3 are tested from a checked-in CSV, so most of this runs
# without tshark installed. The capture-reading test is skipped when tshark
# is missing rather than failing.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=../scripts/lib/find_python.sh
. "$ROOT/scripts/lib/find_python.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0

check() {  # check <name> <command...>
    local name="$1"; shift
    if "$@" >"$WORK/log" 2>&1; then
        echo "  pass  $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name"
        sed 's/^/        /' "$WORK/log"
        FAIL=$((FAIL + 1))
    fi
}

echo "knowledge base"
check "code tables match the tshark dissector" \
    "$PYTHON" scripts/sync_codes.py --check
check "every knowledge file is valid YAML" \
    "$PYTHON" tests/check_knowledge.py

echo "stages 2 and 3, from a checked-in CSV"
"$PYTHON" scripts/2_sessionize.py tests/fixtures/ngap-attach.csv "$WORK/ngap.json" >/dev/null 2>&1
"$PYTHON" scripts/3_render.py "$WORK/ngap.json" "$WORK/ngap.md" \
    --title "the lab radio site" --no-learn >/dev/null 2>"$WORK/ngap.warn"
check "the radio-site report is unchanged" \
    diff -u tests/expected/ngap-attach.report.md "$WORK/ngap.md"
check "the radio-site report contains no jargon" \
    test ! -s "$WORK/ngap.warn"
check "the unexplained message type was spotted" \
    "$PYTHON" tests/check_gaps.py "$WORK/ngap.json" ngap 58

echo "the whole pipeline, from a capture"
if command -v tshark >/dev/null 2>&1; then
    sample_rebuilds() {
        "$PYTHON" tests/make_sample.py "$WORK/sample.pcap" >/dev/null &&
            cmp "$WORK/sample.pcap" samples/lab-session.pcap
    }
    check "the sample capture rebuilds byte for byte" sample_rebuilds
    "$PYTHON" scripts/1_extract.py samples/lab-session.pcap "$WORK/events.csv" >/dev/null 2>&1
    "$PYTHON" scripts/2_sessionize.py "$WORK/events.csv" "$WORK/flows.json" >/dev/null 2>&1
    "$PYTHON" scripts/3_render.py "$WORK/flows.json" "$WORK/report.md" \
        --title "the lab core network" --no-learn >/dev/null 2>"$WORK/report.warn"
    check "the core-network report is unchanged" \
        diff -u tests/expected/lab-session.report.md "$WORK/report.md"
    check "the core-network report contains no jargon" \
        test ! -s "$WORK/report.warn"
else
    echo "  skip  tshark is not installed, so the capture-reading tests did not run"
fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
