# Running this on Windows

The pipeline itself is portable - the four Python stages use no Unix-only
calls. Three things get in the way on Windows, and this page deals with each:

- Wireshark installs `tshark` and `capinfos` somewhere that is not on `PATH`.
- Git Bash has no `python3`, only `python`.
- A CRLF checkout breaks the shell scripts and every golden-report test.

Pick one of the two routes below. If you already use WSL, use WSL and the
Linux instructions in the README apply word for word. Otherwise use Git Bash,
which keeps your captures where Windows put them.

## Route A - Git Bash

### 1. Python

```powershell
winget install --id Python.Python.3.12
```

Or the installer from python.org, with **Add python.exe to PATH** ticked.
Then, in a new terminal:

```powershell
python --version        # 3.9 or newer
python -m pip install pyyaml
```

If `python` opens the Microsoft Store instead of running, turn off the stub:
**Settings > Apps > Advanced app settings > App execution aliases**, and
switch off the `python.exe` and `python3.exe` entries.

A virtual environment works too, and `.venv/` is already gitignored:

```bash
python -m venv .venv
source .venv/Scripts/activate    # in Git Bash; PowerShell: .venv\Scripts\Activate.ps1
pip install pyyaml
```

### 2. Wireshark

```powershell
winget install --id WiresharkFoundation.Wireshark
```

Or download it from <https://www.wireshark.org/download.html>. If winget does
not recognise the id, `winget search wireshark` will show the current one.

The installer offers **Npcap**. That is only needed to capture live traffic.
Reading a `.pcap` file, which is all this project does, works without it.

Now put the command line tools on `PATH`. The installer does not:

1. **Settings > System > About > Advanced system settings**
2. **Environment Variables > Path > Edit > New**
3. Add `C:\Program Files\Wireshark`
4. Close every terminal and open a new one - `PATH` is read at startup.

```bash
tshark --version
capinfos --version
```

Both live in that one folder. If `tshark` is found and `capinfos` is not,
`PATH` is pointing at a shim rather than the Wireshark folder.

### 3. Git Bash and the clone

Git Bash ships with **Git for Windows** (<https://git-scm.com/download/win>).
It provides the `bash`, `grep`, `sort`, `tr`, `diff` and `cmp` that
`scripts/survey.sh` and `tests/run_tests.sh` use, so nothing else is needed.

```bash
git clone <this repo>
cd pcap-explainer
```

The repo's `.gitattributes` forces an LF checkout, so a fresh clone is
correct whatever your `core.autocrlf` is set to. A clone made **before**
that file existed may have CRLF files; renormalise it once:

```bash
git config core.autocrlf input
git rm --cached -r .
git reset --hard
```

### 4. Run it

```bash
bash scripts/survey.sh /c/Users/you/Downloads/capture.pcap
python scripts/1_extract.py /c/Users/you/Downloads/capture.pcap out/events.csv
python scripts/2_sessionize.py out/events.csv out/flows.json
python scripts/3_render.py out/flows.json out/report.md --title "the lab core network"
```

Git Bash maps `C:\` to `/c`, so drag a file into the window and swap the
backslashes, or quote the Windows path.

The shell scripts look for `python3` first and fall back to `python`, so you
do not need to create an alias. To force a particular interpreter - a venv
that is not activated, say - set `PYTHON`:

```bash
PYTHON=./.venv/Scripts/python.exe bash tests/run_tests.sh
```

## Route B - WSL

```powershell
wsl --install -d Ubuntu
```

Then inside Ubuntu, exactly as the README says:

```bash
sudo apt install tshark python3-yaml
```

The tshark package asks whether non-superusers should be allowed to capture
packets. Answer **No**; reading a file does not need it.

Clone into the Linux home directory (`~/`), not into `/mnt/c/`. Captures on
the Windows side are readable at `/mnt/c/Users/you/Downloads/capture.pcap`,
but a repo kept there is slow and picks up Windows line endings.

## Checking it worked

```bash
bash tests/run_tests.sh
```

With tshark on `PATH` that is `8 passed, 0 failed`. Without it you get a
failure on *code tables match the tshark dissector* and a skip for the
capture-reading tests - that check compares the knowledge base against the
dissector, so it cannot run without one.

## When it does not work

| What you see | What it is |
|---|---|
| `tshark: command not found` | `PATH` not updated, or the terminal predates the change. Open a new one. |
| `no Python 3.9+ on PATH (tried python3, python)` | Python is not on `PATH`, or the Store stub is intercepting it. See step 1. |
| `$'\r': command not found`, or a syntax error on a line that looks fine | CRLF checkout. Renormalise as in step 3. |
| Every golden-report test fails with every line differing | Same thing - CRLF. |
| `pip` refuses with *externally-managed-environment* | Use the venv in step 1. |
| `tshark` works, `capinfos` does not | `PATH` entry is not the Wireshark folder itself. |
