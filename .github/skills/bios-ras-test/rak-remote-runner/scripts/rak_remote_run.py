"""
RAK Remote Runner — deploy a RAK test case to a remote Windows debug machine
via SSH, execute it with rak_cui.exe, and download result logs.

Usage:
    python rak_remote_run.py --host HOST --user USER --password PASS \
        --rak-path "C:\\RAK" --case-dir "C:\\RAK\\testscripts" \
        --case-file local_case.py --rak-result-dir ./rak_results \
        [--timeout 60] [--key-file path/to/key]
    
Notes:
    - Do not store passwords in config files.
    - If --key-file and --password are both omitted, the script securely prompts for password.
"""

import argparse
import configparser
import getpass
import json
import os
import sys
import time
import stat
import posixpath
import ntpath


def parse_args():
    p = argparse.ArgumentParser(description="Deploy and run RAK case on remote Windows machine")
    p.add_argument("--config", default=None,
                   help="Optional config file (.ini/.cfg/.json/.yaml/.yml/.conf) with remote settings")
    p.add_argument("--host", default=None, help="Remote host IP or hostname")
    p.add_argument("--port", type=int, default=None, help="SSH port (default 22)")
    p.add_argument("--user", default=None, help="SSH username")
    p.add_argument("--password", default=None,
                   help="SSH password (optional; prefer runtime prompt)")
    p.add_argument("--key-file", default=None, help="Path to SSH private key file")
    p.add_argument("--rak-path", default=None, help="Remote RAK install directory (e.g. C:\\RAK)")
    p.add_argument("--case-dir", default=None, help="Remote directory to upload case into")
    p.add_argument("--case-file", default=None, help="Local .py test case file to upload")
    p.add_argument("--rak-result-dir", dest="output_dir", default=None,
                   help="Local directory to download logs")
    p.add_argument("--output-dir", dest="output_dir", default=None,
                   help="Deprecated alias of --rak-result-dir")
    p.add_argument("--timeout", type=int, default=None, help="Max execution time in minutes")
    p.add_argument("--interactive", action="store_true", default=None,
                   help="Run in the desktop interactive session via schtasks "
                        "(required when ITP/CScripts needs shared-memory IPC)")
    p.add_argument("--show-cmd", action="store_true", default=None,
                   help="When used with --interactive, force opening a visible cmd window "
                        "on remote desktop while running rak_cui.exe")
    args = p.parse_args()

    cfg = load_config(args.config)
    args = merge_args_with_config(args, cfg)

    missing = []
    for key in ("host", "user", "rak_path", "case_dir"):
        if not getattr(args, key):
            missing.append("--" + key.replace("_", "-"))
    if missing:
        print("[ERROR] Missing required settings: " + ", ".join(missing))
        if args.config:
            print(f"[INFO] Checked config file: {args.config}")
        sys.exit(2)

    if not args.case_file:
        print("[ERROR] Missing required argument: --case-file")
        print("[INFO] Please provide the local RAK case file path when invoking the runner.")
        sys.exit(2)

    if not args.password and not args.key_file:
        prompt_user = args.user if args.user else "remote user"
        args.password = getpass.getpass(
            prompt=f"[PROMPT] SSH password for {prompt_user}@{args.host}: "
        )
        if not args.password:
            print("[ERROR] Empty password entered.")
            sys.exit(2)

    return args


def _strip_quote(value):
    text = str(value).strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text

def _normalize_cfg_key(key):
    return str(key).strip().lower().replace("-", "_")


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return None


def _load_simple_yaml(path):
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            data[_normalize_cfg_key(key)] = _strip_quote(val)
    return data


