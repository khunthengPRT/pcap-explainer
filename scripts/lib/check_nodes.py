#!/usr/bin/env python3
"""Read IP addresses on stdin, report which ones the active lab profile names.

Used by scripts/survey.sh. Exits 1 if any address is unnamed, so the survey
step fails loudly rather than letting bare IPs reach a report.

Usage: ... | python3 scripts/lib/check_nodes.py [--nodes PATH]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import nodes as node_lib  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    node_lib.add_argument(parser)
    args = parser.parse_args()

    try:
        table = node_lib.load(args.nodes)
    except node_lib.ProfileError as error:
        sys.exit(f"node profile: {error}")

    print(f"  using {table.origin}")
    addresses = [line.strip() for line in sys.stdin if line.strip()]
    unknown = []
    for address in addresses:
        entry = table.get(address)
        if entry:
            print(f"  known    {address:<18} {entry.get('name')}")
        else:
            unknown.append(address)
            print(f"  UNKNOWN  {address}")
    if unknown:
        print(f"\n{len(unknown)} address(es) are not named. Add them to "
              f"{table.source}, pointing each at equipment from "
              f"knowledge/topology.yaml:")
        for address in unknown:
            print(f"  {address}: <equipment-id>")
        print("\n(Equipment ids: " + ", ".join(sorted(node_lib.load_topology()))
              + ". Add a new one there if none of these fit.)")
        sys.exit(1)
    print(f"\nAll {len(addresses)} address(es) are named.")


if __name__ == "__main__":
    main()
