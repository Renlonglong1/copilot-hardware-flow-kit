# RAK API Reference

Purpose: list the RAK framework APIs, runtime objects, and framework-provided helper calls that may be used in generated RAK Python cases.

Rules:
- Use only APIs listed in this file or platform CScripts calls listed in `CScript_Functions_Reference.md`.
- Do not invent APIs, parameters, return values, runtime objects, or side effects.
- Prefer the primary API name shown in this file when aliases exist.
- Platform-specific CScripts functions such as `ei.*`, `ras.*`, `error.*`, `mc.*`, `pcie.*`, `upi.*`, and `cxl.*` are not defined here; use `CScript_Functions_Reference.md` for those.

## 1. CScripts-Dependent RAK APIs

These APIs require CScripts / `ITP_enable=true` unless a platform reference explicitly says otherwise:

| API | Dependency note |
|---|---|
| `RAK_WAIT_SYSTEM_STATUS(...)` | Requires CScripts system status access. |
| `RAK_ASSERT_SYSTEM_STATUS(...)` | Requires CScripts system status access. |
| `RAK_SHOW_HWCONFIG()` | Requires CScripts hardware discovery. |
| `RAK_CHECK_HWCONFIG(HW_INFO)` | Requires CScripts hardware discovery. |
| `RAK_ADDTRAN_SPA_TO_RANK(...)` | Requires CScripts address translation support. |
| `RAK_ADDTRAN_RANK_TO_SPA(...)` | Requires CScripts address translation support. |
| `RAK_ADDTRAN_SPA_TO_DRAM(...)` | Requires CScripts address translation support. |
| `RAK_ADDTRAN_DRAM_TO_SPA(...)` | Requires CScripts address translation support. |
| `RAK_ASSERT_CSR(...)` | Requires CScripts register access. |
| `RAK_ASSERT_MSR(...)` | Requires CScripts MSR access. |

If a case uses any of these APIs, declare CScripts / `ITP_enable=true` in the ConfigInfo or HW-configuration notes.

## 2. System State APIs

### `RAK_CHECK_OS_READY()`
Purpose: check whether the target OS is ready.
Return: `True` or `False`.
Example:

```python
if not RAK_CHECK_OS_READY():
    itp.resettarget()
```

### `RAK_WAIT_SYSTEM_STATUS(target=0x1111, timeout=60)`
Purpose: wait for the system status to reach `target`.
Parameters:
- `target`: CPU or OS/system status code.
- `timeout`: timeout in seconds.
Preferred example:

```python
RAK_WAIT_SYSTEM_STATUS(SYS_STATUS.OS.OS_READY, timeout=1000)
```

### `RAK_ASSERT_SYSTEM_STATUS(expect=0x1111)`
Purpose: fail the case if current system status is not `expect`.
Preferred example:

```python
RAK_ASSERT_SYSTEM_STATUS(SYS_STATUS.OS.OS_READY)
```

### `SYS_STATUS`
Purpose: symbolic status-code namespace.

CPU status codes:

| Name | Value |
|---|---:|
| `SYS_STATUS.CPU.RUNNING` | `0x0000` |
| `SYS_STATUS.CPU.GO` | `0x0001` |
| `SYS_STATUS.CPU.HALT` | `0x0002` |
| `SYS_STATUS.CPU.READY` | `0x0003` |
| `SYS_STATUS.CPU.SMM` | `0x0004` |

OS/system status codes:

| Name | Value |
|---|---:|
| `SYS_STATUS.OS.OS_READY` | `0x1000` |
| `SYS_STATUS.OS.SHELL` | `0x1001` |
| `SYS_STATUS.OS.BIOS` | `0x1002` |
| `SYS_STATUS.UNKNOWN` | `0x1110` |
| `SYS_STATUS.ALL` | `0x1111` |

### `itp.resettarget()`
Purpose: reset the target system.
Use when the case is CScripts-enabled and target reset is required.

### `halt()` and `go()`
Purpose:
- `halt()`: halt the target.
- `go()`: resume the target.

Use register reads and transient status assertions before `go()` when firmware, SMI, OS recovery, or device recovery may clear status registers.

### `RAK_DELAY(seconds=3)`
Purpose: wait for the requested number of seconds. If no argument is provided, the default is 3 seconds.

## 3. Hardware Configuration and BIOS Knob APIs

### `RAK_SHOW_HWCONFIG()`
Purpose: show the current machine hardware configuration.
Dependency: CScripts / `ITP_enable=true`.

