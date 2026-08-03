# Oak Stream CScripts Reference

## Purpose and Location

CScripts is the Oak Stream platform scripting framework used for platform discovery, register access, and platform-specific debug APIs. It is installed on the validated control server:

```text
SSH control server: debug@10.239.84.44 (dbgsh12)
Latest package: C:\Users\debug\Desktop\CScripts\821387_Oak_Stream_CScripts_Rev_2615_2000
Framework root: C:\Users\debug\Desktop\CScripts\821387_Oak_Stream_CScripts_Rev_2615_2000\cscripts
Entry point: cscripts_api.py
Release notes: cscripts\docs\821387_Oak_Stream_CScripts_UG_Release_Notes_Rev_2615_2000.pdf
```

The root also retains `Rev_2550_2000`, an older `cscripts` directory, release ZIP archives, and an older PDF. Prefer `Rev_2615_2000` unless a task specifically requires another revision.

## Repository Layout

```text
cscripts\
  cscripts_api.py                 Framework entry point
  api_design\
    framework_api\                Framework lifecycle and connection management
    platform_apis\                Platform API registration and implementations
    services_api\                 Argument parsing, logging, and services
  dependencies\                   Bundled Python, named-node, register, and third-party libraries
  docs\                           Release notes and legal documentation
  license\                        License material
  validation\                     Validation harness, test helpers, and requirements
```

The CPU API tree includes areas such as CPUID, MSR, memory, I/O, RAS, crashlog, error injection, fabrics, D2D, EDK2, and Simics. Available APIs depend on the detected platform and selected ingredient.

## Operating Model

`cscripts_api.py` supplies two modes:

1. **Interactive mode**: start the script with command-line options, then use the framework environment.
2. **Python API mode**: import `cscripts_api` and call `start(...)`.

Startup creates services, selects a connection, detects the platform/flavor, registers matching APIs, and exposes the registered API objects to the running Python main module. It also creates a session log and enables register logging by default.

## CLI Usage

Run all commands from the framework root:

```powershell
Set-Location -LiteralPath 'C:\Users\debug\Desktop\CScripts\821387_Oak_Stream_CScripts_Rev_2615_2000\cscripts'
py .\cscripts_api.py --help
```

Validated help output identifies these access modes:

```text
itp, inband, stub, simics, redfish,
test_itp, test_inband, test_stub, test_redfish,
ipc_simics, test_ipc_simics, ipc, test_ipc
```

Key options:

| Option | Meaning |
|---|---|
| `-a`, `--access` | Connection/access mode |
| `-i`, `--ingredients` | Platform ingredient selection; help examples include `MVS`, `SPR`, `DMR`, `RPL`, `NVL`, `ALL` |
| `-H`, `--host` | Remote target hostname or IP |
| `-pt`, `--port` | Remote target connection port |
| `-t`, `--timeout` | Connection timeout in milliseconds |
| `-U`, `--username` | Remote target user name |
| `-vf`, `--verify` | Enable TLS/SSL certificate verification |
| `--simics_ipc_scripts`, `--ipc_path`, `--work_path` | IPC/Simics environment or working-directory overrides |
| `-c`, `--config` | OpenIPC configuration |
| `--multi-instance` | Enable OpenIPC multi-instance support |
| `--legacy_interface` | Use legacy interface names where available |
| `--console_log_level` | Set `INFO`, `DEBUG`, or `ERROR` |
| `--stop_on_error` | Stop execution when an error occurs |
| `--deactivate_register_logging` | Disable register-access logging |
| `--deactivate_create_log_file` | Disable current-session log-file creation |

Do not pass passwords on the command line. Use an approved non-secret authentication mechanism or run the connection setup interactively.

## Python API Usage

The exported startup function has this shape:

```python
cscripts_api.start(
    ingredients="ALL",
    access="stub",
    host=None,
    port=None,
    stop_on_error=False,
    breakpoint_on_error=False,
    create_log_file=True,
    console_log_level="INFO",
    activate_register_logging=True,
    run_as_api=True,
    legacy_interface=False,
)
```

`host` and `port` are used for remote access, including the `ipc_simics` connection. The default `stub` access does not establish a real hardware connection; selecting an ITP, in-band, Redfish, IPC, or Simics mode must be based on the target platform's approved connection setup.

## Safe Operating Procedure

1. Identify the target platform, CScripts revision, and approved access mode before running the framework.
2. Start with `py .\cscripts_api.py --help`; do not assume that an access mode or ingredient is available.
3. Preserve the session log and register-access log whenever hardware access is used.
4. Use `--stop_on_error` for unattended diagnostics so failures are surfaced rather than followed by additional actions.
5. Keep credentials, private keys, tokens, and Kerberos-ticket contents out of command lines, logs, and this repository.
6. Treat register writes, error injection, and platform control APIs as hardware-changing actions; confirm the requested scope before invoking them.

## Validation Assets

`validation\` contains the packaged test and support tooling, including environment activation, register dump/compare helpers, API testing, log parsing, test-case generation, and dependency requirement files. These are framework validation assets, not a substitute for a target-specific hardware test plan.

## Discovery Commands

Use these read-only commands to inspect the installed revision before a new task:

```powershell
$root = 'C:\Users\debug\Desktop\CScripts\821387_Oak_Stream_CScripts_Rev_2615_2000\cscripts'
Get-ChildItem -LiteralPath $root -Directory
py (Join-Path $root 'cscripts_api.py') --help
Get-ChildItem -LiteralPath (Join-Path $root 'docs') -File
```
