#!/usr/bin/env python3
"""No address from a local lab profile appears in anything git tracks.

A rule that lives only in a README stops being true within a month. This is
the part that actually holds: it reads whatever lab profiles exist on this
machine and checks that none of their numbering has reached a tracked file -
including the checked-in captures, where an address is four bytes rather than
text and no amount of reading the diff would catch it.

Passes quietly when there is no local profile, which is the normal state on a
fresh clone and in CI.
"""
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import nodes as node_lib  # noqa: E402

ROOT = node_lib.ROOT
IPV4 = re.compile(rb"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

# Committed on purpose: the example people copy, and the fixture the tests
# render against. Both are made-up numbering.
PUBLIC = {node_lib.FIXTURE.resolve(),
          (node_lib.KNOWLEDGE / "addresses.example.yaml").resolve()}


def local_profiles():
    found = []
    for directory in (node_lib.LABS, node_lib.CONFIG_LABS):
        if directory.is_dir():
            found += sorted(directory.glob("*.yaml"))
    local = node_lib.KNOWLEDGE / "nodes.local.yaml"
    if local.exists():
        found.append(local)
    return [path for path in found if path.resolve() not in PUBLIC]


def secrets(paths):
    """Every address and subnet the local profiles mention."""
    exact, networks = set(), []
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception as error:  # a broken profile is check_profiles' job
            print(f"  (skipped {path}: {error})")
            continue
        for address in (data.get("addresses") or data.get("nodes") or {}):
            address = str(address).strip()
            try:
                if "/" in address:
                    networks.append(ipaddress.ip_network(address, strict=False))
                else:
                    exact.add(ipaddress.ip_address(address))
            except ValueError:
                continue
    return exact, networks


def tracked_files():
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    return [ROOT / name.decode() for name in listing.split(b"\0") if name]


def main():
    profiles = local_profiles()
    if not profiles:
        print("no local lab profile on this machine, nothing to leak")
        return 0

    exact, networks = secrets(profiles)
    if not exact and not networks:
        print("local lab profiles name no addresses")
        return 0

    def is_secret(address):
        return address in exact or any(address in net for net in networks)

    # Small ranges are worth expanding for the binary sweep, so a committed
    # capture from a lab subnet is caught too. Large ones are left to the text
    # check rather than enumerating millions of addresses.
    binary_watch = set(exact)
    for network in networks:
        if network.num_addresses <= 4096:
            binary_watch.update(network.hosts())

    leaks = []
    for path in tracked_files():
        if not path.is_file():
            continue
        if path.resolve() in {profile.resolve() for profile in profiles}:
            leaks.append(f"{path.relative_to(ROOT)} is a lab profile and is tracked by git")
            continue
        blob = path.read_bytes()
        for match in set(IPV4.findall(blob)):
            try:
                address = ipaddress.ip_address(match.decode())
            except ValueError:
                continue
            if is_secret(address):
                leaks.append(f"{path.relative_to(ROOT)} contains {address}")
        # captures carry addresses as four raw bytes, not as text
        for address in binary_watch:
            if address.packed in blob:
                leaks.append(f"{path.relative_to(ROOT)} contains {address} "
                             f"in binary form")

    if leaks:
        print(f"lab addresses from {len(profiles)} local profile(s) reached "
              f"tracked files:")
        for leak in sorted(set(leaks)):
            print(f"  {leak}")
        print("\nA tracked file must not carry a real lab's numbering. Move the "
              "value out, or use made-up addresses for anything committed.")
        return 1

    print(f"checked {len(profiles)} local profile(s); no lab addresses in "
          f"tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
