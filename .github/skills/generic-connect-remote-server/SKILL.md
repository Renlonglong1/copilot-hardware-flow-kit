---
name: generic-connect-remote-server
description: "Connect to and operate remote servers over SSH, plus Intel lab out-of-band debug channels. One entry point for: (1) interactive SSH into a remote Linux host to run commands, experiments, or test suites end-to-end (with diagnose→fix→re-run troubleshooting); (2) uploading/downloading files via SFTP/SCP; (3) optional encrypted credential vault + IP history so the user doesn't re-type passwords; (4) Intel silicon/BIOS/RAS out-of-band channels — CScripts via PsExec+dflaunch, PythonSV via PsExec (startsrf/startgnr), in-band OS Linux SSH (dmesg/lspci/AER), and BMC Serial-Over-LAN via ipmitool to capture POST across a reboot — including mode=all to fan them out in parallel. Use this skill whenever the user wants to: ssh / 连接 / 登录 a remote Linux server or test machine by IP; run a command, script, experiment, or test on a remote host; upload or copy a file to/from a server; remember / save / reuse a server's credentials or pick from previous IPs; 连接 cscripts / launch cscripts / dflaunch; 连接 pythonsv / startsrf / startgnr / sierraforest / graniterapids; 看 dmesg / lspci / AER / eDPC from the OS; 连接 BMC 串口 / abrir SOL / ipmitool sol activate / capture BIOS POST log across reboot / 'SOL payload already active on another session'; or connect to all of these at once. Triggers: SSH, remote Linux, test machine, server IP, upload file, run remote test, run experiment on target, save password, remember IP, cscripts, pythonsv, BMC, SOL, POST capture, connect all."
argument-hint: "[mode] [ip/host] [user] — ssh | upload | run | cscripts | pythonsv | sol | all"
tools: [execute, read, search]
user-invocable: true
---

# Connect to Remote Server (SSH / SFTP / Lab OOB)

Single entry point for working with remote servers. Most tasks are **interactive SSH into a remote Linux host** to run commands, experiments, or test suites and to move files. A second family of modes reaches **Intel lab out-of-band debug channels** (CScripts, PythonSV, BMC SOL) used during silicon/BIOS/RAS debug.

Pick the **mode** that matches the user's intent and follow the matching section. Interactive connects always use **async terminals** so the session stays alive and follow-up commands go through `send_to_terminal` against the captured terminal ID.

## Mode selector

