# Lab Out-of-Band Connections (CScripts / PythonSV / BMC SOL)

Credential-free procedures for the Intel silicon/BIOS/RAS out-of-band debug channels. Read this when the user asks for `cscripts`, `pythonsv`, `sol`, or `all`. Every host/user/password/path below is a **placeholder** — require the caller to supply them; never reuse defaults from another skill or prior session, and never echo secrets into shared logs/commits/tickets.

`cscripts` and `pythonsv` reach the **OOB host** that owns the XDP/JTAG probe. `sol` reaches the **BMC**. The in-band OS SSH path is in the main SKILL.md (Section 1). All of these can be open in parallel terminals.

## Required arguments per mode (no defaults)

| Mode | Required arguments |
|---|---|
| `cscripts` | `<OOB_HOST>`, optional `<OOB_USER>`/`<OOB_PASS>` (skip when pass-through admin), `<PSEXEC>` path, `<CS_ROOT>`, `<CS_LAUNCHER>` |
| `pythonsv` | `<OOB_HOST>`, optional `<OOB_USER>`/`<OOB_PASS>` (skip when pass-through admin), `<PSEXEC>` path, `<PYSV_ROOT>`, `<PYSV_LAUNCHER>` |
| `sol` | `<BMC_HOST>`, `<BMC_SSH_USER>`, `<BMC_SSH_PASS>`, `<IPMI_USER>`, `<IPMI_PASS>` (often same as BMC SSH creds — confirm), optional `<IPMI_CIPHER>` (default `17`) |
| `all` | Union of every field for the requested modes. Skip (and record the reason for) any mode missing creds rather than blocking the others. |

If the user invokes a mode but omits required arguments, ask **once** for the missing fields.

## PsExec auth-mode selection (cscripts + pythonsv)

| Auth mode | When | Command form |
|---|---|---|
| **Pass-through (preferred)** | The local Windows account running VS Code is already admin on `<OOB_HOST>`. No user/pass on the command line. | `.\PsExec.exe \\<OOB_HOST> -h cmd` |
| **Explicit credentials** | Different account, or a local account on `<OOB_HOST>`. | `.\PsExec.exe \\<OOB_HOST> -u <OOB_USER> -p <OOB_PASS> -h cmd` |

