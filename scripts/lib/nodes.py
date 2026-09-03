"""Who is who on the network, resolved per lab.

Split deliberately in two:

  knowledge/topology.yaml   the equipment and its plain-English names -
                            committed, shared by every lab, no addresses
  a lab profile             address -> equipment - local to one machine,
                            never committed

Every lab runs the same equipment, so only the numbering changes between them.
Keeping the prose in the shared half means describing a node once benefits
every lab, and the confidential half stays a bare list of addresses.

The other reason for the split is correctness. Two labs can reuse the same
address for different equipment, so one merged table would not just be untidy,
it would name things wrongly with no sign that anything was off. Loading
exactly one profile, chosen on purpose, is what stops that.
"""
import ipaddress
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE = ROOT / "knowledge"
TOPOLOGY = KNOWLEDGE / "topology.yaml"
FIXTURE = KNOWLEDGE / "nodes.yaml"
LABS = ROOT / "labs"
CONFIG_LABS = Path(
    os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
) / "pcap-explainer" / "labs"

ROLES = ("radio", "core", "forwarder", "subscriber", "other")


class ProfileError(Exception):
    """The profile is unusable. Always fatal: a half-understood address map
    produces a confidently wrong report, which is worse than no report."""


def _load(path):
    return yaml.safe_load(Path(path).read_text()) or {}


class NodeTable:
    """Address -> {name, role, note}, by exact match or by subnet.

    Subnets matter because a lab hands out a whole range to phones and another
    to the containers making up the core; the most specific match wins so a
    named address inside a range still gets its own name.
    """

    def __init__(self, entries=None, networks=None, source=None, origin=""):
        self._entries = dict(entries or {})
        # longest prefix first, so 10.1.3.1/32 beats 10.1.0.0/16
        self._networks = sorted(networks or [],
                                key=lambda pair: pair[0].prefixlen,
                                reverse=True)
        self.source = source
        self.origin = origin

    @property
    def where(self):
        """How to name this profile in a finished report: relative to the
        project if it lives there, otherwise the bare filename. Never an
        absolute path - that would put someone's home directory in a document
        meant to be forwarded, and would differ between machines."""
        if self.source is None:
            return "the lab node profile"
        try:
            return str(Path(self.source).resolve().relative_to(ROOT))
        except ValueError:
            return Path(self.source).name

    def get(self, address):
        entry = self._entries.get(address)
        if entry is not None:
            return entry
        if not self._networks:
            return None
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return None
        for network, entry in self._networks:
            if parsed in network:
                return entry
        return None

    def name(self, address):
        if not address:
            return "unknown"
        return (self.get(address) or {}).get("name") or address

    def __len__(self):
        return len(self._entries) + len(self._networks)

    def redacted(self):
        """The same table, but an address it cannot name becomes a numbered
        placeholder instead of the address itself. For a report leaving the
        machine: an unnamed node is exactly the one whose bare number would
        otherwise be printed."""
        return RedactedNodeTable(self)


class RedactedNodeTable:
    """Wraps a NodeTable so no address can reach the text through it.

    Deliberately a wrapper rather than a flag on the renderer: every table,
    line and sentence in a report asks the node table for names, so covering
    them one at a time is how one of them gets missed.
    """

    def __init__(self, table):
        self._table = table
        self._placeholders = {}
        self.source = table.source
        self.origin = table.origin
        # deliberately not table.where: a profile filename is usually the lab
        # name, and this is the copy that gets forwarded
        self.where = "the lab node profile"

    def get(self, address):
        return self._table.get(address)

    def name(self, address):
        if not address:
            return "unknown"
        entry = self._table.get(address)
        if entry and entry.get("name"):
            return entry["name"]
        if address not in self._placeholders:
            self._placeholders[address] = (
                f"Unnamed equipment {len(self._placeholders) + 1}")
        return self._placeholders[address]

    def __len__(self):
        return len(self._table)


def load_topology(path=TOPOLOGY):
    """{id: {name, role, note, interfaces}} - the shared, committed half."""
    return _load(path).get("nodes") or {}


def _describe(node, interface, node_id):
    """One report-ready entry for a node reached on one of its interfaces."""
    name = node.get("name") or node_id
    label = (node.get("interfaces") or {}).get(interface)
    if label:
        name = f"{name} ({label})"
    return {"name": name, "role": node.get("role") or "other",
            "note": node.get("note") or ""}