### `RAK_CHECK_HWCONFIG(HW_INFO)`
Purpose: check whether current hardware matches the case HW configuration table.
Dependency: CScripts / `ITP_enable=true`.
Parameter rule: use `HW_INFO` exactly; do not rename it.
Format rule: when using this API, include a standalone `##HW-configuration:` header in ConfigInfo.

### `RAK_UEFI_KNOBS(uefi_knobs, cmos=True, ssh=True)`
Purpose: modify BIOS setup from a UEFI shell environment.
Requirements:
- Requires a UEFI shell environment in BIOS or USB bootable media.
- Requires the BIOS knob structure expected by RAK.
Parameters:
- `uefi_knobs`: BIOS knob assignment string or framework-provided knob variable.
- `cmos`: whether to clear CMOS.
- `ssh`: whether SSH is required.
Example:

```python
RAK_UEFI_KNOBS(UEFI_BIOS_knobs)
```

Alias listed in source references: `RAK_SET_KNOBS(uefi_knobs, cmos=True)`. Existing cases may use the alias; prefer `RAK_UEFI_KNOBS(...)` for new generated cases.

### `RAK_GEN_BIOSCFG(path=None)`
Purpose: generate a BIOS configuration file.
Note: documented to generate `{config.runtime.current_case_name}_bios_cfg.txt`.

### `RAK_GET_KNOBS(file_path)`
Purpose: get UEFI variables or BIOS knob values from `file_path`.

### `RAK_COMP_KNOBS(json1_path, json2_path)`
Purpose: compare BIOS knob JSON files.

## 4. Remote Target OS APIs

### `RAK_CMD_REMOTE(cmd, timeout=5)`
Purpose: execute `cmd` on the remote target OS through SSH.
Parameters:
- `cmd`: command string.
- `timeout`: command timeout in seconds.
Example:

```python
RAK_CMD_REMOTE("cd /root && ls -al")
```

RAS clean-baseline example:

```python
RAK_CMD_REMOTE("sudo dmesg -C")
```

Use the dmesg clear command before injection only when the case verifies post-injection dmesg content and needs a clean baseline.

### `RAK_CMD_REMOTE_OUTPUT_SCRIPT(cmd)`
Purpose: get remote command output as documented by the RAK engineering guide.

### `RAK_CMD_REMOTE_IN_SESSION(session, cmd)`
Purpose: execute `cmd` in a persistent SSH session for background or streaming processes.
Dependency: requires `tmux` on the remote Linux OS.
Example:

```python
RAK_CMD_REMOTE_IN_SESSION("session1", "ls")
```

### `RAK_DOWNLOAD_SSH_SESSION_LOG(session)`
Purpose: download a named SSH session log to the local case log path.

### `RAK_UPLOAD_TO_REMOTE(srcDir, desDir)`
Purpose: upload file or directory content from host to target OS.

### `RAK_DOWNLOAD_FROM_REMOTE(srcDir, desDir=None)`
Purpose: download files or directories from target OS to host.
Note: `desDir` defaults to the current case path.

### `RAK_REMOTE_CMD_CHECK(cmd, timeout, patternType, matchType, existType, *keywords)`
Purpose: execute a remote command and check command output with the shared pattern matching arguments.

### `RAK_REMOTE_CMD_GETVALUE(cmd, timeout, keyword)`
Purpose: execute a remote command and extract the value associated with `keyword`.
Return: documented as a string.

## 5. Local Host APIs

### `RAK_CMD_LOCAL(cmd)`
Purpose: execute `cmd` on the host where RAK is running.

### `RAK_CMD_LOCAL_THREAD(cmd)`
Purpose: execute a local host command in a thread.

## 6. BMC and IPMI APIs

### `RAK_CMD_BMC(cmd, timeout=5)`
Purpose: execute `cmd` on the BMC through SSH.
Use cases:
- OOB RAS / RAS Offload tests.
- Reading or clearing BMC RAS manager logs.
Notes:
- Requires BMC SSH configuration in `config.ini`.
- Output is saved under the case log folder as `{case_name}.py_BMC_cmd.log`.

### `RAK_CMD_BMC_WITH_ADMIN(cmd, pw, timeout=5)`
Purpose: execute a BMC command that requires admin or root privilege escalation.
Parameters:
- `cmd`: command string.
- `pw`: admin password string.

### `RAK_IPMI_CMD_EXECUTE(cmd)`
Purpose: execute an IPMI command.
Example:

```python
RAK_IPMI_CMD_EXECUTE("sol activate")
```

## 7. Runtime Metadata

The `config.runtime` namespace exposes read-only metadata for the current case.

