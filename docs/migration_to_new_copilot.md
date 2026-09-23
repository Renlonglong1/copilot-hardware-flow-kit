# Migration Guide for a New Copilot Environment

Use this guide when moving the hardware flow to another PC/server/Copilot workspace.

## What to Copy

Copy the whole folder:

```text
C:\Users\rli\copilot-hardware-flow-kit
```

The important portable entry points are:

```text
README.md
.github\copilot-instructions.md
.github\skills\bhs-hardware-flow\SKILL.md
config\hardware-flow.template.json
config\hardware-flow.dbgsh05.json
docs\bhs_uplr2_robust_full_flow.md
docs\emulator_powersplitter_cli_notes.md
docs\hsd_python_api_notes.md
scripts\*.ps1
```

## New Server Setup Checklist

1. Configure passwordless SSH from the Copilot machine to the Windows hardware server. If the target uses a dedicated local private key, configure its `IdentityFile` and `IdentitiesOnly yes` in the local (uncommitted) `C:\Users\<user>\.ssh\config`; do not assume the default `id_ed25519` is authorized.
2. Confirm `smucmd.exe` exists on the remote server.
3. Confirm `PowerSplitterCL.exe` exists on the remote server.
4. Confirm the target `.bin` file path.
5. Confirm chip model, usually `MX66U1G45G` for the current BHS uPLR2 flow.
6. Confirm serial ports:
   - COM3 = GNR CPU
   - COM4 = BMC
   - 115200 8N1
7. Copy `config\hardware-flow.template.json` to `config\local\hardware-flow.json`; this local runtime profile is ignored by Git.
8. Replace SSH host, bin path, expected device serial, and tool paths as needed.
9. Ask Copilot to read `docs\bhs_uplr2_robust_full_flow.md` before running the flow.
10. Read `docs\local_runtime_profiles.md` to keep deployment-only settings separate from portable files.

## Recommended One-Pass Validation

Use this command after updating the server-specific config:

```powershell
cd C:\Users\rli\copilot-hardware-flow-kit
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

What this command does:

1. Verifies SSH, bin hash, DediProg USB visibility, `smucmd`, and PowerSplitter.
2. Optionally closes `EM100.exe` / `Emulator.exe` GUI conflicts before flashing.
3. Powers off, flashes, and validates flash output keywords.
4. Copies serial helper scripts to the remote `flow_logs` folder instead of using long encoded commands.
5. Opens COM3/COM4 before power-on, captures 10-minute raw logs, and checks boot evidence.
6. Logs in on COM3 and runs MLC baseline commands, then verifies saved result files contain `EXIT:0`.

## Recommended User Prompt

```text
请按 BHS uPLR2 robust full flow 跑一遍：
服务器：debug@<server-ip>
bin 文件：<remote-bin-path>
芯片型号：MX66U1G45G
串口：COM3=GNR CPU，COM4=BMC
串口抓取时间：10分钟
要求：烧录失败立即诊断和自恢复；烧录成功后再开电抓串口；保存完整原始日志后再分析。
```

## Success Criteria

The new environment is ready when Copilot can report:

```text
FLASH_OK=True
FLOW_OK=True
COM3 log saved
COM4 log saved
MLC_OK=True
```

## Important Pitfalls

- Do not start serial capture if flash failed.
- Do not rely only on `smucmd.exe` exit code.
- `EM100.exe` / `Emulator.exe` GUI processes can cause `No device is connected!`.
- COM3 can be silent for several minutes; capture the full 10-minute raw log before analysis.
- Keep the known good logs for comparison.
- Do not rely on marker strings echoed by the serial console; verify the real prompt and saved result files.
- If remote command text gets too long, copy a `.ps1` helper to the remote server and run it with `powershell -File`.
- If SSH reports public-key denial after a migration, inspect `ssh -G debug@<host>` and test the already provisioned target-specific key explicitly before any hardware action. For the safe host-key procedure, see `docs\ssh_passwordless.md`.

## MLC Migration Notes

MLC command knowledge is documented in:

```text
docs\mlc_command_manual.md
```

When migrating to a new Host OS, confirm:

1. MLC binary path, for example `/root/mlc_v3.11b/mlc`.
2. MLC version, for example `Intel(R) Memory Latency Checker - v3.11b`.
3. Root access is available.
4. `msr` module can be loaded with `modprobe msr` when needed.
5. Result logs are saved under a timestamped result directory.

Known validated result directories on current Host OS:

```text
/root/mlc_v3.11b/copilot_mlc_results_20260623_094808
/root/mlc_v3.11b/copilot_mlc_results_20260623_094928
```

## HSDES Migration Notes

HSDES database search and Python API knowledge is documented in:

```text
docs\hsd_python_api_notes.md
```

When migrating to a new Copilot environment, confirm:

1. Python is installed.
2. `requests`, `requests-kerberos`, `certifi`, and `truststore` are installed.
3. The user has a valid Windows/Kerberos login context.
4. Python HSD calls use `truststore.inject_into_ssl()` on Windows.
5. Article extraction uses `https://hsdes-api.intel.com/rest/article/<articleId>`.
6. If Python `requests` returns a generic HTML `Access Denied` / `403`, retry with direct curl proxy bypass.

Validated package install command on this PC:

```powershell
py -m pip --proxy http://proxy-dmz.intel.com:911 install requests requests-kerberos certifi truststore
```

Validated fetch command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId 14027366976
```

Validated fallback when Python/API path gets generic HTML `403 Access Denied`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId 14027366976 -ForceCurlDirect
```

For field extraction, first search returned keys because some fields are tenant-qualified, for example:

```text
server_platf_ae.bug.ext_cust_blog_hist
```

Validated HSD example:

```text
Article 14027366976
Title: [MEM] GNR-SP HCC Support 2+2 DIMM Population
Status: complete
Fix: MagInfra GNR-SP HCC 2-DIMM CVILS PORed
Key conclusion: for 2DPC, populate CH0/CH4 (C0D0/C4D0).
```
