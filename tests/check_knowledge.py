#!/usr/bin/env python3
"""Every knowledge file parses, and every described code has real text."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import knowledge  # noqa: E402
from lib import nodes as node_lib  # noqa: E402

problems = []

topology = node_lib.load_topology()
if not topology:
    problems.append("knowledge/topology.yaml: no equipment defined")
for node_id, entry in topology.items():
    entry = entry or {}
    if not entry.get("name"):
        problems.append(f"knowledge/topology.yaml: {node_id} has no name")
    if entry.get("role") not in node_lib.ROLES:
        problems.append(f"knowledge/topology.yaml: {node_id} has role "
                        f"{entry.get('role')!r}; expected one of "
                        f"{', '.join(node_lib.ROLES)}")
    interfaces = entry.get("interfaces")
    if interfaces is not None and not isinstance(interfaces, dict):
        problems.append(f"knowledge/topology.yaml: {node_id} interfaces "
                        f"should be a mapping of id to label")

# The committed example has to stay loadable, since it is what people copy and
# what the fallback uses when no lab profile is chosen.
for name in ("nodes.yaml", "addresses.example.yaml"):
    try:
        node_lib.read_profile(node_lib.KNOWLEDGE / name, topology)
    except node_lib.ProfileError as error:
        problems.append(f"knowledge/{name}: {error}")

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
