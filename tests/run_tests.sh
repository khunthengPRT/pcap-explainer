#!/usr/bin/env bash
# Everything that has to keep working. Run before committing.
#
#   bash tests/run_tests.sh
#
# Stages 2 and 3 are tested from a checked-in CSV, so most of this runs
# without tshark installed. The capture-reading test is skipped when tshark
# is missing rather than failing.
#
# Rendering always pins --nodes to the committed example, so that whichever lab
# profile a developer has selected cannot change what these tests compare.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
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
    python3 scripts/sync_codes.py --check
check "every knowledge file is valid YAML" \
    python3 tests/check_knowledge.py
check "lab profiles resolve, and fail loudly when they cannot" \
    python3 tests/check_profiles.py
check "no local lab addresses reached a tracked file" \
    python3 tests/check_no_lab_data.py

echo "stages 2 and 3, from a checked-in CSV"
python3 scripts/2_sessionize.py tests/fixtures/ngap-attach.csv "$WORK/ngap.json" >/dev/null 2>&1
python3 scripts/3_render.py "$WORK/ngap.json" "$WORK/ngap.md" \
    --title "the lab radio site" --no-learn --nodes knowledge/nodes.yaml \
    >/dev/null 2>"$WORK/ngap.warn"
check "the radio-site report is unchanged" \
    diff -u tests/expected/ngap-attach.report.md "$WORK/ngap.md"
grep -v '^naming equipment from ' "$WORK/ngap.warn" > "$WORK/ngap.jargon" || true
check "the radio-site report contains no jargon" \
    test ! -s "$WORK/ngap.jargon"
check "the unexplained message type was spotted" \
    python3 tests/check_gaps.py "$WORK/ngap.json" ngap 58

# A report meant to leave the machine must carry no addresses at all, not even
# for the equipment the profile could not name.
python3 scripts/3_render.py "$WORK/ngap.json" "$WORK/redacted.md" \
    --title "the lab radio site" --no-learn --nodes knowledge/nodes.yaml \
    --redact-addresses >/dev/null 2>&1
check "a redacted report contains no addresses" \
    bash -c '! grep -Eq "\b[0-9]{1,3}(\.[0-9]{1,3}){3}\b" "'"$WORK"'/redacted.md"'
check "a redacted report still names the equipment it knows" \
    grep -q "Core network access manager" "$WORK/redacted.md"

# A lab that was asked for by name and does not exist has to stop the run. The
# alternative - quietly using another lab's numbering - is invisible in the
# finished report, which is the whole reason profiles are separate.
check "an unknown PCAP_LAB stops the run" \
    bash -c 'PCAP_LAB=no-such-lab python3 scripts/3_render.py "'"$WORK"'/ngap.json" \
             "'"$WORK"'/never.md" --no-learn 2>&1 | grep -q "no profile for it"'

echo "the whole pipeline, from a capture"
if command -v tshark >/dev/null 2>&1; then
    check "the sample capture rebuilds byte for byte" \
        bash -c 'python3 tests/make_sample.py "'"$WORK"'/sample.pcap" >/dev/null &&
                 cmp "'"$WORK"'/sample.pcap" samples/lab-session.pcap'
    python3 scripts/1_extract.py samples/lab-session.pcap "$WORK/events.csv" >/dev/null 2>&1
    python3 scripts/2_sessionize.py "$WORK/events.csv" "$WORK/flows.json" >/dev/null 2>&1
    python3 scripts/3_render.py "$WORK/flows.json" "$WORK/report.md" \
        --title "the lab core network" --no-learn --nodes knowledge/nodes.yaml \
        >/dev/null 2>"$WORK/report.warn"
    check "the core-network report is unchanged" \
        diff -u tests/expected/lab-session.report.md "$WORK/report.md"
    grep -v '^naming equipment from ' "$WORK/report.warn" \
        > "$WORK/report.jargon" || true
    check "the core-network report contains no jargon" \
        test ! -s "$WORK/report.jargon"
else
    echo "  skip  tshark is not installed, so the capture-reading tests did not run"
fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
