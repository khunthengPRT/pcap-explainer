#!/usr/bin/env python3
"""Every knowledge file parses, and every described code has real text."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import knowledge  # noqa: E402

problems = []

nodes = knowledge.load_nodes()
for ip, entry in nodes.items():
    if not (entry or {}).get("name"):
        problems.append(f"knowledge/nodes.yaml: {ip} has no name")

terms, banned = knowledge.load_glossary()
if not terms:
    problems.append("knowledge/glossary.yaml: no terms defined")
for term in terms:
    if term.lower() in {word.lower() for word in banned}:
        problems.append(f"knowledge/glossary.yaml: {term!r} is both allowed and banned")

protocols = knowledge.load_protocols()
for name in knowledge.PROTOCOLS:
    if name not in protocols:
        problems.append(f"knowledge/protocols/{name}.yaml is missing")
        continue
    for block in ("codes", "causes"):
        for code, entry in (protocols[name].get(block) or {}).items():
            if not entry.get("name"):
                problems.append(f"{name}.yaml {block} {code}: no spec name")
            plain = entry.get("plain")
            if plain is not None and not str(plain).strip():
                problems.append(f"{name}.yaml {block} {code}: empty description")
            if entry.get("reply") not in (None, "expected", "none"):
                problems.append(f"{name}.yaml {block} {code}: bad reply value "
                                f"{entry['reply']!r}")

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