### `config.runtime.current_case_name`
Purpose: current test case filename without `.py`.
Typical use: build log filenames for `RAK_LOCAL_FILE_ANALYSE(...)`.

### `config.runtime.current_case_path`
Purpose: absolute output/log directory for the current case.
Typical use: pass current case paths to `RAK_CMD_LOCAL(...)` or local file analysis.

Example:

```python
current_name = config.runtime.current_case_name
log_file = f"./{current_name}.py_BMC_cmd.log"
```

## 8. Address Translation APIs

### `RAK_ADDTRAN_SPA_TO_RANK(spa)`
Purpose: translate a system physical address to rank address and location information.
Dependency: CScripts / `ITP_enable=true`.
Return: `location, rank_address`.
Example:

```python
location, rank_address = RAK_ADDTRAN_SPA_TO_RANK(0x40000000)
```

### `RAK_ADDTRAN_RANK_TO_SPA(location, mem_type, rank_addr)`
Purpose: translate a rank address to system physical address.
Dependency: CScripts / `ITP_enable=true`.
Examples:

```python
spa = RAK_ADDTRAN_RANK_TO_SPA([0, 1, 1, 0, 0, 0], "ddr5", 0x10000000)
spa = RAK_ADDTRAN_RANK_TO_SPA([0, 1, 1, 0], "ddr4", 0x10000000)
```

### `RAK_ADDTRAN_SPA_TO_DRAM(spa)`
Purpose: Birch Stream SPA-to-DRAM address translation API listed in the engineering guide.
Dependency: CScripts / `ITP_enable=true`.
Use only when the platform flow documents the expected returned fields.

### `RAK_ADDTRAN_DRAM_TO_SPA(location, mem_type)`
Purpose: Birch Stream DRAM-to-SPA address translation API listed in the engineering guide.
Dependency: CScripts / `ITP_enable=true`.
Use only when the platform flow documents the required input fields.

## 9. Assertions and Verification APIs

### `RAK_ASSERT(first, second, msg=None)`
Purpose: fail if `first` and `second` are unequal.

### `RAK_ASSERT_EQUAL(first, second, msg=None)`
Purpose: fail if `first` and `second` are unequal.

### `RAK_ASSERT_NOTEQUAL(first, second, msg=None)`
Purpose: fail if `first` and `second` are equal.

### `RAK_ASSERT_CSR(CSR, *args, msg=None)`
Purpose: compare a CScripts CSR/register value with an expected value or bit-field dictionary.
Dependency: CScripts / `ITP_enable=true`.
Examples:

```python
RAK_ASSERT_CSR(sv.socket0.uncore.pcie.pxp2.port0.cfg.erruncsts, 0)
RAK_ASSERT_CSR(sv.socket0.uncore.pcie.pxp2.port0.cfg.erruncsts, {"bit0": 1, "bit9-7": 2})
```

Formatting rule: generated `RAK_ASSERT_CSR(...)` calls must remain on one physical line.

### `RAK_ASSERT_MSR(first, *args, msg=None)`
Purpose: compare an MSR value with an expected value or bit-field dictionary.
Dependency: CScripts / `ITP_enable=true`.
Examples:

```python
RAK_ASSERT_MSR(int(itp.threads[0].msr(0x709)), 0)
RAK_ASSERT_MSR(int(itp.threads[0].msr(0x419)), {"bit63": 1, "bit61": 0, "bit57": 1, "bit15-1": 0xe0b})
```

Rule: CScripts MSR reads such as `itp.threads[0].msr(...)` can return CScripts integer-like objects. Convert the MSR read to a native Python `int` before passing it to `RAK_ASSERT_MSR(...)`, while preserving the original access form. For example, use `RAK_ASSERT_MSR(int(itp.threads[0].msr(0x4d7)), expected)` instead of replacing it with bare `msr(...)`.

## 10. Shared Pattern Matching Arguments

These arguments are used by log analysis and command-check APIs.

| Argument | Allowed values |
|---|---|
| `patternType` | `"normal"` or `"regex"` |
| `matchType` | `"sequential"` or `"unsequential"` |
| `existType` | `"exist"` or `"unexist"` |
| `*keywords` | Exact keywords or regex patterns, depending on `patternType`. |

Rules:
- Use log analysis only when exact keywords are provided by the user, recipe, or reference case.
- Do not invent generic OS, MCA, WHEA, AER, panic, or Oops keywords.
- Use OR matching only when the source recipe explicitly provides the full OR expression or separator syntax. Do not synthesize OR expressions from unrelated keywords.

## 11. Log Analysis APIs