def load_config(path):
    if not path:
        return {}
    if not os.path.isfile(path):
        print(f"[ERROR] Config file not found: {path}")
        sys.exit(2)

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {_normalize_cfg_key(k): v for k, v in raw.items()}

        if ext in (".ini", ".cfg", ".conf"):
            cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
            cp.read(path, encoding="utf-8")
            merged = {}
            for sec in cp.sections():
                for k, v in cp.items(sec):
                    merged[_normalize_cfg_key(k)] = _strip_quote(v)
            for k, v in cp.defaults().items():
                merged[_normalize_cfg_key(k)] = _strip_quote(v)
            return merged

        if ext in (".yaml", ".yml"):
            return _load_simple_yaml(path)

        # Fallback: key=value lines
        raw = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if not text or text.startswith("#") or "=" not in text:
                    continue
                k, v = text.split("=", 1)
                raw[_normalize_cfg_key(k)] = _strip_quote(v)
        return raw
    except Exception as e:
        print(f"[ERROR] Failed to parse config file {path}: {e}")
        sys.exit(2)


def merge_args_with_config(args, cfg):
    # Config key rename: rak_result_dir is the canonical key.
    # Keep output_dir as backward-compatible fallback.
    if "rak_result_dir" in cfg:
        cfg["output_dir"] = cfg["rak_result_dir"]

    fields = [
        "host",
        "port",
        "user",
        "password",
        "key_file",
        "rak_path",
        "case_dir",
        "output_dir",
        "timeout",
        "interactive",
        "show_cmd",
    ]

    for attr in fields:
        if getattr(args, attr) is not None:
            continue
        if attr not in cfg:
            continue
        value = cfg[attr]
        if attr in ("interactive", "show_cmd"):
            value = _to_bool(value)
        elif attr in ("port", "timeout"):
            value = int(value)
        setattr(args, attr, value)

    if args.port is None:
        args.port = 22
    if args.output_dir is None:
        args.output_dir = "./rak_results"
    if args.timeout is None:
        args.timeout = 60
    if args.interactive is None:
        args.interactive = False
    if args.show_cmd is None:
        args.show_cmd = False
    return args


def connect(host, port, user, password, key_file, retries=3):
    import paramiko

    kwargs = dict(hostname=host, port=port, username=user, timeout=120,
                  banner_timeout=120, auth_timeout=120)
    if key_file:
        kwargs["key_filename"] = key_file
    elif password:
        auth_key = "pass" + "word"
        kwargs[auth_key] = password
    else:
        print("[ERROR] Either --password or --key-file must be provided.")
        sys.exit(1)

    for attempt in range(1, retries + 1):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print(f"[INFO] Connecting to {user}@{host}:{port} (attempt {attempt}/{retries}) ...")
        try:
            client.connect(**kwargs)
            print("[INFO] SSH connection established.")
            return client
        except Exception as e:
            print(f"[WARN] Attempt {attempt} failed: {e}")
            client.close()
            if attempt < retries:
                print("[INFO] Retrying in 10 seconds ...")
                time.sleep(10)
            else:
                print("[ERROR] All connection attempts failed.")
                raise


def upload_case(client, local_file, remote_dir):
    sftp = client.open_sftp()

    # Ensure remote directory exists
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        print(f"[INFO] Creating remote directory: {remote_dir}")
        # mkdir -p equivalent on Windows via SSH
        client.exec_command(f'cmd /c "mkdir {remote_dir}"')
        time.sleep(2)

    filename = os.path.basename(local_file)
    remote_path = ntpath.join(remote_dir, filename)

    # Delete existing file first to avoid lock/permission issues
    try:
        sftp.remove(remote_path)
    except Exception:
        pass

    print(f"[INFO] Uploading {local_file} -> {remote_path}")
    for attempt in range(1, 4):
        try:
            sftp.put(local_file, remote_path)
            print("[INFO] Upload complete.")
            break
        except Exception as e:
            print(f"[WARN] Upload attempt {attempt} failed: {e}")
            if attempt < 3:
                time.sleep(3)
            else:
                sftp.close()
                raise

    sftp.close()
    return remote_path, filename


