---
name: rak-remote-runner
description: "Deploy a RAK test case to a remote Windows debug machine via SSH and execute it using rak_cui.exe. Use this skill whenever the user asks to run, deploy, send, or execute a RAK test case on a remote machine, debug machine, or test bench. Also triggers for phrases like 'run this case remotely', 'send to debug machine', 'execute on RAK machine', 'validate on target', or any request involving uploading a .py RAK script and collecting results from a remote RAK environment."
argument-hint: "Provide the RAK test case (inline or file path) and optionally the remote host info."
---

# RAK Remote Runner

Deploy a generated RAK test case (.py) to a remote Windows debug machine that already has a
working RAK environment, execute it via `rak_cui.exe`, and download the result logs back to
the local machine for review.

## Workflow Overview

```
Local machine                        Remote debug machine (Windows)
─────────────                        ──────────────────────────────
1. Save test case as .py       ──►   2. Upload via SSH/SFTP
                                     3. rak_cui.exe run --files_path <case>
                                     4. Wait for completion
5. Download log package        ◄──   (logs in RAK output directory)
6. Present log location to user
```

## Prerequisites

- **Python `paramiko`** must be installed locally.
  If missing, install with: `pip install paramiko`
  If your environment requires a proxy, configure it using your local network settings or pip proxy options.
- The remote machine must have **OpenSSH Server** enabled (Windows 10+ / Server 2019+).
- `rak_cui.exe` must be present on the remote machine.

## Connection Configuration

Connection settings are stored in **[../rak_remote_config.ini](../rak_remote_config.ini)** at the `ras-test` skill root. Edit that file to configure your remote machine before running.

`generated_testscripts_dir` in the same config file defines where Phase 1 should save newly generated `.py` cases locally.

`case_file` is **not** stored in config. The local case path must be provided by the user at invocation time via `--case-file <local_case_file.py>`.
Do not store `password` in this file.

If the user has previously provided these values in the conversation, reuse them.
If a session memory file `/memories/session/rak-remote-config.md` exists, read it for
saved connection details.

## Step-by-Step Instructions

### 1. Prepare the test case file

If the test case was just generated in conversation (not yet saved to disk), save it:
- Write the script content to a `.py` file under `generated_testscripts_dir` from `rak_remote_config.ini`.
- If `generated_testscripts_dir` is absent, fall back to the workspace `generated_testscripts_dir/`.
- Use a descriptive filename (e.g., `OKS_SDDC_CE_Injection.py`).

### 2. Ensure paramiko is installed

```python
python -c "import paramiko; print('paramiko OK')"
```
If it fails, install:
```
python -m pip install paramiko --proxy=http://child-prc.intel.com:913
```

### 3. Run the deployment script

Execute the bundled runner script using the shared config file at the `ras-test` root, and always pass the case path explicitly:

```
python <skill-dir>/scripts/rak_remote_run.py ^
    --config <ras-test-dir>/rak_remote_config.ini ^
    --case-file <local_case_file.py>
```

When `--key-file` and `--password` are not provided, the script prompts for SSH password at runtime.

You can override any config value with a CLI flag (CLI takes priority over the file):

```
python <skill-dir>/scripts/rak_remote_run.py ^
    --config <ras-test-dir>/rak_remote_config.ini ^
    --case-file <local_case_file.py> ^
    --timeout <minutes, default 60>
```

The script performs these steps automatically:
1. Opens SSH connection to the remote machine.
2. Uploads the `.py` test case via SFTP to `<remote_case_dir>`.
3. Executes `rak_cui.exe run --files_path <remote_case_dir>\<case_file>`.
4. Streams stdout/stderr in real time so the user can see progress.
5. After completion, identifies the latest log directory under `<remote_rak_path>\logs\`.
6. Downloads the entire log directory to `<rak_result_dir>\<case_name>\`.
7. Prints a summary: exit code, log location, and elapsed time.

### 4. Present results

After the script finishes:
- Tell the user the local path where logs were downloaded.
- If the user wants automated PASS/FAIL analysis, that is out of scope for this skill —
  the user will review logs manually.

## Error Handling

| Situation                        | Action                                              |
|----------------------------------|-----------------------------------------------------|
| SSH connection refused           | Verify host/port, check OpenSSH Server is running   |
| Authentication failed            | Re-ask user for credentials                         |
| `rak_cui.exe` not found          | Ask user to verify `remote_rak_path`                |
| Timeout exceeded                 | Inform user; offer to increase timeout and retry    |
| SFTP upload fails                | Check remote path exists; offer to create it        |

## Security Notes

- Never print or log the password in terminal output or files.
- Do not add `password` to `rak_remote_config.ini`; passwords must be entered interactively at run time (or use `--key-file`).
- The `--password` argument is passed directly to paramiko; it is not written to any file.
- If the user prefers SSH key auth in the future, the script also supports `--key-file`.

## Session Memory

After a successful first run, save the connection config (excluding password) to session
memory so subsequent runs in the same conversation reuse it automatically:

```
/memories/session/rak-remote-config.md
```

Format:
```
- remote_host: 10.239.xx.xx
- remote_user: administrator
- remote_rak_path: C:\RAK
- remote_case_dir: C:\RAK\testscripts
- rak_result_dir: .\rak_results
```