### `RAK_DMESG_ANALYSE(command, patternType, matchType, existType, *keywords)`
Purpose: run a dmesg command on the target OS and match keywords in the output.

### `RAK_SERIAL_ANALYSE(patternType, matchType, existType, *keywords)`
Purpose: match keywords in serial logs.

### `RAK_CSCRIPT_ANALYSE(command, patternType, matchType, existType, *keywords)`
Purpose: execute one CScripts command and match keywords only within that command output.

### `RAK_SOL_ANALYSE(patternType, matchType, existType, *keywords)`
Purpose: match keywords in SOL logs.

### `RAK_SEL_LOG_ANALYSE(patternType, matchType, existType, *keywords)`
Purpose: match keywords in SEL logs.

### `RAK_LOCAL_FILE_ANALYSE(filePath, patternType, matchType, existType, *keywords)`
Purpose: match keywords in a local file.

## 12. Log Collection and Value Extraction APIs

### `RAK_SEL_LOG_COLLECT()`
Purpose: collect SEL logs with IPMI tool into the case log folder.

### `RAK_SEL_LOG_CLEAR()`
Purpose: clear SEL logs with IPMI tool.

### `RAK_SERIAL_LOG_GETVALUE(keyword)`
Purpose: extract a decimal integer value from serial logs by keyword.
Return: documented as integer.

### `RAK_SOL_LOG_GETVALUE(keyword)`
Purpose: extract a decimal integer value from SOL logs by keyword.
Return: documented as integer.

Remote command value extraction uses `RAK_REMOTE_CMD_GETVALUE(cmd, timeout, keyword)`, defined in section 4.

## 13. Error Injection and Fisher APIs

### `RAK_EINJ_INJECT(error_type, flags, param1, param2, param3, param4, notrigger)`
Purpose: inject an ACPI EINJ error using the engineering-guide signature that includes `notrigger`.

### `RAK_EINJ_INJECT(error_type, flags, param1, param2, param3, param4)`
Purpose: inject an ACPI EINJ error using the signature without `notrigger`.
Parameter meanings:
- `error_type`: ACPI EINJ error type.
- `flags`: bitmask specifying which parameters are valid.
- `param1`: often memory address for memory-related EINJ flows.
- `param2`: often address mask for memory-related EINJ flows.
- `param3`: APIC ID when flag bit `0x1` is set.
- `param4`: target PCIe device when flag bit `0x4` is set.
Allowed call forms:

```python
RAK_EINJ_INJECT(error_type, flags, param1, param2, param3, param4, notrigger)
RAK_EINJ_INJECT(error_type, flags, param1, param2, param3, param4)
```

Rules:
- Use EINJ only when the user or source recipe explicitly requires it.
- Use the signature and provided parameters from the source recipe. Do not invent missing EINJ flags, masks, trigger behavior, or platform-specific side effects.

### `RAK_Fisher_remote_injector(remote_Injector_path)`
Purpose: run Fisher `remote_injector.py` and update the connection IP in the runtime variable.

### `RAK_FISH_CMD_WITH_LOG_DOWNLOAD(cmd)`
Purpose: run a Fisher command on the target system and download the Fisher log to `config.runtime.current_case_path`.

## 14. Utility APIs

### `RAK_NOTIFY(message)`
Purpose: show a notification that interrupts script execution and waits for manual confirmation.
Use only in Automation Level 0 cases.

### `RAK_PARAM(type, cmd, param)`
Purpose: auto-fill parameters for interaction requirements.
Supported types: documented CScripts or Linux command interactions.
Example:

```python
RAK_PARAM(type="cscript", cmd="ei.AMEI()", param="1,1,2,1")
```

### `RAK_SIMICS(cmd)`
Purpose: execute a Simics command.
Example:

```python
RAK_SIMICS("continue")
```

## 15. Dependency Summary

| Dependency | APIs or cases |
|---|---|
| CScripts / `ITP_enable=true` | System status wait/assert, HW config, address translation, CSR/MSR assertions. |
| UEFI shell | `RAK_UEFI_KNOBS(...)`. |
| SSH to target OS | Remote command, remote session, upload, download, dmesg analysis. |
| `tmux` on target OS | `RAK_CMD_REMOTE_IN_SESSION(...)`. |
| BMC SSH | `RAK_CMD_BMC(...)`, `RAK_CMD_BMC_WITH_ADMIN(...)`. |
| IPMI tool or IPMI path | SEL collection, SEL clear, IPMI command execution. |

Final rule: this file is a whitelist. If an API, parameter, return value, or runtime object is not listed here or in the platform CScripts reference, do not generate it.
