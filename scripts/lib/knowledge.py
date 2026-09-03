"""Loading and lookup for everything under knowledge/.

Nothing in the pipeline is allowed to describe a message in its own words. It
looks the message up here; if there is no description, it says so.
"""
from pathlib import Path

import yaml

from . import nodes as _nodes

ROOT = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE = ROOT / "knowledge"

PROTOCOLS = ("ngap", "f1ap", "pfcp", "gtp", "sctp")


def _load(path, default):
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text()) or default


def load_nodes(profile=None, lab=None):
    """Who is who, for one lab. Returns a nodes.NodeTable.

    Which lab is decided by scripts/lib/nodes.py, never guessed from the
    capture - see the note there about labs reusing addresses.
    """
    return _nodes.load(profile, lab)


def load_glossary():
    data = _load(KNOWLEDGE / "glossary.yaml", {})
    return data.get("terms") or {}, [b.lower() for b in (data.get("banned") or [])]


def load_protocols():
    """{proto: {meta..., codes: {int: {name, plain}}}}"""
    out = {}
    for proto in PROTOCOLS:
        data = _load(KNOWLEDGE / "protocols" / f"{proto}.yaml", None)
        if not data:
            continue
        for block in ("codes", "causes"):
            if block in data:
                data[block] = {
                    int(code): (entry or {})
                    for code, entry in (data[block] or {}).items()
                }
        out[proto] = data
    return out


def lookup(protocols, proto, code, block="codes"):
    """The knowledge entry for one message code, or {} if we have never
    heard of it. A missing code and a code with no plain text are the same
    thing to the report: something we cannot explain yet."""
    if code is None:
        return {}
    return ((protocols.get(proto) or {}).get(block) or {}).get(code) or {}


def describe(protocols, proto, code, block="codes"):
    """Return (spec_name, plain_text_or_None) for one message code."""
    entry = lookup(protocols, proto, code, block)
    return entry.get("name"), entry.get("plain")


def node_name(nodes, ip):
    """Plain-English name for an address, or the bare address if unknown."""
    return nodes.name(ip)


def record_unknown(entries):
    """Append gaps to the learning queue, deduplicated. Returns how many are new."""
    path = KNOWLEDGE / "_unknown.yaml"
    data = _load(path, {"unknown": []})
    queue = data.get("unknown") or []
    seen = {(e.get("protocol"), e.get("code")) for e in queue}
    added = 0
    for entry in entries:
        key = (entry.get("protocol"), entry.get("code"))
        if key in seen:
            continue
        seen.add(key)
        queue.append(entry)
        added += 1
    if not added:
        return 0
    header = []
    for line in path.read_text().splitlines() if path.exists() else []:
        if line.startswith("#") or not line.strip():
            header.append(line)
        else:
            break
    body = yaml.safe_dump({"unknown": queue}, sort_keys=False, allow_unicode=True)
    path.write_text("\n".join(header + [body]) if header else body)
    return added
