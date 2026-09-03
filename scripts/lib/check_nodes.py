#!/usr/bin/env python3
"""Read IP addresses on stdin, report which ones knowledge/nodes.yaml names.

Used by scripts/survey.sh. Exits 1 if any address is unnamed, so the survey
step fails loudly rather than letting bare IPs reach a report.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import knowledge  # noqa: E402


def main():
    nodes = knowledge.load_nodes()
    addresses = [line.strip() for line in sys.stdin if line.strip()]
    unknown = []
    for address in addresses:
        entry = nodes.get(address)
        if entry:
            print(f"  known    {address:<18} {entry.get('name')}")
        else:
            unknown.append(address)
            print(f"  UNKNOWN  {address}")
    if unknown:
        print(f"\n{len(unknown)} address(es) are not named. Add them to "
              f"knowledge/nodes.yaml before rendering a report:")
        for address in unknown:
            print(f"  {address}:\n    name: \"\"\n    role: other")
        sys.exit(1)
    print(f"\nAll {len(addresses)} address(es) are named.")


if __name__ == "__main__":
    main()