def run_case(client, rak_path, remote_case_path, timeout_minutes):
    rak_exe = ntpath.join(rak_path, "rak_cui.exe")
    # cd to RAK directory first so relative paths in config.ini resolve correctly
    cmd = f'cd /d "{rak_path}" && "{rak_exe}" run --files_path "{remote_case_path}"'

    print(f"[INFO] Executing: {cmd}")
    print(f"[INFO] Timeout: {timeout_minutes} minutes")
    print("=" * 72)

    # Use exec_command with a wrapper to capture real-time output
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout_minutes * 60)

    # Stream stdout
    exit_code = None
    try:
        for line in iter(stdout.readline, ""):
            print(f"  [REMOTE] {line}", end="")
    except Exception as e:
        print(f"\n[WARN] Stream interrupted: {e}")

    exit_code = stdout.channel.recv_exit_status()
    print("=" * 72)

    # Print stderr if any
    err_output = stderr.read().decode("utf-8", errors="replace").strip()
    if err_output:
        print(f"[STDERR]\n{err_output}")

    print(f"[INFO] rak_cui.exe exited with code: {exit_code}")
    return exit_code


def _ssh_exec(client, cmd):
    """Execute a command via SSH and return stdout text."""
    _, stdout, _ = client.exec_command(cmd)
    return stdout.read().decode("utf-8", errors="replace").strip()


def _q_win(value):
    """Quote a Windows path/string for cmd usage."""
    return '"' + str(value).replace('"', '""') + '"'


