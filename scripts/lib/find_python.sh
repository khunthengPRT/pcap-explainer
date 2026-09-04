# Sets PYTHON to a Python 3.9+ interpreter, or exits 1.
#
# Sourced by scripts/survey.sh and tests/run_tests.sh. `python3` does not
# exist in Git Bash on Windows - the python.org installer only puts
# `python.exe` on PATH - so try both, and let PYTHON= override either way.

if [ -z "${PYTHON:-}" ]; then
    for _candidate in python3 python; do
        if command -v "$_candidate" >/dev/null 2>&1 &&
           "$_candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
               >/dev/null 2>&1; then
            PYTHON="$_candidate"
            break
        fi
    done
    unset _candidate
fi

if [ -z "${PYTHON:-}" ]; then
    echo "no Python 3.9+ on PATH (tried python3, python)." >&2
    echo "Install it, or point at one: PYTHON=/path/to/python bash <script>" >&2
    exit 1
fi
