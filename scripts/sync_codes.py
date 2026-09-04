#!/usr/bin/env python3
"""Refresh the numeric code tables in knowledge/protocols/*.yaml from tshark.

The spec name of every procedure / message type comes from the Wireshark
dissector's own value tables (`tshark -G values`), never from memory. This
script only touches the `name` field of each code and adds codes that are
missing. Hand-written `plain` text is never overwritten.

Usage: python scripts/sync_codes.py [--check]
       --check exits 1 if any file would change (for tests/CI).
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "knowledge" / "protocols"

# protocol file -> the YAML blocks it carries, and the tshark field whose
# value table fills each one.
BLOCKS = {
    "ngap": [("codes", "ngap.procedureCode")],
    "f1ap": [("codes", "f1ap.procedureCode")],
    "pfcp": [("codes", "pfcp.msg_type"), ("causes", "pfcp.cause")],
    "gtp": [("codes", "gtp.message")],
    "sctp": [("codes", "sctp.chunk_type")],
}


def dissector_values(field):
    """Return {code:int -> name:str} from the tshark dissector value table."""
    try:
        out = subprocess.run(
            ["tshark", "-G", "values"], capture_output=True, text=True, check=True
        ).stdout
    except FileNotFoundError:
        sys.exit(
            "tshark not found on PATH. Install wireshark-cli / tshark first.\n"
            "On Windows, install Wireshark and add its folder to PATH "
            "(see windows-setup.md)."
        )
    values = {}
    for line in out.splitlines():
        parts = line.split("\t")
        # V <field> <value> <description>
        if len(parts) >= 4 and parts[0] == "V" and parts[1] == field:
            raw = parts[2].strip()
            try:
                code = int(raw, 16) if raw.lower().startswith("0x") else int(raw)
            except ValueError:
                continue
            values[code] = parts[3].strip()
    return values


def parse_block(text, block):
    """Read one `<block>:` mapping as {code: {key: raw_value_line}}.

    Deliberately line-based rather than a YAML round-trip so that comments and
    ordering in the hand-edited files survive untouched.
    """
    codes, current = {}, None
    inside = False
    for line in text.splitlines():
        if re.match(rf"^{block}:\s*$", line):
            inside = True
            continue
        if inside and line and not line.startswith(" ") and not line.startswith("#"):
            inside = False
        if not inside:
            continue
        m = re.match(r"^  (\d+):\s*$", line)
        if m:
            current = int(m.group(1))
            codes[current] = {}
            continue
        m = re.match(r"^    (\w+):\s*(.*)$", line)
        if m and current is not None:
            codes[current][m.group(1)] = m.group(2)
    return codes


def yaml_str(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(header, blocks):
    lines = [header.rstrip("\n")]
    for block, codes in blocks:
        lines.append(f"{block}:")
        for code in sorted(codes):
            entry = codes[code]
            lines.append(f"  {code}:")
            lines.append(f"    name: {entry['name']}")
            lines.append(f"    plain: {entry.get('plain', 'null')}")
            for key in sorted(k for k in entry if k not in ("name", "plain")):
                lines.append(f"    {key}: {entry[key]}")
    return "\n".join(lines) + "\n"


def sync(proto, blocks, check):
    path = PROTO_DIR / f"{proto}.yaml"
    if not path.exists():
        print(f"skip {proto}: {path} does not exist")
        return False
    text = path.read_text()
    header = text.split(f"\n{blocks[0][0]}:")[0] + "\n"

    rendered, added, renamed, missing, total = [], 0, 0, 0, 0
    for block, field in blocks:
        existing = parse_block(text, block)
        live = dissector_values(field)
        if not live:
            sys.exit(f"tshark reported no value table for {field}")
        merged = {}
        for code, name in live.items():
            prev = existing.get(code, {})
            if not prev:
                added += 1
            elif prev.get("name", "").strip('"') != name:
                renamed += 1
            merged[code] = dict(prev)
            merged[code]["name"] = yaml_str(name)
            merged[code].setdefault("plain", "null")
        # codes the local dissector does not know about are kept, not dropped
        for code, prev in existing.items():
            merged.setdefault(code, prev)
        missing += sum(1 for c in merged.values() if c.get("plain", "null") == "null")
        total += len(merged)
        rendered.append((block, merged))

    new_text = render(header, rendered)
    changed = new_text != text
    if changed and not check:
        path.write_text(new_text)
    if not changed:
        status = "unchanged"
    else:
        status = "would change" if check else "updated"
    print(
        f"{proto}: {status} - {total} entries "
        f"({added} added, {renamed} renamed, {missing} without plain text)"
    )
    return changed


def main():
    check = "--check" in sys.argv
    changed = [sync(p, b, check) for p, b in BLOCKS.items()]
    if check and any(changed):
        sys.exit("code tables are stale - run: python scripts/sync_codes.py")


if __name__ == "__main__":
    main()
