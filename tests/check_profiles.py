#!/usr/bin/env python3
"""The per-lab node profiles: lookup, and the ways they are meant to fail.

Most of this is about failing loudly. A profile that quietly drops a line, or
quietly falls back to another lab's numbering, produces a report that is wrong
in the one way nobody can see afterwards - the equipment names look fine.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import nodes as node_lib  # noqa: E402

problems = []


def check(name, condition, detail=""):
    if not condition:
        problems.append(f"{name}{': ' + detail if detail else ''}")


def write(directory, name, text):
    path = Path(directory) / name
    path.write_text(text)
    return path


TOPOLOGY = {
    "gnb-cu": {"name": "Base station brain", "role": "radio", "note": "n",
               "interfaces": {"f1": "antenna link", "n3": "traffic link"}},
    "upf": {"name": "Traffic forwarder", "role": "forwarder", "note": "n",
            "interfaces": {"n3": ""}},
    "subscriber": {"name": "A subscriber device", "role": "subscriber"},
}

GOOD = """
lab: test-lab
addresses:
  10.1.4.1: gnb-cu.f1
  10.1.3.2: gnb-cu.n3
  10.1.3.1: upf.n3
  1.1.1.7: subscriber
  1.1.1.0/24: subscriber
"""

with tempfile.TemporaryDirectory() as work:
    table = node_lib.read_profile(write(work, "good.yaml", GOOD), TOPOLOGY)

    check("an interface label is appended to the name",
          table.name("10.1.4.1") == "Base station brain (antenna link)",
          table.name("10.1.4.1"))
    check("one box on two legs reads as two rows",
          table.name("10.1.3.2") == "Base station brain (traffic link)",
          table.name("10.1.3.2"))
    check("an empty interface label leaves the bare name",
          table.name("10.1.3.1") == "Traffic forwarder", table.name("10.1.3.1"))
    check("a subnet names every address in it",
          table.name("1.1.1.99") == "A subscriber device", table.name("1.1.1.99"))
    check("an exact address beats the subnet it sits in",
          table.get("1.1.1.7") is not None
          and table.get("1.1.1.7")["role"] == "subscriber")
    check("an address outside the profile stays a bare number",
          table.name("192.0.2.1") == "192.0.2.1", table.name("192.0.2.1"))
    check("the note comes from the shared topology",
          table.get("10.1.3.1")["note"] == "n")
    check("the profile reports where it came from",
          table.where == "good.yaml", table.where)

    # A more specific subnet wins over a broader one, so a container network
    # can be named as a whole while one container inside it is named exactly.
    layered = node_lib.read_profile(write(work, "layered.yaml", """
addresses:
  172.20.0.0/16: subscriber
  172.20.5.0/24: upf.n3
"""), TOPOLOGY)
    check("the most specific subnet wins",
          layered.name("172.20.5.9") == "Traffic forwarder",
          layered.name("172.20.5.9"))

    for name, text, because in [
        ("unknown-node.yaml", "addresses:\n  10.0.0.1: nonsense\n",
         "equipment that is not in the topology"),
        ("unknown-interface.yaml", "addresses:\n  10.0.0.1: upf.n99\n",
         "an interface the equipment does not have"),
        ("bad-address.yaml", "addresses:\n  not-an-ip: upf.n3\n",
         "an address that is not an address"),
        ("empty.yaml", "lab: nothing\n", "neither addresses nor nodes"),
    ]:
        try:
            node_lib.read_profile(write(work, name, text), TOPOLOGY)
            problems.append(f"a profile with {because} was accepted")
        except node_lib.ProfileError:
            pass

    # Choosing a profile: explicit beats environment, and a named lab that does
    # not exist stops the run rather than falling back to another lab's numbers.
    saved = {key: os.environ.get(key) for key in ("PCAP_NODES", "PCAP_LAB")}
    saved_labs, saved_config = node_lib.LABS, node_lib.CONFIG_LABS
    try:
        node_lib.LABS = Path(work) / "labs"
        node_lib.CONFIG_LABS = Path(work) / "config"
        node_lib.LABS.mkdir()
        node_lib.CONFIG_LABS.mkdir()
        write(node_lib.LABS, "node-lab-2.yaml", GOOD)

        os.environ["PCAP_NODES"] = str(Path(work) / "good.yaml")
        os.environ.pop("PCAP_LAB", None)
        check("PCAP_NODES is honoured",
              node_lib.profile_path() == Path(work) / "good.yaml")
        check("an explicit path beats PCAP_NODES",
              node_lib.profile_path(str(Path(work) / "layered.yaml"))
              == Path(work) / "layered.yaml")

        os.environ.pop("PCAP_NODES")
        os.environ["PCAP_LAB"] = "node-lab-2"
        check("PCAP_LAB is looked up in the search path",
              node_lib.profile_path() == node_lib.LABS / "node-lab-2.yaml")

        write(node_lib.CONFIG_LABS, "node-lab-2.yaml", GOOD)
        check("a profile outside the tree wins over one inside it",
              node_lib.profile_path() == node_lib.CONFIG_LABS / "node-lab-2.yaml")

        os.environ["PCAP_LAB"] = "node-lab-404"
        try:
            node_lib.profile_path()
            problems.append("a missing PCAP_LAB fell back instead of stopping")
        except node_lib.ProfileError:
            pass

        os.environ.pop("PCAP_NODES", None)
        os.environ.pop("PCAP_LAB", None)
        check("with nothing chosen, the committed example is used",
              node_lib.profile_path() == node_lib.FIXTURE)
    finally:
        node_lib.LABS, node_lib.CONFIG_LABS = saved_labs, saved_config
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
