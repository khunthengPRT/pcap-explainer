#!/usr/bin/env python3
"""Assert that a flows.json records a gap for a given protocol and code.

Usage: python tests/check_gaps.py <flows.json> <protocol> <code>
"""
import json
import sys

flows, protocol, code = sys.argv[1], sys.argv[2], int(sys.argv[3])
gaps = json.load(open(flows)).get("gaps", [])
if any(gap["protocol"] == protocol and gap["code"] == code for gap in gaps):
    sys.exit(0)
print(f"expected a gap for {protocol} code {code}, found: "
      f"{[(g['protocol'], g['code']) for g in gaps]}")
sys.exit(1)
