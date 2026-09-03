# Lab profiles

One file per lab, mapping addresses to the equipment in
`knowledge/topology.yaml`. Nothing in here is committed except this README.

## Where to put yours

**Outside the repository, recommended:**

    mkdir -p ~/.config/pcap-explainer/labs
    cp knowledge/addresses.example.yaml ~/.config/pcap-explainer/labs/node-lab-1.yaml
    export PCAP_LAB=node-lab-1

**Or in this directory**, if you would rather keep it with the project:

    cp knowledge/addresses.example.yaml labs/node-lab-1.yaml
    export PCAP_LAB=node-lab-1

Both work. Outside the tree is safer: `.gitignore` stops `git add -A`, but it
does not stop `git add -f`, a colleague tarring the directory, or `git clean
-xdf` deleting the only copy of a profile you spent an afternoon writing.

## Choosing one

In order, first hit wins:

1. `--nodes PATH` on `survey.sh` and `3_render.py`
2. `$PCAP_NODES`, a path
3. `$PCAP_LAB`, a name, looked up in `~/.config/pcap-explainer/labs/` then `labs/`
4. `labs/default.yaml`
5. `knowledge/nodes.yaml`, the committed example

If `$PCAP_LAB` is set and no profile matches it, the run stops. It does not
fall back to the example: naming lab-2's equipment with lab-1's numbering is
the failure this whole arrangement exists to prevent, and it would not be
visible in the finished report.

## What not to put in a report

The profile keeps names out of the confidential half, but a rendered report
still prints addresses next to them. Pass `--redact-addresses` to
`3_render.py` for anything leaving your machine.