| User intent | Mode | Where |
|---|---|---|
| ssh into a Linux box / run a command, experiment, or test on a remote host / dmesg / lspci / AER | `ssh` | [1. SSH to remote Linux](#1-ssh-to-remote-linux) |
| upload / download / copy a file to or from a server | `transfer` | [2. File transfer](#2-file-transfer-sftpscp) |
| save / remember / reuse credentials, list previous IPs | `creds` | [3. Credential vault & IP history](#3-credential-vault--ip-history) |
| cscripts / dflaunch / startCscripts.py | `cscripts` | references/lab-connections.md |
| pythonsv / startsrf / startgnr / sierraforest / graniterapids | `pythonsv` | references/lab-connections.md |
| BMC / SOL / ipmitool / capture POST serial across reboot | `sol` | references/lab-connections.md |
| connect to everything at once / 一次起全部 | `all` | references/lab-connections.md |

> **The four lab modes (`cscripts`, `pythonsv`, `sol`, `all`) live in [references/lab-connections.md](references/lab-connections.md).** Read that file when the user asks for any of them — it carries the full PsExec / ipmitool procedures, the shared-XDPA-probe constraints, and the parallel fan-out logic. Keeping them out of this file keeps the common SSH path lean.

---

## 1. SSH to remote Linux

The goal is to get an interactive shell on the target and then *stay in it*. A persistent session preserves environment, working directory, and shell state — which is exactly what makes multi-step experiments and troubleshooting tractable. Repeatedly firing one-off `ssh user@ip "cmd"` calls throws that state away each time and makes quoting/expansion fragile, so prefer one live session and send commands into it.

### Procedure

1. **Resolve host & credentials.** Use what the user supplied. If a password isn't given, check the vault (see [Section 3](#3-credential-vault--ip-history)) — `ssh_manager.py` loads saved creds automatically when `--password` is omitted. If nothing is found and no IP was given, offer the IP history so the user can pick.

2. **Open an async SSH terminal** from local PowerShell:

   ```powershell
   ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL <USER>@<HOST>
   ```

   - Use **async** mode so the session stays alive; capture the returned terminal ID.
   - `UserKnownHostsFile=NUL` is the Windows null device (use `/dev/null` on Linux). This avoids host-key prompts blocking automation on lab machines that get reimaged often.

3. **Send the password** when the prompt appears, via `send_to_terminal` with `waitForOutput=true`. Never echo the password back into summaries or logs.

4. **Wait for the shell prompt**, then send every follow-up command into this same terminal. If you're already logged into the target, run commands locally there — don't open a nested SSH.

### Running commands, experiments, and tests

Work the problem in the live shell rather than scripting blind one-liners:

- **Batch the first diagnostic pass.** Gather the high-value facts (host identity, target state, preconditions) in one compact pass before changing anything.
- **Avoid fail-fast modes** like `set -e` during troubleshooting — they abort the session on the first hiccup and cost you the context you just built up.
- **Prefer interactive execution for complex commands/scripts.** Direct `ssh host "long | complex | string"` invites quoting and `$`-expansion bugs; pasting into the live shell sidesteps them.
- **Diagnose → smallest viable fix → re-run immediately.** Apply the least-risky idempotent fix to the highest-impact blocker, then rerun the failed step at once. If a new blocker surfaces, treat it as the next root cause and iterate.
- **End with explicit evidence** — exit code, observed state, and functional output — so success is verifiable, not assumed.

For a one-off non-interactive command where keeping a session alive adds nothing, `ssh <USER>@<HOST> "<cmd>"` from a throwaway sync terminal is fine.

### Common follow-up commands (in-band Linux debug)

| Goal | Command |
|---|---|
| PCIe topology | `lspci -tv` |
| Specific Root Port | `lspci -vvv -s <BDF>` |
| AER counters | `cat /sys/bus/pci/devices/0000:<BDF>/aer_dev_*` |
| Recent kernel events | `dmesg -T \| tail -100` |
| eDPC / DPC / PCIe events | `dmesg -T \| grep -iE 'dpc\|aer\|pcie'` |
| NVMe enumeration | `lsblk; nvme list` |
| Re-enumerate a PCIe device | `echo 1 > /sys/bus/pci/devices/0000:<BDF>/remove ; echo 1 > /sys/bus/pci/rescan` |

### Notes
- An in-band SSH session **dies the moment the OS or its NIC is impacted** (e.g. eDPC containment on the NIC's own Root Port). For silicon debug that may take down the OS, keep an out-of-band channel (CScripts/PythonSV/SOL — see references/lab-connections.md) open as a backup.
- **`Connection timed out` / `refused` on port 22 is expected** when the target is in POST, in UEFI shell, has its NIC down, or is post-containment. Do NOT retry blindly — report it and confirm host state via BMC SOL or an OOB channel first.

---

## 2. File transfer (SFTP/SCP)

To move files to/from the target, use the bundled `ssh_manager.py`, which wraps paramiko's SFTP and reuses any saved credentials:

```powershell
# Upload local → remote
python scripts/ssh_manager.py upload --ip <HOST> --user <USER> [--password <PASS>] --local <LOCAL_PATH> --remote <REMOTE_PATH>
```

If `--password` is omitted, the script loads it from the encrypted vault. On success it confirms the remote destination path and records the IP in history.

For ad-hoc copies you can also use OpenSSH `scp` directly from PowerShell:

```powershell
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL <LOCAL> <USER>@<HOST>:<REMOTE>
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL <USER>@<HOST>:<REMOTE> <LOCAL>
```

`pscp -pw <PASS> ...` (PuTTY) is a good fallback when you need to pass the password as an argument in a non-interactive context.

---

## 3. Credential vault & IP history

So the user doesn't re-type passwords every session, the skill can persist credentials **encrypted at rest** and remember recently used IPs. This is optional and only kicks in when the user asks to save creds or omits a password that's already stored. The Intel lab modes (`cscripts`/`pythonsv`/`sol`) deliberately do **not** use the vault — see the security note below.

All operations go through [scripts/ssh_manager.py](scripts/ssh_manager.py):

```powershell
# Connect and run a command (loads saved creds if --password omitted)
python scripts/ssh_manager.py connect --ip <IP> --user <USER> [--password <PASS>] --cmd "uname -a"

# Run a test script on the remote host
python scripts/ssh_manager.py run-test --ip <IP> --user <USER> [--password <PASS>] --script <REMOTE_SCRIPT_PATH>

# Save credentials (AES-256-GCM encrypted)
python scripts/ssh_manager.py save-creds --ip <IP> --user <USER> --password <PASS>

# List IP history + saved IPs
python scripts/ssh_manager.py list-ips

# Forget saved credentials for a host
python scripts/ssh_manager.py forget --ip <IP>
```

### Rules
- After a **successful** connection, the IP is recorded in history automatically.
- Save credentials **only** when the user explicitly says "remember password" / "save credentials".
- Credentials are AES-256-GCM encrypted; the key is derived (PBKDF2-SHA256) from the machine hostname + a local random salt in `credentials/.salt`.
- **Never print or log passwords in plain text.** Mask them in any summary.
- The `credentials/` directory must not be committed — remind the user to `.gitignore` it.

### First-run dependencies
Reuse a persistent venv for this skill rather than reinstalling each run:

```powershell
python -m venv C:/Users/<you>/.copilot/skills/os-connect-remote-server/.venv
C:/Users/<you>/.copilot/skills/os-connect-remote-server/.venv/Scripts/python.exe -m pip install paramiko cryptography
```

---

## Global rules (all modes)

- **Always `mode=async`** for the initial interactive connect (SSH / PsExec). Capture the terminal ID and reuse it via `send_to_terminal` for follow-ups — don't reconnect unless the session died or you're targeting a different host.
- **Reuse one live session** for a given host instead of repeated one-off SSH; it keeps environment and working directory consistent and makes complex commands reliable.
- **Never echo or commit secrets.** Mask passwords as `<PASS>` / `<BMC_PASS>` etc. in anything you write back — summaries, logs, HSD/Jira tickets.
- **Ask once for missing required arguments** when the user clearly invokes a mode but omits host/user/password/path. Don't invent values or reuse another context's defaults.
- **Don't retry blindly.** A timeout often means the target is intentionally in a state where SSH is down (POST, UEFI, containment). Report it and confirm state through another channel.
- **Parallel sessions are fine.** OS SSH, BMC SOL, and PsExec CScripts/PythonSV can coexist against the same target — don't kill one to start another unless asked.

## References
- [references/lab-connections.md](references/lab-connections.md) — CScripts/PythonSV via PsExec, BMC SOL via ipmitool (incl. POST capture across reboot), and the `all` parallel fan-out, with shared-probe and SOL constraints.
- [scripts/ssh_manager.py](scripts/ssh_manager.py) — SSH/SFTP CLI (connect, upload, run-test, save-creds, list-ips, forget).
- [scripts/credential_store.py](scripts/credential_store.py) — encrypt/decrypt the credential vault + IP history.