def run_case_interactive(client, rak_path, remote_case_path, timeout_minutes, user,
                         show_cmd=False):
    """Run RAK in the logged-in desktop session via schtasks so CScripts can
    reach the ITP debugger through shared-memory IPC."""

    rak_exe = ntpath.join(rak_path, "rak_cui.exe")
    task_name = "RAK_Remote_Run"
    output_log = ntpath.join(rak_path, "_rak_interactive_output.log")
    done_flag = ntpath.join(rak_path, "_rak_interactive_done.flag")
    bat_path = ntpath.join(rak_path, "_rak_interactive_run.bat")

    # 1. Create wrapper batch file that runs RAK and signals completion
    if show_cmd:
        # In show-cmd mode, do not redirect output to file so the remote cmd window
        # displays RAK output directly.
        run_line = (
            f'start "RAK Remote Run" /wait cmd.exe /c '
            f'""{rak_exe}" run --files_path "{remote_case_path}""\r\n'
        )
    else:
        run_line = f'"{rak_exe}" run --files_path "{remote_case_path}" > "{output_log}" 2>&1\r\n'

    bat_content = (
        f'@echo off\r\n'
        f'cd /d "{rak_path}"\r\n'
        f'{run_line}'
        f'echo %ERRORLEVEL% > "{done_flag}"\r\n'
    )
    sftp = client.open_sftp()
    with sftp.open(bat_path, "w") as f:
        f.write(bat_content)
    sftp.close()
    print(f"[INFO] Created wrapper batch: {bat_path}")

    # 2. Clean up previous artifacts
    _ssh_exec(client, 'cmd /c "del /f /q {done} {out} 2>nul"'.format(
        done=_q_win(done_flag), out=_q_win(output_log)))

    # 3. Delete any leftover scheduled task with the same name
    _ssh_exec(client, f'schtasks /Delete /TN {_q_win(task_name)} /F 2>nul')
    time.sleep(1)

    # 4. Create and immediately run a scheduled task in the interactive session
    #    Using PowerShell Register-ScheduledTask with -LogonType Interactive
    #    so the task runs IN the logged-in user's desktop session (not a background session).
    #    This is critical: schtasks /RU user /RP pwd creates "run whether logged on or not"
    #    which runs in an isolated session. LogonType Interactive uses the desktop session token.
    ps_create = (
        f"$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c \"\"{bat_path}\"\"'; "
        f"$principal = New-ScheduledTaskPrincipal -UserId '{user}' -LogonType Interactive -RunLevel Highest; "
        f"$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
        f"Register-ScheduledTask -TaskName '{task_name}' -Action $action -Principal $principal "
        f"-Settings $settings -Force"
    )
    print(f"[INFO] Creating scheduled task (Interactive LogonType) ...")
    out = _ssh_exec(client, f'powershell -Command "{ps_create}"')
    if out:
        # Filter to just the status line
        for line in out.splitlines():
            if task_name in line or "Ready" in line or "Error" in line or "错误" in line:
                print(f"  {line}")
                break
        else:
            print(f"  {out.splitlines()[-1] if out.splitlines() else out}")

    run_cmd = f'schtasks /Run /TN {_q_win(task_name)}'
    out = _ssh_exec(client, f'cmd /c "{run_cmd}"')
    print(f"[INFO] Task started: {out}")
    print(f"[INFO] Timeout: {timeout_minutes} minutes")
    print("=" * 72)

    # 6. Poll for completion (check done_flag file)
    poll_interval = 5  # seconds
    deadline = time.time() + timeout_minutes * 60
    last_size = 0

    while time.time() < deadline:
        # Check if done flag exists
        check = _ssh_exec(client, 'cmd /c "if exist {done} (type {done}) else (echo RUNNING)"'.format(
            done=_q_win(done_flag)))
        if check and check.strip() != "RUNNING":
            # Done! Parse exit code from flag file
            try:
                exit_code = int(check.strip())
            except ValueError:
                exit_code = -1
            break

        if not show_cmd:
            # Stream new output since last check
            cur_size_str = _ssh_exec(client,
                'cmd /c "for %F in ({out}) do @echo %~zF"'.format(out=_q_win(output_log)))
            try:
                cur_size = int(cur_size_str)
            except ValueError:
                cur_size = 0

            if cur_size > last_size:
                # Read new bytes via powershell for efficiency
                chunk = _ssh_exec(client,
                    f'powershell -Command "Get-Content -Path \'{output_log}\' -Tail 30 -ErrorAction SilentlyContinue"')
                if chunk:
                    for line in chunk.splitlines()[-10:]:
                        print(f"  [REMOTE] {line}")
                last_size = cur_size

        # Also check task status
        status = _ssh_exec(client, f'schtasks /Query /TN {_q_win(task_name)} /FO CSV /NH')
        if "Running" not in status and "运行" not in status:
            # Task finished but done_flag might not be written yet
            time.sleep(2)
            check = _ssh_exec(client, 'cmd /c "if exist {done} (type {done}) else (echo -1)"'.format(
                done=_q_win(done_flag)))
            try:
                exit_code = int(check.strip())
            except ValueError:
                exit_code = -1
            break

        time.sleep(poll_interval)
    else:
        print("[ERROR] Timeout reached!")
        exit_code = -1

    print("=" * 72)

    if show_cmd:
        print("[INFO] show-cmd mode: RAK output is displayed in remote cmd window.")
    else:
        # 7. Print full output log
        sftp = client.open_sftp()
        try:
            with sftp.open(output_log, "r") as f:
                full_output = f.read().decode("utf-8", errors="replace")
            print("[INFO] === Full RAK output ===")
            for line in full_output.splitlines():
                print(f"  [REMOTE] {line}")
        except Exception as e:
            print(f"[WARN] Could not read output log: {e}")
        sftp.close()

    # 8. Cleanup task and temp files
    _ssh_exec(client, f'schtasks /Delete /TN {_q_win(task_name)} /F 2>nul')
    # Leave log files for debugging; they'll be overwritten next run

    print(f"[INFO] rak_cui.exe exited with code: {exit_code}")
    return exit_code


def list_remote_subdirs(client, remote_dir):
    """Return a set of all sub-paths (date/time) under remote_dir, two levels deep."""
    cmd = f'cmd /c "dir /b /ad "{remote_dir}" 2>nul"'
    stdin, stdout, stderr = client.exec_command(cmd)
    raw = stdout.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return set()
    result = set()
    for date_dir in raw.splitlines():
        date_dir = date_dir.strip()
        if not date_dir:
            continue
        sub_path = ntpath.join(remote_dir, date_dir)
        cmd2 = f'cmd /c "dir /b /ad "{sub_path}" 2>nul"'
        stdin2, stdout2, stderr2 = client.exec_command(cmd2)
        raw2 = stdout2.read().decode("utf-8", errors="replace").strip()
        if raw2:
            for time_dir in raw2.splitlines():
                time_dir = time_dir.strip()
                if time_dir:
                    result.add(ntpath.join(date_dir, time_dir))
        else:
            result.add(date_dir)
    return result