Try pass-through first when the user implies they have admin and didn't supply creds — it keeps plaintext passwords off the command line. If it fails with `Access is denied` / `Couldn't access <OOB_HOST>`, fall back to explicit credentials and ask for them.

---

## 1. CScripts via PsExec

Open a PsExec interactive cmd to `<OOB_HOST>`, then `dflaunch` the launcher.

1. **Launch PsExec (async)** — capture the terminal ID; all follow-ups go via `send_to_terminal`.

   ```powershell
   cd "<PSEXEC dir>" ; .\PsExec.exe \\<OOB_HOST> -h cmd          # pass-through
   cd "<PSEXEC dir>" ; .\PsExec.exe \\<OOB_HOST> -u <OOB_USER> -p <OOB_PASS> -h cmd   # explicit
   ```

2. **Wait for `C:\Windows\System32>`.** PsExec prints "Starting PSEXESVC service…" first; poll with `get_terminal_output` or send `echo connected` until the cmd prompt returns.

3. **Locate the launcher** (`<CS_ROOT>\cscripts\<CS_LAUNCHER>`, e.g. `startCscripts.py`). `dir cscripts\*.py` if unsure.

4. **Launch CScripts:**

   ```cmd
   cd /d <CS_ROOT> && dflaunch cscripts\<CS_LAUNCHER>
   ```

   Expected banner varies by platform: `Target System: <PLATFORM>`, `PythonSv running in interactive mode`, `Using XDPA as the OpenIPC connection.`, eventually IPython `In [1]:`.

5. **Wait for the IPython prompt** before sending commands. Init can take 60–120 s (loads SOC views, taps, patches).

### Notes
- `dflaunch` is the Intel SWTools wrapper that activates Python 3.10 + OpenIPC; do NOT call `python <CS_LAUNCHER>` directly.
- A harmless `IPC_PATH` warning before launch — ignore.
- `&&` works inside the remote `cmd`, NOT in local PowerShell — keep `&&` only in post-PsExec commands.
- **Shared XDPA probe with PythonSV** — see the constraints in Section 4.

---

## 2. PythonSV via PsExec

Open a PsExec interactive cmd to `<OOB_HOST>`, then run the project's start script.

### Typical project → launcher mapping (examples — confirm with `dir start*.py`)

| Project | Typical `<PYSV_ROOT>` | `<PYSV_LAUNCHER>` |
|---|---|---|
| sierraforest | `C:\pythonsv\sierraforest` | `startsrf.py` |
| graniterapids | `C:\pythonsv\graniterapids` | `startgnr.py` |
| birchstream | `C:\pythonsv\birchstream` | `startbhs.py` (verify) |
| eaglestream | `C:\pythonsv\eaglestream` | `starteagle.py` (verify) |

1. **Launch PsExec (async)** — same as CScripts step 1 (prefer pass-through).
2. **Wait for `C:\Windows\System32>`** (`echo connected` confirms).
3. **Launch the project script:**

   ```cmd
   cd <PYSV_ROOT> && python <PYSV_LAUNCHER>
   ```

4. **"Use previous config?" prompt** — `startsrf.py`/`startgnr.py` auto-assume `yes` after a short delay; do nothing unless the user wants to change config (then send `no` and answer the wizard).
5. **Wait for** `PythonSv running in interactive mode` + the `Running <project>` banner. Then it accepts PythonSV commands (e.g. `sv.socket0.<...>`). Init ~60–120 s.

### Notes
- If PsExec hangs at "Starting PSEXESVC service…", the host may be unreachable or the admin share blocked — surface the error instead of retrying blindly.
- **Shared XDPA probe with CScripts** — see Section 4.

---

## 3. BMC SOL via SSH + ipmitool

Open a host serial console by SSH'ing into the BMC, then running `ipmitool ... sol activate` from the BMC itself (loopback over the BMC IPMI stack). The standard way to watch UEFI/boot/Linux serial without a physical cable, e.g. to capture POST codes, debug boot hangs, or scroll a kernel panic.

### 3a. Open SOL

1. **Async SSH to the BMC:**

   ```powershell
   ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL <BMC_SSH_USER>@<BMC_HOST>
   ```

2. **Send the BMC password** when prompted; wait for the BMC shell prompt.
3. **Enable + activate SOL in one shot** (idempotent):

   ```sh
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus sol set enabled true && \
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus sol activate
   ```

   `-H` is the BMC's own LAN IP (loopback over IPMI), not 127.0.0.1. Success marker: `[SOL Session operational.  Use ~? for help]` then live host serial.

   **Once SOL is active, every keystroke goes to the host serial.** To run any BMC-shell command (power cycle, `sol deactivate` from outside), open a **second** BMC SSH session — never reuse the SOL one.

4. **If "SOL payload already active on another session"** — force-release then re-activate (safe; no host reboot):

   ```sh
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus sol deactivate
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus sol activate
   ```

### In-session controls (tilde escapes — must follow a newline)

| Keys | Effect |
|---|---|
| `~.` | Terminate SOL session (return to BMC shell) |
| `~B` | Send serial BREAK (SysRq) |
| `~?` | ipmitool SOL help |
| `~~` | Send a literal tilde |

**Pitfall:** under automation with no real TTY, `~.` is consumed by the outer SSH and tears down the whole connection. Use a second SSH session running `ipmitool ... sol deactivate` instead.

### 3b. Reboot and capture POST serial to a file

For "重启抓 POST 串口" / "capture BIOS POST log" / "save SOL output across a reboot". Needs **two** SSH sessions because `sol activate` blocks in the foreground.

```
Terminal A (BMC ssh)              Terminal B (BMC ssh, 2nd session)
sol deactivate           # cleanup
sol activate | tee $LOG  # blocks, streams to file
                                  chassis power cycle      # host reboots, POST → $LOG
                                  # ... wait for POST + login banner ...
                                  sol deactivate           # frees A