def _from_topology(profile, topology, where):
    """Build a table from a lab profile: address -> node id, or node.interface.

    Anything that does not line up with the topology is an error rather than a
    skipped line - a silently dropped address comes out of the report as a bare
    number at best, and as the wrong equipment at worst.
    """
    entries, networks = {}, []
    for address, target in (profile.get("addresses") or {}).items():
        address = str(address).strip()
        node_id, _, interface = str(target or "").strip().partition(".")
        node = topology.get(node_id)
        if not node:
            raise ProfileError(
                f"{where}: {address} points at {node_id!r}, which is not in "
                f"{TOPOLOGY.relative_to(ROOT)}. Known equipment: "
                f"{', '.join(sorted(topology))}.")
        if interface and interface not in (node.get("interfaces") or {}):
            known = ", ".join(sorted(node.get("interfaces") or {})) or "none"
            raise ProfileError(
                f"{where}: {address} points at interface {interface!r} of "
                f"{node_id!r}, which has no such interface. It has: {known}.")
        entry = _describe(node, interface, node_id)
        if "/" in address:
            try:
                networks.append((ipaddress.ip_network(address, strict=False), entry))
            except ValueError as error:
                raise ProfileError(f"{where}: {address} is not a valid subnet: {error}")
        else:
            try:
                ipaddress.ip_address(address)
            except ValueError as error:
                raise ProfileError(f"{where}: {address} is not a valid address: {error}")
            entries[address] = entry
    return entries, networks


def _from_flat(profile, where):
    """Build a table from the older flat format, where each address carries its
    own name. Still supported so an existing knowledge/nodes.yaml keeps working
    - but it cannot be shared between labs, which is the point of the split."""
    entries = {}
    for address, entry in (profile.get("nodes") or {}).items():
        entry = entry or {}
        if not entry.get("name"):
            raise ProfileError(f"{where}: {address} has no name.")
        entries[str(address).strip()] = {
            "name": entry["name"],
            "role": entry.get("role") or "other",
            "note": entry.get("note") or "",
        }
    return entries, []


def read_profile(path, topology=None):
    """Load one profile file, in whichever of the two formats it uses."""
    path = Path(path)
    if not path.exists():
        raise ProfileError(f"node profile not found: {path}")
    where = path
    try:
        data = _load(path)
    except yaml.YAMLError as error:
        raise ProfileError(f"{where}: not valid YAML: {error}")

    if "addresses" in data:
        topology = load_topology() if topology is None else topology
        entries, networks = _from_topology(data, topology, where)
        lab = data.get("lab") or path.stem
        origin = f"lab {lab!r} ({path})"
    elif "nodes" in data:
        entries, networks = _from_flat(data, where)
        origin = f"flat node list ({path})"
    else:
        raise ProfileError(
            f"{where}: expected a top-level 'addresses:' (a lab profile) or "
            f"'nodes:' (the older flat format).")

    for address, entry in entries.items():
        if entry["role"] not in ROLES:
            raise ProfileError(f"{where}: {address} has role "
                               f"{entry['role']!r}; expected one of "
                               f"{', '.join(ROLES)}.")
    return NodeTable(entries, networks, source=path, origin=origin)


def profile_path(explicit=None, lab=None):
    """Which profile to load, and nothing clever about it.

    In order: an explicit path, then PCAP_NODES, then a lab named by PCAP_LAB
    looked up in the search path, then the committed example.

    Deliberately not auto-detected from the capture's addresses: labs reuse
    ranges, so guessing here would reintroduce exactly the mislabelling this
    module exists to prevent.
    """
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise ProfileError(f"--nodes {explicit}: no such file.")
        return path

    from_env = os.environ.get("PCAP_NODES")
    if from_env:
        path = Path(from_env).expanduser()
        if not path.exists():
            raise ProfileError(f"PCAP_NODES={from_env}: no such file.")
        return path

    lab = lab or os.environ.get("PCAP_LAB")
    if lab:
        searched = [directory / f"{lab}.yaml"
                    for directory in (CONFIG_LABS, LABS)]
        for path in searched:
            if path.exists():
                return path
        raise ProfileError(
            f"PCAP_LAB={lab} but no profile for it. Looked in:\n" +
            "\n".join(f"  {path}" for path in searched) +
            f"\nCopy {(KNOWLEDGE / 'addresses.example.yaml').relative_to(ROOT)} "
            f"to the first of those and fill in this lab's addresses.")

    default = LABS / "default.yaml"
    if default.exists():
        return default
    return FIXTURE


def load(explicit=None, lab=None, topology=None):
    """The node table for this run. Raises ProfileError, which callers should
    print and exit on rather than carrying on with half a table."""
    return read_profile(profile_path(explicit, lab), topology=topology)


def add_argument(parser):
    """The --nodes flag, worded the same wherever it appears."""
    parser.add_argument(
        "--nodes", metavar="PATH",
        help="lab node profile to use. Defaults to $PCAP_NODES, then the lab "
             "named by $PCAP_LAB, then labs/default.yaml, then the committed "
             "example.")