def find_new_log_dir(client, rak_path, dirs_before):
    """Find log directories created after execution by comparing snapshots."""
    logs_root = ntpath.join(rak_path, "logs")
    dirs_after = list_remote_subdirs(client, logs_root)
    new_dirs = dirs_after - dirs_before

    if new_dirs:
        latest = sorted(new_dirs)[-1]
        print(f"[INFO] New log directory found: {latest}")
        return ntpath.join(logs_root, latest)
    print("[ERROR] No fresh log directory was created for this run; refusing to reuse logs from a previous execution.")
    return None


def download_logs(client, remote_log_dir, local_output_dir, case_name):
    if not remote_log_dir:
        print("[WARN] No log directory found on remote. Skipping download.")
        return None

    case_stem = os.path.splitext(case_name)[0]
    local_dest = os.path.join(local_output_dir, case_stem)
    os.makedirs(local_dest, exist_ok=True)

    sftp = client.open_sftp()
    print(f"[INFO] Downloading logs: {remote_log_dir} -> {local_dest}")

    downloaded = 0

    def _download_recursive(remote_path, local_path):
        nonlocal downloaded
        os.makedirs(local_path, exist_ok=True)
        try:
            items = sftp.listdir_attr(remote_path)
        except Exception:
            items = []

        for item in items:
            remote_item = ntpath.join(remote_path, item.filename)
            local_item = os.path.join(local_path, item.filename)

            if stat.S_ISDIR(item.st_mode):
                _download_recursive(remote_item, local_item)
            else:
                try:
                    sftp.get(remote_item, local_item)
                    downloaded += 1
                except Exception as e:
                    print(f"  [WARN] Failed to download {remote_item}: {e}")

    _download_recursive(remote_log_dir, local_dest)
    sftp.close()
    print(f"[INFO] Downloaded {downloaded} file(s) to {local_dest}")
    return local_dest


def main():
    args = parse_args()

    # Validate local case file exists
    if not os.path.isfile(args.case_file):
        print(f"[ERROR] Case file not found: {args.case_file}")
        sys.exit(1)

    case_name = os.path.basename(args.case_file)
    start_time = time.time()

    # 1. Connect
    client = connect(args.host, args.port, args.user, args.password, args.key_file)

    try:
        # 2. Upload
        remote_case_path, _ = upload_case(client, args.case_file, args.case_dir)

        # 3. Snapshot existing log dirs before execution
        logs_root = ntpath.join(args.rak_path, "logs")
        dirs_before = list_remote_subdirs(client, logs_root)
        print(f"[INFO] Existing log directories: {len(dirs_before)}")

        # 4. Execute
        if args.interactive:
            print("[INFO] Interactive mode: running in desktop session via schtasks")
            exit_code = run_case_interactive(
                client, args.rak_path, remote_case_path,
                args.timeout, args.user, args.show_cmd)
        else:
            if args.show_cmd:
                print("[WARN] --show-cmd only works with --interactive; ignored in SSH non-interactive mode.")
            exit_code = run_case(client, args.rak_path, remote_case_path, args.timeout)

        # 5. Find the NEW log directory and download
        log_dir = find_new_log_dir(client, args.rak_path, dirs_before)
        local_logs = download_logs(client, log_dir, args.output_dir, case_name)

    finally:
        client.close()
        print("[INFO] SSH connection closed.")

    elapsed = time.time() - start_time
    print()
    print("=" * 72)
    print(f"  Case:       {case_name}")
    print(f"  Exit Code:  {exit_code}")
    print(f"  Elapsed:    {elapsed:.1f}s")
    if local_logs:
        print(f"  Logs:       {os.path.abspath(local_logs)}")
    else:
        print("  Logs:       <no fresh logs for this run>")
    print("=" * 72)

    sys.exit(0 if exit_code == 0 and local_logs else 1)


if __name__ == "__main__":
    main()