# A unblocks, log complete
```

1. **Terminal A — start tee'd capture:**

   ```sh
   LOG=/tmp/post_sol_$(date +%Y%m%d_%H%M%S).log; echo "LOG=$LOG"
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus sol deactivate 2>/dev/null
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus sol activate | tee $LOG
   ```

2. **Terminal B — trigger reset** (second SSH+login to the BMC):

   ```sh
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus chassis power cycle
   ```

   Variants: `power reset` (warm), `power off` + `power on` (cold), `power cycle` (default).

3. **Wait** for POST (~60–120 s on Intel server BIOS — memory training dominates). End marker: OS login banner (`<hostname> login:`) or UEFI Shell prompt.
4. **Terminal B — stop capture from outside** (more reliable than `~.`):

   ```sh
   ipmitool -H <BMC_HOST> -U <IPMI_USER> -P <IPMI_PASS> -C <IPMI_CIPHER> -I lanplus sol deactivate
   ```

5. **Copy the log back** (prefer `pscp` — accepts the password as an argument):

   ```powershell
   pscp -pw <BMC_SSH_PASS> <BMC_SSH_USER>@<BMC_HOST>:/tmp/post_sol_<timestamp>.log .\post_sol_final.log
   ```

   Fallback to OpenSSH `scp` from a real interactive PowerShell if `pscp` is unavailable.

6. **Sanity check:** `Get-FileHash`/`md5sum` match, `Get-Content -Tail 20` ends at the login banner.

**Why two sessions, not `sol activate &`:** backgrounding detaches it from the controlling TTY and ipmitool stops emitting serial — you get an empty file. The foreground `tee` pattern is the only reliable capture.

### Cleanup
Inside SOL, `~.` on a new line to drop the payload (or `sol deactivate` from a second session). Then `exit` the BMC shell. Leaving SOL active blocks future activations and other engineers.

### Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Unable to establish IPMI v2 / RMCP+ session` | Wrong cipher / IPMI user, or BMC IPMI down. Try without `-C`, or `-C 3`. Verify `ipmitool -H ... lan print 1` from inside the BMC. |
| `SOL payload already active on another session` | See 3a step 4 — deactivate then re-activate. |
| `Unable to establish LAN session` (from inside BMC) | OpenBMC `phosphor-ipmi-net` not running. `systemctl status phosphor-ipmi-net`. |
| Garbage / no output after activate | Host serial baud mismatch — `sol info 1` baud (usually 115.2k) must match the host BIOS serial-console redirection COM port. |

---

## 4. All-in-parallel (fan-out)

For "connect all" / "同时连接所有" / `mode=all`: launch every mode whose required arguments were supplied **concurrently**. Tolerate per-mode failure — a missing-cred or failed session must NOT block the others.

### Launch order (issue each async connect back-to-back, capture every ID)
1. **PsExec #1 → CScripts** (prefer pass-through). After `C:\Windows\System32>`, send `cd /d <CS_ROOT> && dflaunch cscripts\<CS_LAUNCHER>` with `waitForOutput=false`. Don't wait for `In [1]:`.
2. **PsExec #2 → PythonSV** (separate ID, same `<OOB_HOST>`). Send `cd <PYSV_ROOT> && python <PYSV_LAUNCHER>` once the cmd prompt appears; the "Use previous config?" prompt auto-assumes `yes`.
3. **SSH → OS** (`<OS_USER>@<OS_HOST>`, see SKILL.md Section 1). Send the password. If it exits with `Connection timed out`, **record and continue** — expected when the OS isn't up. Do NOT retry.
4. **SSH → BMC**. Send the password, then the one-shot `sol set enabled true && sol activate` (Section 3a step 3).

Skip any mode missing creds; record `skipped (missing creds)` in the summary instead of pausing.

### After launches: poll for readiness and summarize
Give PythonSV/CScripts ~60 s to init, then `get_terminal_output` on each ID and present a status table: `| Mode | Terminal ID | Status (ready marker / error / skipped) |`.

### Hard constraints during fan-out
- **Shared XDPA probe (CScripts ⇄ PythonSV).** Both attach to the same OpenIPC probe. **Concurrent reads are safe.** **Do NOT run halt / unlock / register writes / break in both at once** — the second issuer gets probe-busy errors or corrupts the other's state. Warn the user when both are up.
- **BMC SOL terminal is foreground host-serial.** After `[SOL Session operational]`, that terminal forwards every keypress to the host. Open a second BMC SSH for power cycle / deactivate / log copy.
- **No automatic OS-SSH retry.** Treat timeout / refused / no route as informational and continue with the other modes.
- **Don't block on slow inits.** Fire all launches first, summarize later — PythonSV/CScripts startup is 60–120 s.
- **No clarification mid-fan-out.** Collect every required argument up front; missing-arg modes are silently skipped (and recorded).
