r"""
GUI entry point for exporting BIOS knob XML.

Double-click this file on Windows to open a small form. The form can export and
program BIOS knobs through a remote debug machine, directly on the local system,
or against an offline BIOS binary image.
"""

import contextlib
import configparser
from collections import Counter
import json
import importlib
import importlib.util
import os
import queue
import re
import traceback
import shutil
import struct
import subprocess
import sys
import threading
import tempfile
import tkinter as tk
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


class SafeNullStream:
    def write(self, _text):
        return 0

    def flush(self):
        return None

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = SafeNullStream()
if sys.stderr is None:
    sys.stderr = SafeNullStream()


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, os.pardir, "rak_remote_config.ini"))
REMOTE_SYSTEM_INFO_FILE = os.path.join(SCRIPT_DIR, "remote_system_information.json")
REMOTE_SYSTEM_INFO_FALLBACK_FILE = os.path.abspath(
    os.path.join(SCRIPT_DIR, os.pardir, os.pardir, "page-resource-monitor", "remote_system_information.json")
)
SYSTEM_INFO_NODE = "__system_info__"
SYSTEM_INFO_FRONT_PAGE_FIELDS = (
    ("Firmware Version", "FirmwareVersion"),
    ("Product Name", "ProductName"),
    ("CPU Version", "CpuVersion"),
    ("CPU Speed", "CpuSpeed"),
    ("Memory Size", "MemorySize"),
)
SYSTEM_INFO_COMMENT_FIELDS = (
    "Total CPU Number",
    "CPUID",
    "Stepping",
    "MicroCodeRev",
    "PlatformID",
    "CpuCoreFreq (MHz)",
)
PYSVTOOLS_XMLCLI_HINT = (
    "This tool depends on pysvtools.xmlcli. Please set up the pysvtools.xmlcli tool in the target Python environment first, "
    "then run this operation again."
)
PYSVTOOLS_XMLCLI_INSTALL_INDEX = "https://intelpypi.intel.com/pythonsv/production"
PYSVTOOLS_XMLCLI_INSTALL_PROXY = "http://child-prc.intel.com:911"
PYSVTOOLS_XMLCLI_PACKAGE = "pysvtools.xmlcli"
PYSVTOOLS_XMLCLI_INSTALL_TIMEOUT_SECONDS = 30
PARAMIKO_INSTALL_PROXY = "http://child-prc.intel.com:913"
PARAMIKO_INSTALL_TIMEOUT_SECONDS = 120
__version__ = "0.1.0"


def _hidden_window_subprocess_kwargs():
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }

def _install_paramiko_if_missing():
    try:
        import paramiko
        return paramiko
    except ImportError:
        pass

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "paramiko",
        f"--proxy={PARAMIKO_INSTALL_PROXY}",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PARAMIKO_INSTALL_TIMEOUT_SECONDS,
            **_hidden_window_subprocess_kwargs(),
        )
    except Exception as exc:
        raise RuntimeError(f"paramiko is required for remote online BIOS knob operations, and automatic installation failed: {exc}") from exc

    if result.returncode != 0:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
        raise RuntimeError(
            "paramiko is required for remote online BIOS knob operations, but automatic installation failed.\n"
            f"Command: {' '.join(command)}\n"
            f"Exit code: {result.returncode}\n"
            f"{output}"
        )

    try:
        import paramiko
        return paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko installation completed, but the module still cannot be imported. Please restart this tool and try again.") from exc

def _strip_quote(value):
    text = str(value).strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def _normalize_cfg_key(key):
    return str(key).strip().lower().replace("-", "_")


def load_config(path):
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cp.read(path, encoding="utf-8")
    merged = {}
    for section in cp.sections():
        for key, value in cp.items(section):
            merged[_normalize_cfg_key(key)] = _strip_quote(value)
    for key, value in cp.defaults().items():
        merged[_normalize_cfg_key(key)] = _strip_quote(value)
    return merged


def connect(host, port, user_name, password):
    paramiko = _install_paramiko_if_missing()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=user_name,
        password=password,
        timeout=120,
        banner_timeout=120,
        auth_timeout=120,
    )
    return client


def _quote_cmd_arg(value):
    return '"' + str(value).replace('"', '\\"') + '"'


def _raw_string_arg(value):
    return 'r"' + str(value).replace('"', '\\"') + '"'


def _powershell_single_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _powershell_command(script):
    return f"powershell -NoProfile -ExecutionPolicy Bypass -Command {_quote_cmd_arg(script)}"


def _strip_vt_sequences(text):
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(text or ""))
    cleaned = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", cleaned)
    cleaned = cleaned.replace("\r", "")
    return cleaned


def _run_remote_command(client, command, timeout_seconds=180, log_callback=None, use_pty=True):
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds, get_pty=use_pty)
    except Exception:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
    out_text = stdout.read().decode("utf-8", errors="replace").strip()
    err_text = stderr.read().decode("utf-8", errors="replace").strip()
    exit_code = stdout.channel.recv_exit_status()
    if out_text:
        print("[STDOUT]")
        for line in out_text.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(_strip_vt_sequences(out_text) + "\n")
    if err_text:
        print("[STDERR]")
        for line in err_text.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(_strip_vt_sequences(err_text) + "\n")
    return exit_code, out_text, err_text


def _run_remote_command_streaming(client, command, timeout_seconds=180, log_callback=None, use_pty=True):
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds, get_pty=use_pty)
    except Exception:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
    channel = stdout.channel
    channel.settimeout(1.0)
    out_chunks = []
    err_chunks = []
    start_time = time.time()
    while not channel.exit_status_ready():
        _collect_remote_command_output(channel, out_chunks, err_chunks, log_callback)
        if time.time() - start_time > timeout_seconds:
            channel.close()
            timeout_message = f"Command timed out after {timeout_seconds} seconds."
            err_chunks.append(timeout_message)
            if log_callback:
                log_callback("\n" + timeout_message + "\n")
            return 1, "".join(out_chunks).strip(), "".join(err_chunks).strip()
        time.sleep(0.1)
    _collect_remote_command_output(channel, out_chunks, err_chunks, log_callback)
    exit_code = channel.recv_exit_status()
    return exit_code, "".join(out_chunks).strip(), "".join(err_chunks).strip()


def _remote_file_exists(client, remote_path, timeout_seconds=30, log_callback=None):
    command = _powershell_command(f"if (Test-Path -LiteralPath {_powershell_single_quote(remote_path)}) {{ Write-Output 'FOUND' }} else {{ Write-Output 'MISSING' }}")
    exit_code, out_text, err_text = _run_remote_command(client, command, timeout_seconds=timeout_seconds, log_callback=log_callback)
    return exit_code == 0 and "FOUND" in out_text


def _remote_temp_directory(client, timeout_seconds=30, log_callback=None):
    command = _powershell_command("Write-Output $env:TEMP")
    exit_code, out_text, err_text = _run_remote_command(client, command, timeout_seconds=timeout_seconds, log_callback=log_callback)
    temp_dir = (out_text or err_text or "").strip()
    if exit_code != 0 or not temp_dir:
        raise RuntimeError("Failed to resolve remote TEMP directory.")
    return temp_dir


def _upload_remote_file(client, local_path, remote_dir, remote_name, log_callback=None):
    remote_path = remote_dir.rstrip("\\/") + "\\" + remote_name
    if log_callback:
        log_callback(f"[INFO] Uploading BIOS binary to remote path: {remote_path}\n")
    sftp = client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
    finally:
        sftp.close()
    return remote_path


def _ensure_remote_directory(client, remote_dir, log_callback=None):
    command = _powershell_command(
        f"New-Item -ItemType Directory -Force -Path {_powershell_single_quote(remote_dir)} | Out-Null"
    )
    exit_code, out_text, err_text = _run_remote_command(client, command, timeout_seconds=30, log_callback=log_callback)
    if exit_code != 0:
        raise RuntimeError(err_text or f"Failed to prepare remote directory: {remote_dir}")


def _is_generated_metadata(value):
    return "generated" in str(value or "").lower()


def _is_missing_pysvtools_error(message):
    text = str(message or "")
    return "No module named 'pysvtools'" in text or 'No module named "pysvtools"' in text


def _is_ipc_disconnect_noise(message):
    text = str(message or "")
    return (
        "IPC_Error: Not_Connected == 0x80000007" in text
        or "A connection to the IPC API implementation has not been established" in text
        or "IPC_Disconnect" in text and "Not_Connected" in text
    )


def _is_no_device_connected_message(message):
    text = str(message or "")
    return "No device is connected!" in text or "No device is connected" in text


def _with_pysvtools_hint(message):
    text = str(message or "").strip()
    if _is_missing_pysvtools_error(text) and PYSVTOOLS_XMLCLI_HINT not in text:
        return f"{text}\n\n{PYSVTOOLS_XMLCLI_HINT}"
    return text


def _pysvtools_index_url(credentials=None):
    if not credentials:
        return PYSVTOOLS_XMLCLI_INSTALL_INDEX
    parsed = urllib.parse.urlsplit(PYSVTOOLS_XMLCLI_INSTALL_INDEX)
    user_name = urllib.parse.quote(credentials["user"], safe="")
    password = urllib.parse.quote(credentials["password"], safe="")
    netloc = f"{user_name}:{password}@{parsed.netloc}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _redact_pysvtools_credentials(text, credentials=None):
    if not text or not credentials:
        return text
    redacted = str(text)
    password = credentials.get("password", "")
    encoded_password = urllib.parse.quote(password, safe="") if password else ""
    if password:
        redacted = redacted.replace(password, "****")
    if encoded_password and encoded_password != password:
        redacted = redacted.replace(encoded_password, "****")
    return redacted


def _pysvtools_install_args(credentials=None):
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "-i",
        _pysvtools_index_url(credentials),
        PYSVTOOLS_XMLCLI_PACKAGE,
        f"--proxy={PYSVTOOLS_XMLCLI_INSTALL_PROXY}",
    ]


def _pysvtools_install_command_text():
    return (
        "pip install "
        f"-i {PYSVTOOLS_XMLCLI_INSTALL_INDEX} "
        f"{PYSVTOOLS_XMLCLI_PACKAGE} "
        f"--proxy={PYSVTOOLS_XMLCLI_INSTALL_PROXY}"
    )


def _remote_pysvtools_install_command_text():
    return "python -m " + _pysvtools_install_command_text()


def _remote_pysvtools_install_command(credentials=None):
    return (
        "python -m pip install --no-input "
        f"-i {_quote_cmd_arg(_pysvtools_index_url(credentials))} "
        f"{PYSVTOOLS_XMLCLI_PACKAGE} "
        f"--proxy={PYSVTOOLS_XMLCLI_INSTALL_PROXY}"
    )


def _install_timeout_text():
    if PYSVTOOLS_XMLCLI_INSTALL_TIMEOUT_SECONDS < 60:
        return f"{PYSVTOOLS_XMLCLI_INSTALL_TIMEOUT_SECONDS} seconds"
    return f"{PYSVTOOLS_XMLCLI_INSTALL_TIMEOUT_SECONDS // 60} minutes"


def prompt_install_pysvtools(parent, settings=None):
    remote_settings = settings if settings and settings.get("mode") == "remote" else None
    target_text = "remote system" if remote_settings else "local Python environment"
    if not messagebox.askyesno(
        "Install pysvtools.xmlcli",
        f"pysvtools.xmlcli is not available in the {target_text}.\n\n"
        "Do you want to try installing it automatically now?",
        parent=parent,
    ):
        return

    credentials = PyPiCredentialDialog(parent).show()
    if credentials is None:
        return

    command_text = _remote_pysvtools_install_command_text() if remote_settings else _pysvtools_install_command_text()
    dialog = CommandDialog(parent, "Install pysvtools.xmlcli", command_text)
    dialog.append("Running dependency installation...\n")
    dialog.append(f"Target: {target_text}\n")
    dialog.append(f"Command: {command_text}\n\n")
    dialog.append(f"This will time out after {_install_timeout_text()}.\n\n")

    def worker():
        try:
            if remote_settings:
                exit_code, out_text, err_text = install_pysvtools_remote(
                    remote_settings,
                    credentials,
                    log_callback=lambda text: parent.after(0, lambda chunk=text: dialog.append(chunk)),
                )
            else:
                exit_code, out_text, err_text = install_pysvtools_local(
                    credentials,
                    log_callback=lambda text: parent.after(0, lambda chunk=text: dialog.append(chunk)),
                )
        except subprocess.TimeoutExpired as error:
            out_text = _timeout_output_text(error.stdout)
            err_text = _timeout_output_text(error.stderr)
            if err_text:
                err_text += "\n"
            err_text += f"Installation timed out after {_install_timeout_text()}."
            parent.after(0, lambda output=out_text, error_text=err_text: _finish_pysvtools_install(dialog, 1, output, error_text))
            return
        except Exception as error:
            parent.after(0, lambda msg=str(error): _finish_pysvtools_install(dialog, 1, "", msg))
            return

        parent.after(0, lambda: _finish_pysvtools_install(dialog, exit_code, "", ""))

    threading.Thread(target=worker, daemon=True).start()


def install_pysvtools_local(credentials=None, log_callback=None):
    process = subprocess.Popen(
        _pysvtools_install_args(credentials),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_chunks = []
    reader_done = threading.Event()

    def reader():
        try:
            while True:
                chunk = process.stdout.read(1)
                if not chunk:
                    break
                chunk = _redact_pysvtools_credentials(chunk, credentials)
                output_chunks.append(chunk)
                if log_callback:
                    log_callback(chunk)
        finally:
            reader_done.set()

    threading.Thread(target=reader, daemon=True).start()

    try:
        exit_code = process.wait(timeout=PYSVTOOLS_XMLCLI_INSTALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        reader_done.wait(timeout=2)
        err_text = f"Installation timed out after {_install_timeout_text()}."
        if log_callback:
            log_callback("\n" + err_text + "\n")
        return 1, "".join(output_chunks).strip(), err_text

    reader_done.wait(timeout=2)
    return exit_code, "".join(output_chunks).strip(), ""


def _timeout_output_text(value):
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def install_pysvtools_remote(settings, credentials=None, log_callback=None):
    client = connect(settings["host"], settings["port"], settings["user"], settings["password"])
    try:
        command = _remote_pysvtools_install_command(credentials)
        stdin, stdout, stderr = client.exec_command(command, timeout=600)
        channel = stdout.channel
        channel.settimeout(1.0)
        out_chunks = []
        err_chunks = []
        start_time = time.time()
        while not channel.exit_status_ready():
            _collect_remote_install_output(channel, out_chunks, err_chunks, log_callback, credentials)
            if time.time() - start_time > PYSVTOOLS_XMLCLI_INSTALL_TIMEOUT_SECONDS:
                channel.close()
                err_chunks.append(f"Installation timed out after {_install_timeout_text()}.")
                if log_callback:
                    log_callback("\n" + err_chunks[-1] + "\n")
                return 1, "\n".join(out_chunks).strip(), "\n".join(err_chunks).strip()
            time.sleep(0.1)
        _collect_remote_install_output(channel, out_chunks, err_chunks, log_callback, credentials)
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, "\n".join(out_chunks).strip(), "\n".join(err_chunks).strip()
    finally:
        client.close()


def _collect_remote_install_output(channel, out_chunks, err_chunks, log_callback=None, credentials=None):
    while channel.recv_ready():
        chunk = channel.recv(4096).decode("utf-8", errors="replace")
        chunk = _redact_pysvtools_credentials(chunk, credentials)
        out_chunks.append(chunk)
        if log_callback:
            log_callback(chunk)
    while channel.recv_stderr_ready():
        chunk = channel.recv_stderr(4096).decode("utf-8", errors="replace")
        chunk = _redact_pysvtools_credentials(chunk, credentials)
        err_chunks.append(chunk)
        if log_callback:
            log_callback(chunk)


def _finish_pysvtools_install(dialog, exit_code, out_text, err_text):
    if out_text:
        dialog.append("[STDOUT]\n")
        dialog.append(out_text + "\n")
    if err_text:
        dialog.append("[STDERR]\n")
        dialog.append(err_text + "\n")
    if exit_code == 0:
        dialog.finish(True, "pysvtools.xmlcli was installed successfully. Please retry the previous operation.")
    else:
        dialog.finish(False, f"Failed to install pysvtools.xmlcli. pip exited with code {exit_code}.")


def run_xmlcli_export(client, remote_file, timeout_seconds=180, log_callback=None):
    inline_python = (
        "from pysvtools.xmlcli import XmlCli as cli; "
        "cli.clb._setCliAccess('ipc'); "
        f"cli.savexml(filename=r'{remote_file}')"
    )
    command = f"python -u -c {_quote_cmd_arg(inline_python)}"

    print("[INFO] Running remote XmlCli BIOS knob export ...")
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds, get_pty=True)
    except Exception:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)

    channel = stdout.channel
    channel.settimeout(1.0)
    out_chunks = []
    err_chunks = []
    start_time = time.time()

    while not channel.exit_status_ready():
        _collect_remote_command_output(channel, out_chunks, err_chunks, log_callback)
        if time.time() - start_time > timeout_seconds:
            channel.close()
            timeout_message = f"Command timed out after {timeout_seconds} seconds."
            err_chunks.append(timeout_message)
            if log_callback:
                log_callback("\n" + timeout_message + "\n")
            return 1
        time.sleep(0.1)

    _collect_remote_command_output(channel, out_chunks, err_chunks, log_callback)
    exit_code = channel.recv_exit_status()
    out_text = "".join(out_chunks).strip()
    err_text = "".join(err_chunks).strip()

    if out_text:
        print("[STDOUT]")
        for line in out_text.splitlines():
            print(f"  {line}")
    if err_text:
        print("[STDERR]")
        for line in err_text.splitlines():
            print(f"  {line}")
        if _is_missing_pysvtools_error(err_text):
            print(f"[ACTION] {PYSVTOOLS_XMLCLI_HINT}")

    print(f"[INFO] Remote command exited with code: {exit_code}")
    if exit_code != 0 and _is_missing_pysvtools_error(err_text):
        raise RuntimeError(_with_pysvtools_hint(err_text))
    return exit_code


def run_remote_xmlcli_code(client, python_code, timeout_seconds=180):
    command = f"python -c {_quote_cmd_arg(python_code)}"
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
    out_text = stdout.read().decode("utf-8", errors="replace").strip()
    err_text = stderr.read().decode("utf-8", errors="replace").strip()
    exit_code = stdout.channel.recv_exit_status()

    if out_text:
        print("[STDOUT]")
        for line in out_text.splitlines():
            print(f"  {line}")
    if err_text:
        print("[STDERR]")
        for line in err_text.splitlines():
            print(f"  {line}")
        if _is_missing_pysvtools_error(err_text):
            print(f"[ACTION] {PYSVTOOLS_XMLCLI_HINT}")
    return exit_code, out_text, err_text


def run_remote_xmlcli_code_streaming(client, python_code, log_callback=None, timeout_seconds=180):
    command = f"python -u -c {_quote_cmd_arg(python_code)}"
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds, get_pty=True)
    except Exception:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
    channel = stdout.channel
    channel.settimeout(1.0)
    out_chunks = []
    err_chunks = []
    start_time = time.time()
    while not channel.exit_status_ready():
        _collect_remote_command_output(channel, out_chunks, err_chunks, log_callback)
        if time.time() - start_time > timeout_seconds:
            channel.close()
            timeout_message = f"Command timed out after {timeout_seconds} seconds."
            err_chunks.append(timeout_message)
            if log_callback:
                log_callback("\n" + timeout_message + "\n")
            out_text = "".join(out_chunks).strip()
            err_text = "".join(err_chunks).strip()
            return 1, out_text, err_text
        time.sleep(0.1)
    _collect_remote_command_output(channel, out_chunks, err_chunks, log_callback)
    exit_code = channel.recv_exit_status()
    err_text = "".join(err_chunks).strip()
    if err_text and _is_missing_pysvtools_error(err_text) and log_callback:
        log_callback(f"\n[ACTION] {PYSVTOOLS_XMLCLI_HINT}\n")
    out_text = "".join(out_chunks).strip()
    return exit_code, out_text, err_text


def _collect_remote_command_output(channel, out_chunks, err_chunks, log_callback=None):
    while channel.recv_ready():
        chunk = channel.recv(4096).decode("utf-8", errors="replace")
        out_chunks.append(chunk)
        if log_callback:
            log_callback(chunk)
    while channel.recv_stderr_ready():
        chunk = channel.recv_stderr(4096).decode("utf-8", errors="replace")
        err_chunks.append(chunk)
        if log_callback:
            log_callback(chunk)


def _xmlcli_save_success_seen(*texts):
    return any(XMLCLI_SAVE_SUCCESS_TEXT in (text or "") for text in texts)


def _openipc_process_stop_script():
    return (
        "$before = @(Get-Process -Name OpenIPC_x64 -ErrorAction SilentlyContinue)\n"
        "Write-Output '[STEP 1] Query OpenIPC process list before kill:'\n"
        "if ($before.Count -gt 0) {\n"
        "    $before | Select-Object Id, ProcessName, Path | Format-Table -AutoSize | Out-String -Width 4096 | ForEach-Object { Write-Output $_ }\n"
        "    Write-Output '[STEP 2] Kill OpenIPC_x64.exe:'\n"
        "    Write-Output 'taskkill /IM OpenIPC_x64.exe /F /T'\n"
        "    & taskkill /IM OpenIPC_x64.exe /F /T | ForEach-Object { Write-Output $_ }\n"
        "    if ($LASTEXITCODE -eq 0) {\n"
        "        Write-Output 'OpenIPC_x64.exe terminated.'\n"
        "    } else {\n"
        "        Write-Output ('taskkill exited with code ' + $LASTEXITCODE)\n"
        "    }\n"
        "    Start-Sleep -Milliseconds 100\n"
        "} else {\n"
        "    Write-Output 'No OpenIPC process found before kill.'\n"
        "    Write-Output '[STEP 2] Skip kill because no OpenIPC process was found.'\n"
        "}\n"
        "Write-Output '[STEP 3] Query OpenIPC process list after kill:'\n"
        "$after = @(Get-Process -Name OpenIPC_x64 -ErrorAction SilentlyContinue)\n"
        "if ($after.Count -gt 0) {\n"
        "    $after | Select-Object Id, ProcessName, Path | Format-Table -AutoSize | Out-String -Width 4096 | ForEach-Object { Write-Output $_ }\n"
        "    Write-Warning 'OpenIPC process is still visible after kill; continuing because taskkill already succeeded.'\n"
        "} else {\n"
        "    Write-Output 'OpenIPC process is not running.'\n"
        "}\n"
    )


def _stop_openipc_processes_local(log_callback=None):
    if log_callback:
        log_callback("[INFO] Terminating local OpenIPC_x64.exe process if present...\n")
    script = _openipc_process_stop_script()
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    process = subprocess.run(command, capture_output=True, text=True, **_hidden_window_subprocess_kwargs())
    stdout_text = (process.stdout or "").strip()
    stderr_text = (process.stderr or "").strip()
    if stdout_text:
        print("[STDOUT]")
        for line in stdout_text.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(stdout_text + "\n")
    if stderr_text:
        print("[STDERR]")
        for line in stderr_text.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(stderr_text + "\n")
    if process.returncode != 0:
        raise RuntimeError(f"Failed to stop openipc process on the local system. PowerShell exited with code {process.returncode}.")
    if log_callback:
        log_callback("[INFO] Local OpenIPC_x64.exe termination complete.\n")
    return process.returncode


def _stop_openipc_processes_remote(client, log_callback=None, timeout_seconds=60):
    if log_callback:
        log_callback("[INFO] Terminating remote OpenIPC_x64.exe process if present...\n")
    before_command = 'cmd /d /c "tasklist | findstr /I OpenIPC"'
    kill_command = 'cmd /d /c "taskkill /IM OpenIPC_x64.exe /F /T"'

    def run_command(command):
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
        out_text = stdout.read().decode("utf-8", errors="replace").strip()
        err_text = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, out_text, err_text

    print("[STEP 1] Query OpenIPC process list before kill:")
    before_exit, before_out, before_err = run_command(before_command)
    if before_out:
        print("[STDOUT]")
        for line in before_out.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(before_out + "\n")
    if before_err:
        print("[STDERR]")
        for line in before_err.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(before_err + "\n")
    if before_exit != 0 and before_err:
        raise RuntimeError(f"Failed to query OpenIPC process list on the remote system. tasklist exited with code {before_exit}.")

    if before_out:
        print("[STEP 2] Kill OpenIPC_x64.exe:")
        kill_exit, kill_out, kill_err = run_command(kill_command)
        if kill_out:
            print("[STDOUT]")
            for line in kill_out.splitlines():
                print(f"  {line}")
            if log_callback:
                log_callback(kill_out + "\n")
        if kill_err:
            print("[STDERR]")
            for line in kill_err.splitlines():
                print(f"  {line}")
            if log_callback:
                log_callback(kill_err + "\n")
        if kill_exit != 0:
            raise RuntimeError(f"Failed to stop openipc process on the remote system. taskkill exited with code {kill_exit}.")
        time.sleep(0.1)
    else:
        print("No OpenIPC process found before kill.")
        print("[STEP 2] Skip kill because no OpenIPC process was found.")

    print("[STEP 3] Query OpenIPC process list after kill:")
    after_exit, after_out, after_err = run_command(before_command)
    if after_out:
        print("[STDOUT]")
        for line in after_out.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(after_out + "\n")
    if after_err:
        print("[STDERR]")
        for line in after_err.splitlines():
            print(f"  {line}")
        if log_callback:
            log_callback(after_err + "\n")
    if after_exit != 0 and after_err:
        raise RuntimeError(f"Failed to query OpenIPC process list after kill. tasklist exited with code {after_exit}.")
    if after_out:
        raise RuntimeError("OpenIPC process is still running after kill.")
    if log_callback:
        log_callback("[INFO] Remote OpenIPC_x64.exe termination complete.\n")
    return 0


def _stop_openipc_processes(settings, log_callback=None, client=None):
    if not settings:
        return 0
    mode = settings.get("mode")
    if mode == "remote":
        if client is not None:
            return _stop_openipc_processes_remote(client, log_callback=log_callback)
        remote_client = connect(settings["host"], settings["port"], settings["user"], settings["password"])
        try:
            return _stop_openipc_processes_remote(remote_client, log_callback=log_callback)
        finally:
            remote_client.close()
    return _stop_openipc_processes_local(log_callback=log_callback)


def _prepare_local_xmlcli_launch(log_callback=None):
    _stop_openipc_processes_local(log_callback=log_callback)


XMLCLI_SAVE_SUCCESS_TEXT = "BIOS knobs CLI Command ended successfully"


def run_local_xmlcli_export(local_file):
    _stop_openipc_processes_local()
    result_fd, result_path = tempfile.mkstemp(prefix="bios_firmware_decoder_local_export_", suffix=".json")
    os.close(result_fd)
    child_script = "\n".join([
        "import importlib.util",
        "import json",
        "import os",
        "import sys",
        f"module_path = {os.path.abspath(__file__)!r}",
        f"result_path = {result_path!r}",
        "spec = importlib.util.spec_from_file_location('bios_firmware_decoder_child', module_path)",
        "module = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(module)",
        "def stream_callback(text):",
        "    if text:",
        "        sys.__stdout__.write(text)",
        "        sys.__stdout__.flush()",
        "try:",
        f"    module._run_local_xmlcli_export_impl({local_file!r}, stream_callback)",
        "    exit_code = 0",
        "    err_text = ''",
        "except Exception as error:",
        "    exit_code = 1",
        "    err_text = str(error)",
        "with open(result_path, 'w', encoding='utf-8') as result_file:",
        "    json.dump({'exit_code': exit_code, 'err_text': err_text}, result_file)",
    ])
    try:
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", child_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
            **_hidden_window_subprocess_kwargs(),
        )
        if process.stdout is None:
            raise RuntimeError("Local XMLCLI export child process did not expose a stdout pipe.")
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                if process.poll() is not None:
                    break
                continue
            print(chunk.decode("utf-8", errors="replace"), end="")
        process.wait()
        if not os.path.exists(result_path):
            raise RuntimeError(f"Failed to export BIOS XML on the local system. Child process exited with code {process.returncode}.")
        with open(result_path, "r", encoding="utf-8") as result_file:
            result = json.load(result_file)
        exit_code = result.get("exit_code", process.returncode)
        err_text = (result.get("err_text") or "").strip()
        _stop_openipc_processes_local()
        if exit_code != 0:
            raise RuntimeError(err_text or "Failed to export BIOS XML on the local system.")
        return 0
    finally:
        try:
            os.remove(result_path)
        except OSError:
            pass


def _build_xmlcli_program_code(knob_string):
    return "; ".join([
        "from pysvtools.xmlcli import XmlCli as cli",
        "cli.clb._setCliAccess('ipc')",
        f"cli.CvProgKnobs({knob_string!r})",
    ])


def _build_xmlcli_reset_code(reset_action):
    lines = []
    if reset_action in ("cold", "warm"):
        lines.extend([
            "import ipccli",
            "ipc = ipccli.baseaccess()",
        ])
        if reset_action == "cold":
            lines.append("ipc.pulsepwrgood()")
        elif reset_action == "warm":
            lines.append("ipc.resettarget()")
    return "; ".join(lines)


def _run_local_xmlcli_export_impl(local_file, log_callback=None):
    stdout_buffer = StreamingTextBuffer(log_callback)
    stderr_buffer = StreamingTextBuffer(log_callback)
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        cli = importlib.import_module("pysvtools.xmlcli.XmlCli")

        os.makedirs(os.path.dirname(os.path.abspath(local_file)), exist_ok=True)
        print("[INFO] Running local XmlCli BIOS knob export ...")
        cli.clb._setCliAccess("ipc")
        cli.savexml(filename=local_file)
        print(f"[INFO] Local XML export complete: {local_file}")
    return 0, stdout_buffer.getvalue().strip(), stderr_buffer.getvalue().strip()


def _run_local_xmlcli_code_impl(knob_string, log_callback=None, reset_action=None):
    stdout_buffer = StreamingTextBuffer(log_callback)
    stderr_buffer = StreamingTextBuffer(log_callback)
    disconnect_noise = None
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        cli = importlib.import_module("pysvtools.xmlcli.XmlCli")

        cli.clb._setCliAccess("ipc")
        try:
            cli.CvProgKnobs(knob_string)
        except Exception as error:
            if _is_ipc_disconnect_noise(error):
                disconnect_noise = str(error)
            else:
                raise
        save_output = stdout_buffer.getvalue() + stderr_buffer.getvalue()
        if reset_action in ("cold", "warm"):
            if XMLCLI_SAVE_SUCCESS_TEXT not in save_output:
                raise RuntimeError(
                    "BIOS knobs save did not report success, so reset was skipped."
                )
            if log_callback:
                log_callback("[INFO] Save reported success; performing requested reset.\n")
            ipccli = importlib.import_module("ipccli")
            ipc = ipccli.baseaccess()
            if reset_action == "cold":
                ipc.pulsepwrgood()
            elif reset_action == "warm":
                ipc.resettarget()
    if disconnect_noise:
        stdout_text = stdout_buffer.getvalue().strip()
        stderr_text = stderr_buffer.getvalue().strip()
        if log_callback:
            log_callback("[WARN] Ignored IPC disconnect noise after programming finished successfully.\n")
        return 0, stdout_text, stderr_text
    stdout_text = stdout_buffer.getvalue().strip()
    stderr_text = stderr_buffer.getvalue().strip()
    return 0, stdout_text, stderr_text


def run_offline_xmlcli_export(local_file, bios_bin):
    core = load_bios_modify_cui()
    os.makedirs(os.path.dirname(os.path.abspath(local_file)), exist_ok=True)
    print("[INFO] Running standalone BIOS binary decode ...")
    print(f"[INFO] BIOS binary: {bios_bin}")
    result = core.decode_file(core.Path(bios_bin))
    core.write_xml(result, core.Path(local_file))
    print(f"[INFO] Offline XML export complete: {local_file}")
    print(f"[INFO] NVARs: {len(result.nvars)}")
    print(f"[INFO] Knobs: {sum(1 for nvar in result.nvars for knob in nvar.knobs if knob.processed)}")
    if result.warnings:
        print(f"[INFO] Warnings: {len(result.warnings)}")
    return 0


def bios_firmware_decoder_cui_path():
    return os.path.abspath(os.path.join(SCRIPT_DIR, "bios_firmware_decoder.py"))


def load_bios_modify_cui():
    cui_path = bios_firmware_decoder_cui_path()
    if not os.path.isfile(cui_path):
        raise RuntimeError(f"BIOS modify CUI core was not found: {cui_path}")
    module_name = "bios_firmware_decoder_core"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, cui_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load BIOS modify CUI core: {cui_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_local_xmlcli_code(knob_string, log_callback=None, reset_action=None):
    result_fd, result_path = tempfile.mkstemp(prefix="bios_firmware_decoder_local_save_", suffix=".json")
    os.close(result_fd)
    child_script = "\n".join([
        "import importlib.util",
        "import json",
        "import os",
        "import sys",
        f"module_path = {os.path.abspath(__file__)!r}",
        f"result_path = {result_path!r}",
        "spec = importlib.util.spec_from_file_location('bios_firmware_decoder_child', module_path)",
        "module = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(module)",
        "def stream_callback(text):",
        "    if text:",
        "        sys.__stdout__.write(text)",
        "        sys.__stdout__.flush()",
        "try:",
        f"    exit_code, out_text, err_text = module._run_local_xmlcli_code_impl({knob_string!r}, stream_callback, {reset_action!r})",
        "except Exception as error:",
        "    exit_code = 1",
        "    err_text = str(error)",
        "with open(result_path, 'w', encoding='utf-8') as result_file:",
        "    json.dump({'exit_code': exit_code, 'err_text': err_text}, result_file)",
    ])
    try:
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", child_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
            **_hidden_window_subprocess_kwargs(),
        )
        if process.stdout is None:
            raise RuntimeError("Local XMLCLI child process did not expose a stdout pipe.")
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                if process.poll() is not None:
                    break
                continue
            text_chunk = chunk.decode("utf-8", errors="replace")
            if log_callback:
                log_callback(text_chunk)
            else:
                print(text_chunk, end="")
        process.wait()
        if not os.path.exists(result_path):
            raise RuntimeError(f"Local XMLCLI child process failed with exit code {process.returncode}.")
        with open(result_path, "r", encoding="utf-8") as result_file:
            result = json.load(result_file)
        exit_code = result.get("exit_code", process.returncode)
        err_text = (result.get("err_text") or "").strip()
        _stop_openipc_processes_local(log_callback=log_callback)
        return exit_code, "", err_text
    finally:
        try:
            os.remove(result_path)
        except OSError:
            pass


def run_offline_xmlcli_code(knob_string, bios_bin, log_callback=None):
    stdout_buffer = StreamingTextBuffer(log_callback)
    stderr_buffer = StreamingTextBuffer(log_callback)
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        cli = importlib.import_module("pysvtools.xmlcli.XmlCli")

        cli.clb._setCliAccess("ipc")
        cli.CvProgKnobs(knob_string, BiosBin=bios_bin)
    return 0, stdout_buffer.getvalue().strip(), stderr_buffer.getvalue().strip()


def patched_bios_output_path(bios_bin, output_dir=None):
    source_dir = os.path.dirname(os.path.abspath(bios_bin))
    target_dir = output_dir or source_dir
    os.makedirs(target_dir, exist_ok=True)
    base_name = os.path.basename(bios_bin)
    stem, ext = os.path.splitext(base_name)
    if not ext:
        ext = ".bin"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(target_dir, f"{stem}_patched_{stamp}{ext}")


def run_offline_standalone_patch(knob_string, bios_bin, output_dir=None, log_callback=None):
    core = load_bios_modify_cui()
    assignments = [item.strip() for item in knob_string.split(",") if item.strip()]
    output_path = patched_bios_output_path(bios_bin, output_dir=output_dir)
    if log_callback:
        log_callback("[INFO] Running standalone BIOS binary patch ...\n")
        log_callback(f"[INFO] BIOS binary: {bios_bin}\n")
        log_callback(f"[INFO] Patched output: {output_path}\n")
    reports = core.patch_bios_file(
        core.Path(bios_bin),
        core.Path(output_path),
        assignments,
    )
    lines = ["Standalone BIOS binary patch complete.", f"Patched BIOS binary: {output_path}"]
    lines.extend(reports)
    out_text = "\n".join(lines)
    if log_callback:
        log_callback(out_text + "\n")
    return 0, out_text, ""


def program_bios_knobs(remote_settings, knob_string, log_callback=None, reset_action=None):
    python_code = _build_xmlcli_program_code(knob_string)
    client = connect(
        remote_settings["host"],
        remote_settings["port"],
        remote_settings["user"],
        remote_settings["password"],
    )
    try:
        if log_callback:
            log_callback("[INFO] Launching XmlCli environment by importing pysvtools.xmlcli.XmlCli and calling cli.clb._setCliAccess('ipc')...\n")
        exit_code, out_text, err_text = run_remote_xmlcli_code_streaming(
            client,
            python_code,
            log_callback=log_callback,
        )
        if exit_code != 0:
            return exit_code, out_text, err_text
        if reset_action in ("cold", "warm"):
            combined_output = f"{out_text}\n{err_text}"
            if XMLCLI_SAVE_SUCCESS_TEXT not in combined_output:
                raise RuntimeError(
                    "BIOS knobs save did not report success, so reset was skipped."
                )
            if log_callback:
                log_callback("[INFO] Save reported success; performing requested reset.\n")
            reset_code = _build_xmlcli_reset_code(reset_action)
            reset_exit, reset_out, reset_err = run_remote_xmlcli_code_streaming(
                client,
                reset_code,
                log_callback=log_callback,
            )
            merged_out = "\n".join(part for part in (out_text, reset_out) if part).strip()
            merged_err = "\n".join(part for part in (err_text, reset_err) if part).strip()
            return reset_exit, merged_out, merged_err
        return exit_code, out_text, err_text
    finally:
        client.close()


def program_bios_knobs_local(knob_string, log_callback=None, reset_action=None):
    return run_local_xmlcli_code(knob_string, log_callback=log_callback, reset_action=reset_action)


def program_bios_knobs_offline(knob_string, bios_bin, output_dir=None, log_callback=None):
    return run_offline_standalone_patch(knob_string, bios_bin, output_dir=output_dir, log_callback=log_callback)


def _remove_file_if_exists(path, log_callback=None):
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    except OSError as error:
        if log_callback:
            log_callback(f"[WARN] Failed to remove temporary file {path}: {error}\n")
        return False
    if log_callback:
        log_callback(f"[INFO] Removed temporary file: {path}\n")
    return True


def download_file(client, remote_file, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"BIOS_Knob_{stamp}.xml")

    log_remote_file_status(client, remote_file, "before download")
    print(f"[INFO] Downloading {remote_file} -> {output_file}")
    sftp = client.open_sftp()
    try:
        sftp.get(remote_file, output_file)
    finally:
        sftp.close()
    print("[INFO] Download complete.")
    log_remote_file_status(client, remote_file, "after download")
    with contextlib.suppress(Exception):
        client.exec_command(
            f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath \'{remote_file}\' -Force -ErrorAction SilentlyContinue"',
            timeout=30,
        )
    return output_file


def resolve_option_text(options, value):
    option = find_option_by_value(options, value)
    return option.get("text", "") if option else ""


def find_option_by_value(options, value):
    normalized_value = _normalize_int_text(value)
    for option in options:
        option_value = option.get("value", "")
        if option_value.lower() == str(value).lower() or _normalize_int_text(option_value) == normalized_value:
            return option
    return None


def _parse_xml_comment_kv(text):
    match = re.match(r"^\s*([^:]+?)\s*:\s*(.*?)\s*:\s*$", text or "")
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def collect_system_information(root, front_page):
    system_info = []
    if front_page is not None:
        for label, attr_name in SYSTEM_INFO_FRONT_PAGE_FIELDS:
            value = front_page.get(attr_name, "")
            if value and not _is_generated_metadata(value):
                system_info.append({"name": label, "value": value, "source": "FrontPage"})

    wanted_comment_fields = set(SYSTEM_INFO_COMMENT_FIELDS)
    found_comment_fields = set()
    biosknobs = root.find("biosknobs")
    if biosknobs is not None:
        for child in list(biosknobs):
            if child.tag is not ET.Comment:
                if str(child.tag).lower() == "knob":
                    break
                continue
            name, value = _parse_xml_comment_kv((child.text or "").strip())
            if name in wanted_comment_fields and name not in found_comment_fields:
                system_info.append({"name": name, "value": value, "source": "CPU Information"})
                found_comment_fields.add(name)
                if len(found_comment_fields) == len(wanted_comment_fields):
                    break

    return system_info


def parse_bios_knob_xml(xml_path):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.parse(xml_path, parser=parser).getroot()

    bios = root.find("BIOS")
    platform = root.find("PLATFORM")
    front_page = root.find("FrontPage")
    gbt = root.find("GBT")
    meta = root.find("BIOS_KNOBS_DATA_BIN")
    decode_type = ""
    if meta is not None and meta.get("decodeType"):
        decode_type = meta.get("decodeType", "")
    elif gbt is not None and gbt.get("Type"):
        decode_type = gbt.get("Type", "")
    if decode_type == "HII_IFR_ONLY":
        decode_type = "HII/IFR-only fallback"
    metadata = {
        "xml_path": xml_path,
        "bios_version": bios.get("VERSION", "") if bios is not None else "",
        "platform": platform.get("NAME", "") if platform is not None else "",
        "product": front_page.get("ProductName", "") if front_page is not None else "",
        "cpu": front_page.get("CpuVersion", "") if front_page is not None else "",
        "memory": front_page.get("MemorySize", "") if front_page is not None else "",
        "decode_type": decode_type,
        "system_info": collect_system_information(root, front_page),
    }

    biosknobs = root.find("biosknobs") or root
    current_form_set = "BIOS Setup"
    current_form = "General"
    knobs = []

    def is_gui_hidden_knob(node):
        prompt = node.get("prompt", "")
        name = node.get("name", "")
        return (
            node.get("Nvar", "").startswith("UndecodedVarStore")
            or re.fullmatch(r"Question_0x[0-9A-Fa-f]{4}", prompt or "") is not None
            or name.startswith("Question_0x")
        )

    for child in list(biosknobs):
        if child.tag is ET.Comment:
            text = (child.text or "").strip()
            if text.startswith("Form Set:"):
                current_form_set = text.split(":", 1)[1].strip() or current_form_set
                current_form = "General"
            elif text.startswith("Form:"):
                current_form = text.split(":", 1)[1].strip() or current_form
            continue

        if str(child.tag).lower() != "knob":
            continue
        if is_gui_hidden_knob(child):
            continue

        options = []
        options_node = child.find("options")
        if options_node is not None:
            for option_node in options_node.findall("option"):
                options.append({
                    "text": option_node.get("text", ""),
                    "value": option_node.get("value", ""),
                })

        current_value = child.get("CurrentVal", child.get("currentVal", ""))
        default_value = child.get("default", "")
        knobs.append({
            "form_set": current_form_set,
            "form": current_form,
            "name": child.get("name", child.tag),
            "prompt": child.get("prompt", child.get("name", child.tag)),
            "description": child.get("description", ""),
            "setup_page": child.get("SetupPgPtr", ""),
            "setup_type": child.get("setupType", ""),
            "type": child.get("type", ""),
            "current_value": current_value,
            "current_text": resolve_option_text(options, current_value),
            "default_value": default_value,
            "default_text": resolve_option_text(options, default_value),
            "current_available": child.get("currentAvailable", "true").lower() != "false",
            "default_available": child.get("defaultAvailable", "true").lower() != "false",
            "value_source": child.get("valueSource", ""),
            "nvar": child.get("Nvar", ""),
            "nvar_guid": child.get("NvarGuid", ""),
            "offset": child.get("offset", ""),
            "varstore": child.get("varstoreIndex", ""),
            "size": child.get("size", ""),
            "min": child.get("min", ""),
            "max": child.get("max", ""),
            "step": child.get("step", ""),
            "depex": child.get("depex", ""),
            "options": options,
        })

    if not knobs:
        for knob in root.iter("knob"):
            if is_gui_hidden_knob(knob):
                continue
            current_value = knob.get("CurrentVal", knob.get("currentVal", ""))
            options = [
                {"text": option.get("text", ""), "value": option.get("value", "")}
                for option in knob.findall("./options/option")
            ]
            knobs.append({
                "form_set": "BIOS Setup",
                "form": "General",
                "name": knob.get("name", knob.tag),
                "prompt": knob.get("prompt", knob.get("name", knob.tag)),
                "description": knob.get("description", ""),
                "setup_page": knob.get("SetupPgPtr", ""),
                "setup_type": knob.get("setupType", ""),
                "type": knob.get("type", ""),
                "current_value": current_value,
                "current_text": resolve_option_text(options, current_value),
                "default_value": knob.get("default", ""),
                "default_text": resolve_option_text(options, knob.get("default", "")),
                "current_available": knob.get("currentAvailable", "true").lower() != "false",
                "default_available": knob.get("defaultAvailable", "true").lower() != "false",
                "value_source": knob.get("valueSource", ""),
                "nvar": knob.get("Nvar", ""),
                "nvar_guid": knob.get("NvarGuid", ""),
                "offset": knob.get("offset", ""),
                "varstore": knob.get("varstoreIndex", ""),
                "size": knob.get("size", ""),
                "min": knob.get("min", ""),
                "max": knob.get("max", ""),
                "step": knob.get("step", ""),
                "depex": knob.get("depex", ""),
                "options": options,
            })

    return metadata, knobs


def _normalize_int_text(value):
    text = str(value).strip()
    if not text:
        return ""
    try:
        return str(int(text, 0))
    except ValueError:
        return text


def format_knob_width(size_text, offset_text=""):
    text = str(size_text or "").strip()
    if not text:
        return ""
    try:
        value = int(text, 0)
    except ValueError:
        return text
    if value <= 0:
        return text
    try:
        offset_value = int(str(offset_text or "").strip(), 0)
    except ValueError:
        offset_value = 0
    if offset_value >= 0xC0000:
        return f"{value} bit(s)"
    return f"{value} byte(s) / {value * 8} bit(s)"


def _parse_int_value(value):
    text = str(value).strip()
    if not text:
        raise ValueError("empty value")
    return int(text, 0)


def _eval_dependency_clause(clause, current_values):
    list_match = re.match(
        r"^\s*_LIST_\s+([A-Za-z_][A-Za-z0-9_]*)\s+_(EQU|NEQ)_\s+(.+?)\s*$",
        clause,
    )
    if list_match:
        knob_name, operator, expected_values_text = list_match.groups()
        actual = current_values.get(knob_name)
        if actual is None:
            return None
        expected_values = expected_values_text.split()
        try:
            actual_int = _parse_int_value(actual)
            expected_ints = [_parse_int_value(value) for value in expected_values]
            matched = actual_int in expected_ints
        except ValueError:
            normalized_actual = _normalize_int_text(actual)
            matched = normalized_actual in {_normalize_int_text(value) for value in expected_values}
        if operator == "EQU":
            return matched
        if operator == "NEQ":
            return not matched
        return None

    match = re.match(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+_(EQU|NEQ|LTE|GTE|LT|GT)_\s+([A-Za-z0-9_xXa-fA-F]+)\s*$",
        clause,
    )
    if not match:
        return None
    knob_name, operator, expected = match.groups()
    actual = current_values.get(knob_name)
    if actual is None:
        return None
    try:
        actual_int = _parse_int_value(actual)
        expected_int = _parse_int_value(expected)
    except ValueError:
        if operator == "EQU":
            return _normalize_int_text(actual) == _normalize_int_text(expected)
        if operator == "NEQ":
            return _normalize_int_text(actual) != _normalize_int_text(expected)
        return None

    if operator == "EQU":
        return actual_int == expected_int
    if operator == "NEQ":
        return actual_int != expected_int
    if operator == "LTE":
        return actual_int <= expected_int
    if operator == "GTE":
        return actual_int >= expected_int
    if operator == "LT":
        return actual_int < expected_int
    if operator == "GT":
        return actual_int > expected_int
    return None


def _combine_dependency_values(left, operator, right):
    if operator is None:
        return right
    if operator == "AND":
        if left is False or right is False:
            return False
        if left is True and right is True:
            return True
        return None
    if operator == "OR":
        if left is True or right is True:
            return True
        if left is False and right is False:
            return False
        return None
    return right


def dependency_blocks_edit(depex, current_values):
    text = str(depex or "").strip()
    if not text or text.upper() == "TRUE":
        return False, ""

    expression = re.sub(r"\b[GS]if\s*\(", "(", text)
    expression = expression.replace("_AND_", "AND").replace("_OR_", "OR")
    parts = re.split(r"\s+(AND|OR)\s+", expression)
    result = None
    operator = None
    has_clause = False
    ignored = []

    for part in parts:
        part = part.strip().strip("() ")
        if not part:
            continue
        if part in ("AND", "OR"):
            operator = part
            continue

        value = _eval_dependency_clause(part, current_values)
        if value is None:
            ignored.append(part)
        if not has_clause:
            result = value
        else:
            result = _combine_dependency_values(result, operator, value)
        has_clause = True

    if result:
        return True, f"Dependency active: {text}"
    if ignored:
        return False, f"Dependency not fully evaluated; ignored: {', '.join(ignored)}"
    return False, ""


def log_remote_file_status(client, remote_file, label):
    sftp = client.open_sftp()
    try:
        attrs = sftp.stat(remote_file)
        print(f"[INFO] Remote XML exists {label}: {remote_file} ({attrs.st_size} bytes)")
    except Exception as error:
        print(f"[WARN] Remote XML not found {label}: {remote_file} ({error})")
    finally:
        sftp.close()


class BiosSetupViewer:
    TREE_INSERT_BATCH_SIZE = 250
    SEARCH_DEBOUNCE_MS = 200

    def __init__(
        self,
        parent,
        xml_path,
        target_settings_getter=None,
        metadata=None,
        knobs=None,
        start_hidden=False,
        on_ready=None,
        defer_load=False,
        embedded=False,
        show_toolbar_actions=True,
        show_setup_menu=True,
    ):
        self.embedded = embedded
        self.show_toolbar_actions = show_toolbar_actions
        self.show_setup_menu = show_setup_menu
        if embedded:
            self.window = ttk.Frame(parent, style="BiosViewer.TFrame")
            self.window.pack(fill=tk.BOTH, expand=True)
        else:
            self.window = tk.Toplevel(parent)
            if start_hidden:
                self.window.withdraw()
            self.window.title("BIOS Setup Viewer")
            self.window.geometry("1180x720")
            self.window.minsize(980, 580)
            if not start_hidden:
                self.show()

        self.parent = parent
        self.target_settings_getter = target_settings_getter
        if defer_load:
            self.metadata = metadata or {"xml_path": xml_path, "product": "BIOS Setup"}
            self.knobs = []
        elif metadata is None or knobs is None:
            self.metadata, self.knobs = parse_bios_knob_xml(xml_path)
        else:
            self.metadata, self.knobs = metadata, knobs
        self._display_name_counts = Counter()
        self._refresh_display_name_counts()
        self.filtered_knobs = list(self.knobs)
        self.visible_knobs = []
        self.search_var = tk.StringVar(value="")
        self.category_map = {}
        self.category_node_by_key = {}
        self.pending_changes = {}
        self.selected_knob = None
        self.option_value_var = tk.StringVar(value="")
        self.edit_status_var = tk.StringVar(value="Select an option to edit")
        self.loading_status_var = tk.StringVar(value="")
        self.title_var = tk.StringVar(value="")
        self.subtitle_var = tk.StringVar(value="")
        self.command_dialog = None
        self._populate_token = 0
        self._populate_current_values = {}
        self._loading = False
        self._suppress_category_event = False
        self._search_filter_after_id = None

        self._configure_style()
        self._build_ui()
        self._refresh_header()
        if defer_load:
            self._populate_categories()
            self._set_loading(True, 0, "Loading BIOS knob XML...")
        else:
            self._populate_categories()
            self._apply_filter(on_complete=on_ready, show_loading=True)

    def show(self):
        if self.embedded:
            return
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def load_parsed_xml(self, metadata, knobs, on_complete=None):
        self.metadata = metadata
        self.knobs = knobs
        self._refresh_display_name_counts()
        self.filtered_knobs = list(self.knobs)
        self.visible_knobs = []
        self.pending_changes.clear()
        self._refresh_header()
        self._populate_categories()
        self._loading = False
        self._apply_filter(on_complete=on_complete, show_loading=True)

    def load_failed(self, message):
        self._set_loading(False)
        messagebox.showerror("BIOS Setup Viewer", f"Failed to open BIOS XML:\n{message}", parent=self.window)

    def _refresh_header(self):
        title = next(
            (
                item for item in (
                    self.metadata.get("product"),
                    self.metadata.get("platform"),
                ) if item and not _is_generated_metadata(item)
            ),
            "BIOS Setup",
        )
        subtitle_items = [
            self.metadata.get("decode_type"),
        ]
        subtitle_items.extend(
            item for item in (
                self.metadata.get("bios_version"),
                self.metadata.get("cpu"),
                self.metadata.get("memory"),
            ) if item and not _is_generated_metadata(item)
        )
        subtitle = " | ".join(item for item in subtitle_items if item and not _is_generated_metadata(item))
        self.title_var.set(title)
        self.subtitle_var.set(subtitle)

    def _configure_style(self):
        self.colors = {
            "background": "#eef3f8",
            "panel": "#ffffff",
            "panel_alt": "#f7f9fc",
            "border": "#d7e0ea",
            "text": "#1f2937",
            "muted": "#5f6b7a",
            "accent": "#0f6cbd",
            "accent_dark": "#0b4f8a",
            "locked": "#8a94a3",
            "changed": "#005a9e",
        }
        with contextlib.suppress(tk.TclError):
            self.window.configure(bg=self.colors["background"])
        style = ttk.Style(self.window)
        with contextlib.suppress(tk.TclError):
            style.theme_use("clam")

        style.configure("BiosViewer.TFrame", background=self.colors["background"])
        style.configure("BiosPanel.TFrame", background=self.colors["panel"])
        style.configure("BiosToolbar.TFrame", background=self.colors["background"])
        style.configure("Bios.TLabel", background=self.colors["panel"], foreground=self.colors["text"])
        style.configure("BiosTitle.TLabel", background=self.colors["background"], foreground=self.colors["text"], font=("Segoe UI", 15, "bold"))
        style.configure("BiosSubtitle.TLabel", background=self.colors["background"], foreground=self.colors["muted"])
        style.configure("BiosMuted.TLabel", background=self.colors["panel"], foreground=self.colors["muted"])
        style.configure("BiosStatus.TLabel", background=self.colors["background"], foreground=self.colors["muted"])
        style.configure("Bios.TLabelframe", background=self.colors["panel"], bordercolor=self.colors["border"], relief="solid")
        style.configure("Bios.TLabelframe.Label", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 9, "bold"))
        style.configure("Bios.TButton", padding=(10, 5), background=self.colors["accent"], foreground="#ffffff")
        style.map("Bios.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])
        style.configure("BiosSmall.TButton", padding=(6, 2), background=self.colors["accent"], foreground="#ffffff")
        style.map("BiosSmall.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])
        style.configure("Accent.TButton", padding=(12, 5), background=self.colors["accent"], foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])
        style.configure("BiosCompactAccent.TButton", padding=(4, 1), background=self.colors["accent"], foreground="#ffffff")
        style.map("BiosCompactAccent.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])
        style.configure("Bios.Treeview", background=self.colors["panel"], fieldbackground=self.colors["panel"], foreground=self.colors["text"], rowheight=25, bordercolor=self.colors["border"], borderwidth=1)
        style.configure("Bios.Treeview.Heading", background="#dbe8f5", foreground=self.colors["text"], font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Bios.Treeview", background=[("selected", self.colors["accent"])], foreground=[("selected", "#ffffff")])
        style.configure("Bios.TCombobox", fieldbackground=self.colors["panel"], background=self.colors["panel"], foreground=self.colors["text"])
        style.configure("BiosInlineCurrent.TCombobox", fieldbackground="#d8ecff", background="#d8ecff", foreground=self.colors["text"])
        style.configure("BiosInlineCurrent.TEntry", fieldbackground="#d8ecff", background="#d8ecff", foreground=self.colors["text"])
        style.map(
            "Bios.TCombobox",
            fieldbackground=[("disabled", "#e5eaf0"), ("readonly", self.colors["panel"])],
            background=[("disabled", "#e5eaf0"), ("readonly", self.colors["panel"])],
            foreground=[("disabled", self.colors["locked"]), ("readonly", self.colors["text"])],
        )
        style.map(
            "BiosInlineCurrent.TCombobox",
            fieldbackground=[("readonly", "#d8ecff"), ("focus", "#d8ecff")],
            background=[("readonly", "#d8ecff"), ("focus", "#d8ecff")],
            foreground=[("readonly", self.colors["text"]), ("focus", self.colors["text"])],
        )
        style.map(
            "BiosInlineCurrent.TEntry",
            fieldbackground=[("focus", "#d8ecff")],
            foreground=[("focus", self.colors["text"])],
        )

    def _build_ui(self):
        root = ttk.Frame(self.window, padding=0 if self.embedded else 12, style="BiosViewer.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        if not self.embedded:
            ttk.Label(root, textvariable=self.title_var, style="BiosTitle.TLabel").pack(anchor=tk.W)
            ttk.Label(root, textvariable=self.subtitle_var, style="BiosSubtitle.TLabel").pack(anchor=tk.W, pady=(0, 10))

        self.save_button = None
        self.save_cold_reset_button = None
        self.save_warm_reset_button = None
        self.load_default_button = None
        if self.show_toolbar_actions:
            toolbar = ttk.Frame(root, style="BiosToolbar.TFrame")
            toolbar.pack(fill=tk.X, pady=(0, 8))
            self.load_default_button = ttk.Button(toolbar, text="Load Default", command=self._load_defaults, style="Bios.TButton")
            self.load_default_button.pack(side=tk.LEFT)
            self.save_button = ttk.Button(toolbar, text="Save", command=self._save_changes, style="Accent.TButton")
            self.save_button.pack(side=tk.LEFT, padx=(8, 0))
            self.save_cold_reset_button = ttk.Button(toolbar, text="Save and Cold Reset", command=lambda: self._save_changes(reset_action="cold"), style="Bios.TButton")
            self.save_cold_reset_button.pack(side=tk.LEFT, padx=(8, 0))
            self.save_warm_reset_button = ttk.Button(toolbar, text="Save and Warm Reset", command=lambda: self._save_changes(reset_action="warm"), style="Bios.TButton")
            self.save_warm_reset_button.pack(side=tk.LEFT, padx=(8, 0))
            self.pending_var = tk.StringVar(value="No pending changes")
            ttk.Label(toolbar, textvariable=self.pending_var, style="BiosStatus.TLabel").pack(side=tk.RIGHT)
        else:
            self.pending_var = tk.StringVar(value="No pending changes")

        body = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body, padding=(0, 0, 8, 0), style="BiosViewer.TFrame")
        right = ttk.Frame(body, style="BiosViewer.TFrame")
        if self.show_setup_menu:
            body.add(left, weight=1)
        body.add(right, weight=4)

        if self.show_setup_menu:
            ttk.Label(left, text="Setup Menu", style="BiosSubtitle.TLabel").pack(anchor=tk.W)
        category_frame = ttk.Frame(left, style="BiosViewer.TFrame")
        if self.show_setup_menu:
            category_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.category_tree = ttk.Treeview(category_frame, show="tree", selectmode="browse", style="Bios.Treeview")
        category_scrollbar = ttk.Scrollbar(category_frame, orient=tk.VERTICAL, command=self.category_tree.yview)
        self.category_tree.configure(yscrollcommand=category_scrollbar.set)
        if self.show_setup_menu:
            self.category_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            category_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.category_tree.bind("<<TreeviewSelect>>", self._on_category_selected)

        top_bar = ttk.Frame(right, style="BiosViewer.TFrame")
        top_bar.pack(fill=tk.X)
        ttk.Label(top_bar, text="Search", style="BiosSubtitle.TLabel").pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(top_bar, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        self.search_entry.bind("<KeyRelease>", self._schedule_search_filter)
        self.clear_button = ttk.Button(top_bar, text="Clear", command=self._clear_search, style="Bios.TButton")
        self.clear_button.pack(side=tk.LEFT)
        if not self.show_toolbar_actions:
            ttk.Label(top_bar, textvariable=self.pending_var, style="BiosStatus.TLabel").pack(side=tk.RIGHT, padx=(8, 0))

        self.loading_panel = ttk.Frame(right, padding=(10, 8), style="BiosPanel.TFrame")
        self.loading_panel.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(self.loading_panel, textvariable=self.loading_status_var, style="BiosMuted.TLabel").pack(side=tk.LEFT)
        self.loading_progress = ttk.Progressbar(self.loading_panel, mode="determinate")
        self.loading_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        self.loading_panel.pack_forget()

        columns = ("prompt", "current", "default", "name")
        self.knob_tree_frame = ttk.Frame(right, style="BiosViewer.TFrame")
        self.knob_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 8))
        self.knob_tree = ttk.Treeview(self.knob_tree_frame, columns=columns, show="headings", selectmode="browse", style="Bios.Treeview")
        self._configure_knob_tree_for_options()
        self.knob_scrollbar = ttk.Scrollbar(self.knob_tree_frame, orient=tk.VERTICAL, command=self._scroll_knob_tree_y)
        self.knob_tree.configure(yscrollcommand=self._on_knob_tree_yscroll)
        self.knob_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.knob_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.knob_tree.bind("<<TreeviewSelect>>", self._on_knob_selected)
        self.knob_tree.bind("<ButtonRelease-1>", self._on_knob_tree_click)
        self.knob_tree.bind("<Configure>", lambda _event: self._schedule_current_cell_refresh())
        self.knob_tree.bind("<MouseWheel>", lambda _event: self._schedule_current_cell_refresh())
        self.knob_tree.tag_configure("locked", foreground=self.colors["locked"], background="#f3f5f8")
        self.knob_tree.tag_configure("editable", foreground=self.colors["text"])
        self.knob_tree.tag_configure("changed", foreground=self.colors["text"], background="#fff2b8")
        self.current_cell_widgets = {}
        self._current_cell_refresh_pending = False
        self.inline_item = None
        self.inline_knob = None
        self.option_combo = ttk.Combobox(self.knob_tree_frame, textvariable=self.option_value_var, state="disabled", style="BiosInlineCurrent.TCombobox")
        self.option_combo.bind("<<ComboboxSelected>>", self._apply_inline_change)
        self.option_combo.bind("<Return>", self._apply_inline_change)
        self.option_combo.bind("<Escape>", lambda _event: self._hide_inline_editor())
        self.option_combo.bind("<FocusOut>", self._apply_inline_focus_out)
        self.apply_button = None

        self.detail_frame = ttk.LabelFrame(right, text="Selected Option", style="Bios.TLabelframe")
        self.detail_frame.pack(fill=tk.X)
        self.detail_header = ttk.Frame(self.detail_frame, style="BiosViewer.TFrame")
        self.detail_header.pack(fill=tk.X, padx=8, pady=(8, 0))
        self.detail_name_var = tk.StringVar(value="Name: N/A")
        ttk.Label(self.detail_header, textvariable=self.detail_name_var, style="Bios.TLabel").pack(side=tk.LEFT)
        self.goto_button = None
        if not self.embedded:
            self.goto_button = ttk.Button(self.detail_header, text="Go to", command=self._jump_to_selected_knob, style="BiosCompactAccent.TButton")
            self.goto_button.pack(side=tk.LEFT, padx=(4, 0))
            self.goto_button.configure(state=tk.DISABLED)
        self.detail_text = tk.Text(self.detail_frame, height=9, wrap=tk.WORD)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scrollbar = ttk.Scrollbar(self.detail_frame, command=self.detail_text.yview)
        detail_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.detail_text.configure(yscrollcommand=detail_scrollbar.set)
        self.detail_text.configure(
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief=tk.FLAT,
            borderwidth=1,
            padx=8,
            pady=6,
            font=("Consolas", 9),
        )

        self.footer_frame = ttk.Frame(root, style="BiosToolbar.TFrame")
        self.footer_frame.pack(fill=tk.X, pady=(8, 0))
        self.count_var = tk.StringVar(value="")
        ttk.Label(self.footer_frame, textvariable=self.count_var, style="BiosStatus.TLabel").pack(side=tk.LEFT)
        ttk.Button(self.footer_frame, text="Open XML Folder", command=self._open_xml_folder, style="Bios.TButton").pack(side=tk.RIGHT)

    def _show_detail_frame(self):
        if not self.detail_frame.winfo_ismapped():
            self.detail_frame.pack(fill=tk.X)

    def _configure_knob_tree_for_options(self):
        headings = {
            "prompt": "BIOS Knob Name",
            "current": "Current (Click to Edit)",
            "default": "Default",
            "name": "Knob Name",
        }
        widths = {
            "prompt": 360,
            "current": 180,
            "default": 180,
            "name": 260,
        }
        self.knob_tree.configure(displaycolumns=("prompt", "current", "default"))
        for column in ("prompt", "current", "default", "name"):
            self.knob_tree.heading(column, text=headings[column], anchor=tk.W)
            self.knob_tree.column(column, width=widths[column], anchor=tk.W)

    def _configure_knob_tree_for_system_info(self):
        self.knob_tree.configure(displaycolumns=("prompt", "current"))
        self.knob_tree.heading("prompt", text="Item", anchor=tk.W)
        self.knob_tree.heading("current", text="Value", anchor=tk.W)
        self.knob_tree.column("prompt", width=260, anchor=tk.W)
        self.knob_tree.column("current", width=620, anchor=tk.W)

    def _populate_categories(self):
        self.category_tree.delete(*self.category_tree.get_children())
        self.category_map = {}
        self.category_node_by_key = {}
        all_id = self.category_tree.insert("", tk.END, text="All BIOS Options", open=True, values=("__all__",))
        self.category_map[all_id] = (None, None)
        self.category_node_by_key[(None, None)] = all_id
        system_info_id = self.category_tree.insert("", tk.END, text="System Information", open=True, values=(SYSTEM_INFO_NODE,))
        self.category_map[system_info_id] = (SYSTEM_INFO_NODE, None)

        form_sets = {}
        form_keys = set()
        for knob in self.knobs:
            form_set = knob["form_set"] or "BIOS Setup"
            form = knob["form"] or "General"
            if form_set not in form_sets:
                node_id = self.category_tree.insert(all_id, tk.END, text=form_set, open=False)
                form_sets[form_set] = node_id
                self.category_map[node_id] = (form_set, None)
                self.category_node_by_key[(form_set, None)] = node_id
            form_key = (form_set, form)
            if form_key not in form_keys:
                form_id = self.category_tree.insert(form_sets[form_set], tk.END, text=form, open=False)
                self.category_map[form_id] = form_key
                self.category_node_by_key[form_key] = form_id
                form_keys.add(form_key)

        self.category_tree.selection_set(all_id)

    def _selected_category(self):
        selected = self.category_tree.selection()
        if not selected:
            return None, None
        return self.category_map.get(selected[0], (None, None))

    def _on_category_selected(self, _event=None):
        if self._loading:
            return
        if self._suppress_category_event:
            return
        if self._is_system_information_selected():
            self._show_system_information()
            return
        self._apply_filter()

    def _is_system_information_selected(self):
        form_set, _form = self._selected_category()
        return form_set == SYSTEM_INFO_NODE

    def _show_system_information(self):
        self.filtered_knobs = []
        self.visible_knobs = []
        self._populate_token += 1
        self._configure_knob_tree_for_system_info()
        self._clear_current_cell_widgets()
        self.knob_tree.delete(*self.knob_tree.get_children())
        self.detail_text.delete("1.0", tk.END)
        self.detail_frame.pack_forget()
        self._clear_editor()

        system_info = self.metadata.get("system_info", [])
        for index, item in enumerate(system_info):
            self.knob_tree.insert("", tk.END, iid=f"sysinfo-{index}", values=(
                item.get("name", ""),
                item.get("value", ""),
                item.get("source", ""),
                "System Information",
            ))

        if system_info:
            details = [f"{item.get('name', '')}: {item.get('value', '')}" for item in system_info]
            self.detail_text.insert(tk.END, "\n".join(details))
            self.count_var.set(f"Showing {len(system_info)} system information item(s)")
        else:
            self.detail_text.insert(tk.END, "No system information fields found in this XML.")
            self.count_var.set("No system information found")

    def _clear_search(self):
        if self._loading:
            return
        self._cancel_scheduled_search_filter()
        self.search_var.set("")
        if self._is_system_information_selected():
            self._show_system_information()
            return
        self._apply_filter()

    def _cancel_scheduled_search_filter(self):
        if self._search_filter_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self._search_filter_after_id)
            self._search_filter_after_id = None

    def _schedule_search_filter(self, _event=None):
        if self._loading:
            return
        self._cancel_scheduled_search_filter()
        self._search_filter_after_id = self.window.after(self.SEARCH_DEBOUNCE_MS, self._run_scheduled_search_filter)

    def _run_scheduled_search_filter(self):
        self._search_filter_after_id = None
        if self._loading:
            return
        self._apply_filter()

    def _display_value(self, knob, value_key, text_key):
        if value_key == "default_value" and not knob.get("default_available", True):
            return "N/A"
        if value_key == "current_value" and not knob.get("current_available", True):
            return "N/A"
        value = knob.get(value_key, "")
        text = knob.get(text_key, "")
        if value == "":
            return "N/A"
        option = find_option_by_value(knob.get("options", []), value)
        if option:
            text = option.get("text", "") or text
            value = option.get("value", value)
        if text:
            return f"{text}({value})"
        return value

    def _refresh_display_name_counts(self):
        self._display_name_counts = Counter(self._base_display_knob_name(knob).casefold() for knob in self.knobs)
        display_names = {}
        name_counts = Counter()
        for knob in self.knobs:
            base_name = self._base_display_knob_name(knob)
            display_name = base_name
            if self._display_name_counts[base_name.casefold()] > 1:
                display_name = self._display_name_from_setup_page(knob) or display_name
            suffix = self._display_name_suffix(knob)
            unique_name = display_name
            while name_counts[unique_name.casefold()] > 0:
                if suffix and not unique_name.casefold().endswith(f"_{suffix}".casefold()):
                    unique_name = f"{display_name}_{suffix}"
                else:
                    unique_name = f"{display_name}_{name_counts[display_name.casefold()] + 1}"
            name_counts[unique_name.casefold()] += 1
            display_names[self._knob_identity(knob)] = unique_name
        self._display_name_by_identity = display_names

    def _base_display_knob_name(self, knob):
        name = str(knob.get("name", "")).strip()
        if not name:
            return str(knob.get("prompt", "")).strip() or "N/A"
        nvar = str(knob.get("nvar", "")).strip()
        offset = str(knob.get("offset", "")).strip()
        display_name = name
        if nvar and offset:
            display_name = re.sub(rf"__{re.escape(nvar)}_{re.escape(offset)}$", "", display_name, flags=re.IGNORECASE)
        display_name = re.sub(r"__[^_]+_0x[0-9A-Fa-f]+$", "", display_name)
        if display_name != name:
            display_name = re.sub(r"_Support$", "", display_name, flags=re.IGNORECASE)
        return display_name or name

    def _display_name_from_setup_page(self, knob):
        setup_page = str(knob.get("setup_page", "")).strip()
        if not setup_page:
            return ""
        parts = [part.strip() for part in setup_page.split("/") if part.strip()]
        if not parts:
            return ""
        tokens = []
        for part in parts:
            if re.fullmatch(r"(?:IIO|Platform)\s+Configuration", part, flags=re.IGNORECASE):
                continue
            match = re.fullmatch(r"Socket\s*(\d+)\s*Configuration", part, flags=re.IGNORECASE)
            if match:
                tokens.extend(("Socket", match.group(1)))
                continue
            match = re.fullmatch(r"Socket\s*(\d+)", part, flags=re.IGNORECASE)
            if match:
                tokens.extend(("Socket", match.group(1)))
                continue
            match = re.fullmatch(r"PCI\s*Express\s*(\d+)", part, flags=re.IGNORECASE)
            if match:
                tokens.extend(("PciExpress", match.group(1)))
                continue
            match = re.fullmatch(r"Port\s+([A-Za-z]|\d+)", part, flags=re.IGNORECASE)
            if match:
                port = match.group(1)
                if len(port) == 1 and port.isalpha():
                    port = port.upper()
                tokens.extend(("Port", port))
                continue
            if part == parts[-1]:
                part = re.sub(r"\s+Support$", "", part, flags=re.IGNORECASE).strip()
            token = self._display_name_token(part)
            if token:
                tokens.append(token)
        option_text = re.sub(r"\s+Support$", "", parts[-1], flags=re.IGNORECASE).strip()
        option_token = self._display_name_token(option_text)
        if option_token:
            if not tokens or tokens[-1].casefold() != option_token.casefold():
                tokens.append(option_token)
        return "_".join(token for token in tokens if token)

    def _display_name_token(self, text):
        return re.sub(r"[^0-9A-Za-z]+", "_", str(text).strip()).strip("_")

    def _display_name_suffix(self, knob):
        pieces = []
        nvar = self._display_name_token(knob.get("nvar", ""))
        offset = self._display_name_token(knob.get("offset", ""))
        varstore = self._display_name_token(knob.get("varstore", ""))
        if nvar:
            pieces.append(nvar)
        if offset:
            pieces.append(offset)
        elif varstore:
            pieces.append(f"VarStore_{varstore}")
        return "_".join(pieces)

    def _display_knob_name(self, knob):
        display_names = getattr(self, "_display_name_by_identity", {})
        return display_names.get(self._knob_identity(knob), self._base_display_knob_name(knob))

    def _display_current_value(self, knob):
        if not knob.get("current_available", True) and knob["name"] not in self.pending_changes:
            return "N/A"
        value = self.pending_changes.get(knob["name"], knob.get("current_value", ""))
        text = "" if knob["name"] in self.pending_changes else knob.get("current_text", "")
        if value == "":
            return "N/A"
        option = find_option_by_value(knob.get("options", []), value)
        if option:
            text = option.get("text", "") or text
            value = option.get("value", value)
        if text:
            return f"{text}({value})"
        return value

    def _display_current_cell_value(self, knob, locked=None):
        return self._display_current_value(knob)

    def _is_locked(self, knob, current_values=None):
        if current_values is None:
            current_values = self._effective_current_values()
        return dependency_blocks_edit(knob.get("depex", ""), current_values)

    def _is_current_editable(self, knob, locked):
        if locked:
            return False
        if not knob.get("current_available", True):
            return False
        setup_type = knob.get("setup_type", "").lower()
        if setup_type in ("oneof", "checkbox"):
            return bool(self._editor_values_for_knob(knob))
        return setup_type == "numeric"

    def _effective_current_values(self):
        values = {knob["name"]: knob["current_value"] for knob in self.knobs}
        values.update(self.pending_changes)
        return values

    def _knob_matches_search(self, knob, query):
        if not query.strip():
            return True
        for key in ("prompt", "name", "description"):
            if self._text_matches_search(str(knob.get(key, "")), query):
                return True
        if self._text_matches_search(self._display_knob_name(knob), query):
            return True
        return False

    def _text_matches_search(self, text, query):
        normalized_text = text.casefold()
        normalized_query = query.casefold()
        if normalized_query[-1].isspace():
            prefix = normalized_query.rstrip()
            if not prefix:
                return True
            start = 0
            while True:
                index = normalized_text.find(prefix, start)
                if index < 0:
                    return False
                end = index + len(prefix)
                if end == len(normalized_text) or normalized_text[end].isspace():
                    return True
                start = index + 1
        return normalized_query in normalized_text

    def _apply_filter(self, on_complete=None, show_loading=False):
        if self._loading and on_complete is None:
            return
        query = self.search_var.get().casefold()
        has_query = bool(query.strip())
        if self._is_system_information_selected() and not has_query:
            self._show_system_information()
            if callable(on_complete):
                on_complete()
            return
        self._show_detail_frame()
        self._configure_knob_tree_for_options()
        form_set, form = self._selected_category()
        self.filtered_knobs = []

        for knob in self.knobs:
            if not has_query and form_set and knob["form_set"] != form_set:
                continue
            if not has_query and form and knob["form"] != form:
                continue
            if not self._knob_matches_search(knob, query):
                continue
            self.filtered_knobs.append(knob)

        self.visible_knobs = list(self.filtered_knobs)
        self._populate_token += 1
        token = self._populate_token
        self._populate_current_values = self._effective_current_values()
        self.knob_tree.delete(*self.knob_tree.get_children())
        if show_loading:
            self._set_loading(True, len(self.filtered_knobs))
            self.count_var.set(f"Loading 0 of {len(self.filtered_knobs)} BIOS options...")
        else:
            self.count_var.set(f"Showing {len(self.filtered_knobs)} of {len(self.knobs)} BIOS options")
        self.detail_text.delete("1.0", tk.END)
        self._clear_editor()
        self._clear_current_cell_widgets()
        self.window.after(1, lambda: self._populate_knob_tree_batch(token, 0, on_complete, show_loading))

    def _set_loading(self, loading, total=0, message="Loading BIOS options..."):
        self._loading = loading
        self._hide_inline_editor()
        if loading:
            self.loading_status_var.set(message)
            if total:
                self.loading_progress.stop()
                self.loading_progress.configure(mode="determinate", maximum=max(total, 1), value=0)
            else:
                self.loading_progress.configure(mode="indeterminate", value=0)
                self.loading_progress.start(12)
            if not self.loading_panel.winfo_ismapped():
                self.loading_panel.pack(fill=tk.X, pady=(8, 0), before=self.knob_tree_frame)
        else:
            self.loading_progress.stop()
            self.loading_progress.configure(value=0)
            self.loading_panel.pack_forget()

        state = tk.DISABLED if loading else tk.NORMAL
        if self.save_button is not None:
            self.save_button.configure(state=state)
        if self.load_default_button is not None:
            self.load_default_button.configure(state=state)
        self.search_entry.configure(state=state)
        self.clear_button.configure(state=state)
        self.category_tree.configure(selectmode="none" if loading else "browse")
        if self.option_combo is not None:
            self.option_combo.configure(state="disabled")
        if self.apply_button is not None:
            self.apply_button.configure(state=tk.DISABLED)
        self.edit_status_var.set("Loading BIOS options..." if loading else "Select an option to edit")

    def _populate_knob_tree_batch(self, token, start_index, on_complete=None, show_loading=False):
        if token != self._populate_token:
            return

        current_values = self._populate_current_values
        end_index = min(start_index + self.TREE_INSERT_BATCH_SIZE, len(self.visible_knobs))
        for index in range(start_index, end_index):
            knob = self.visible_knobs[index]
            locked, _reason = self._is_locked(knob, current_values)
            self.knob_tree.insert("", tk.END, iid=str(index), values=(
                self._display_knob_name(knob),
                self._display_current_cell_value(knob, locked),
                self._display_value(knob, "default_value", "default_text"),
                knob["name"],
            ), tags=self._row_tags_for_knob(knob, current_values))

        if end_index < len(self.visible_knobs):
            if show_loading:
                self.count_var.set(f"Loading {end_index} of {len(self.filtered_knobs)} BIOS options...")
                self.loading_progress.configure(value=end_index)
            self.window.after(1, lambda: self._populate_knob_tree_batch(token, end_index, on_complete, show_loading))
            return

        self.count_var.set(f"Showing {len(self.filtered_knobs)} of {len(self.knobs)} BIOS options")
        if show_loading:
            self.loading_progress.configure(value=len(self.visible_knobs))
            self._set_loading(False)
        if callable(on_complete):
            on_complete()
        self._schedule_current_cell_refresh()

    def _on_knob_tree_yscroll(self, first, last):
        self.knob_scrollbar.set(first, last)
        self._schedule_current_cell_refresh()

    def _scroll_knob_tree_y(self, *args):
        self.knob_tree.yview(*args)
        self._schedule_current_cell_refresh()

    def _schedule_current_cell_refresh(self):
        return

    def _clear_current_cell_widgets(self):
        for widget in list(getattr(self, "current_cell_widgets", {}).values()):
            with contextlib.suppress(tk.TclError):
                widget.destroy()
        self.current_cell_widgets = {}
        self._current_cell_refresh_pending = False

    def _refresh_current_cell_widgets(self):
        self._current_cell_refresh_pending = False
        existing = getattr(self, "current_cell_widgets", {})
        needed = set()
        for item_id in self.knob_tree.get_children():
            bbox = self.knob_tree.bbox(item_id, "current")
            if not bbox:
                continue
            try:
                knob = self.visible_knobs[int(item_id)]
            except (ValueError, IndexError):
                continue
            locked, _reason = self._is_locked(knob)
            if not self._is_current_editable(knob, locked):
                continue
            needed.add(item_id)
            widget = existing.get(item_id)
            if widget is None or not widget.winfo_exists():
                widget = self._create_current_cell_widget(item_id, knob)
                existing[item_id] = widget
            elif hasattr(widget, "_current_value_var"):
                widget._current_value_var.set(self._format_editor_value_by_current(
                    knob,
                    self.pending_changes.get(knob["name"], knob.get("current_value", "")),
                ))
                if isinstance(widget, ttk.Combobox):
                    widget.configure(values=self._editor_values_for_knob(knob))
            self._place_current_cell_widget(item_id, widget)

        for item_id in list(existing):
            if item_id not in needed:
                with contextlib.suppress(tk.TclError):
                    existing[item_id].destroy()
                existing.pop(item_id, None)
        self.current_cell_widgets = existing

    def _create_current_cell_widget(self, item_id, knob):
        setup_type = knob.get("setup_type", "").lower()
        value_var = tk.StringVar(value=self._format_editor_value_by_current(
            knob,
            self.pending_changes.get(knob["name"], knob.get("current_value", "")),
        ))
        if setup_type == "numeric":
            widget = ttk.Entry(self.knob_tree_frame, textvariable=value_var, style="BiosInlineCurrent.TEntry")
            widget.bind("<Return>", lambda _event, iid=item_id, var=value_var: self._apply_current_widget_value(iid, var.get()))
            widget.bind("<FocusOut>", lambda _event, iid=item_id, var=value_var: self._apply_current_widget_value(iid, var.get(), quiet=True))
        else:
            widget = ttk.Combobox(
                self.knob_tree_frame,
                textvariable=value_var,
                values=self._editor_values_for_knob(knob),
                state="readonly",
                style="BiosInlineCurrent.TCombobox",
            )
            widget.bind("<<ComboboxSelected>>", lambda _event, iid=item_id, var=value_var: self._apply_current_widget_value(iid, var.get()))
        widget.bind("<Button-1>", lambda _event, iid=item_id: self._select_current_widget_row(iid), add="+")
        widget._current_value_var = value_var
        return widget

    def _place_current_cell_widget(self, item_id, widget):
        bbox = self.knob_tree.bbox(item_id, "current")
        if not bbox:
            widget.place_forget()
            return
        x, y, width, height = bbox
        widget.place(
            x=self.knob_tree.winfo_x() + x + 2,
            y=self.knob_tree.winfo_y() + y + 1,
            width=max(width - 4, 40),
            height=max(height - 2, 22),
        )

    def _select_current_widget_row(self, item_id):
        self.knob_tree.selection_set(item_id)
        self.knob_tree.focus(item_id)
        self._on_knob_selected()

    def _apply_current_widget_value(self, item_id, selected_text, quiet=False):
        try:
            knob = self.visible_knobs[int(item_id)]
        except (ValueError, IndexError):
            return "break"
        self.selected_knob = knob
        value = self._option_value_from_text(knob, selected_text)
        if value is None:
            if not quiet:
                messagebox.showerror("BIOS Setup Viewer", "Please select a valid option value.", parent=self.window)
            return "break"
        if self._set_pending_value_for_knob(knob, value, item_id, quiet=quiet):
            self._schedule_current_cell_refresh()
        return "break"

    def _row_tags_for_knob(self, knob, current_values=None):
        locked, _reason = self._is_locked(knob, current_values)
        tags = []
        if locked:
            tags.append("locked")
        elif self._is_current_editable(knob, locked):
            tags.append("editable")
        if knob["name"] in self.pending_changes:
            tags.append("changed")
        return tuple(tags)

    def _refresh_knob_tree_row(self, item_id, knob):
        self.knob_tree.item(item_id, values=(
            self._display_knob_name(knob),
            self._display_current_cell_value(knob),
            self._display_value(knob, "default_value", "default_text"),
            knob["name"],
        ), tags=self._row_tags_for_knob(knob))
        self.knob_tree.selection_set(item_id)
        self.knob_tree.focus(item_id)

    def _on_knob_selected(self, _event=None):
        if self._loading:
            return
        if self._is_system_information_selected() and not self.search_var.get().strip():
            return
        selected = self.knob_tree.selection()
        if not selected:
            return
        knob = self.visible_knobs[int(selected[0])]
        self.selected_knob = knob
        options = knob.get("options", [])
        option_lines = [f"  {option['text']} = {option['value']}" for option in options]
        locked, reason = self._is_locked(knob)
        setup_type = knob.get("setup_type", "").lower()
        self.detail_name_var.set(f"Prompt: {knob.get('prompt', '') or 'N/A'}")
        details = [
            f"Description: {knob['description']}",
            f"Dependency: {knob['depex']}",
            f"Edit Status: {'Locked' if locked else 'Editable'}",
        ]
        if setup_type == "numeric":
            details.insert(2, f"Range: min={knob.get('min', '')}    max={knob.get('max', '')}    step={knob.get('step', '')}")
        if self.embedded:
            details.extend([
                f"NVRAM Variable: {knob.get('nvar', '') or 'N/A'}",
                f"NVRAM GUID: {knob.get('nvar_guid', '') or 'N/A'}",
                f"NVRAM Offset: {knob.get('offset', '') or 'N/A'}",
                f"NVRAM Width: {format_knob_width(knob.get('size', ''), knob.get('offset', '')) or 'N/A'}",
                f"VarStore Index: {knob.get('varstore', '') or 'N/A'}",
                f"Value Source: {knob.get('value_source', '') or 'N/A'}",
            ])
        if option_lines:
            details.append("Options:")
            details.extend(option_lines)

        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, "\n".join(details))
        self._update_goto_button()

    def _update_goto_button(self):
        if self.goto_button is None:
            return
        state = tk.NORMAL if self.selected_knob else tk.DISABLED
        self.goto_button.configure(state=state)

    def _jump_to_selected_knob(self):
        knob = self.selected_knob
        if not knob:
            return
        self._jump_to_knob_location(knob)

    def _on_knob_tree_click(self, event):
        if self._loading:
            return
        if self.inline_item is not None:
            self._flush_inline_editor(quiet=True)
        else:
            self._hide_inline_editor()
        item_id = self.knob_tree.identify_row(event.y)
        column_id = self.knob_tree.identify_column(event.x)
        if not item_id:
            return
        self.knob_tree.selection_set(item_id)
        self.knob_tree.focus(item_id)
        self._on_knob_selected()
        current_bbox = self.knob_tree.bbox(item_id, "current")
        if current_bbox:
            x, _y, width, _height = current_bbox
            in_current_column = x <= event.x <= x + width
        else:
            in_current_column = column_id == "#2"
        if in_current_column:
            self._show_inline_current_editor(item_id)

    def _show_inline_current_editor(self, item_id):
        try:
            knob = self.visible_knobs[int(item_id)]
        except (ValueError, IndexError):
            return
        locked, reason = self._is_locked(knob)
        if locked:
            self.edit_status_var.set(reason)
            return
        setup_type = knob.get("setup_type", "").lower()
        combo_values = self._editor_values_for_knob(knob)
        if setup_type not in ("oneof", "checkbox", "numeric") or (setup_type != "numeric" and not combo_values):
            self.edit_status_var.set("No editable values")
            return
        current_value = self.pending_changes.get(knob["name"], knob.get("current_value", ""))
        bbox = self.knob_tree.bbox(item_id, "current")
        if not bbox:
            return
        x, y, width, height = bbox
        self.selected_knob = knob
        self.inline_item = item_id
        self.inline_knob = knob
        self.option_combo.configure(values=combo_values, state="normal" if setup_type == "numeric" else "readonly")
        self.option_value_var.set(self._format_editor_value_by_current(knob, current_value))
        self.option_combo.place(
            x=self.knob_tree.winfo_x() + x,
            y=self.knob_tree.winfo_y() + y,
            width=width,
            height=max(height, 24),
        )
        self.option_combo.focus_set()

    def _hide_inline_editor(self):
        if hasattr(self, "option_combo") and self.option_combo is not None:
            with contextlib.suppress(tk.TclError):
                self.option_combo.place_forget()
        self.inline_item = None
        self.inline_knob = None

    def _apply_inline_change(self, _event=None):
        self._apply_selected_change(knob=self.inline_knob, item_id=self.inline_item)
        self._hide_inline_editor()
        return "break"

    def _apply_inline_focus_out(self, _event=None):
        knob = self.inline_knob or self.selected_knob
        if knob and knob.get("setup_type", "").lower() == "numeric":
            self._apply_selected_change(quiet=True, knob=knob, item_id=self.inline_item)
        self._hide_inline_editor()
        return "break"

    def _flush_inline_editor(self, quiet=True):
        knob = self.inline_knob or self.selected_knob
        if self.inline_item is None or not knob:
            return True
        if knob.get("setup_type", "").lower() != "numeric":
            self._hide_inline_editor()
            return True
        ok = self._apply_selected_change(quiet=quiet, knob=knob, item_id=self.inline_item)
        if ok:
            self._hide_inline_editor()
        return ok

    def _knob_identity(self, knob):
        return (
            str(knob.get("name", "")),
            str(knob.get("setup_page", "")),
            str(knob.get("nvar_guid", "")),
            str(knob.get("offset", "")),
            str(knob.get("varstore", "")),
        )

    def _jump_to_knob_location(self, knob):
        form_set = knob.get("form_set", "")
        form = knob.get("form", "")
        self.search_var.set("")
        target_id = self.category_node_by_key.get((form_set, form)) or self.category_node_by_key.get((form_set, None))
        if target_id:
            parent_id = self.category_tree.parent(target_id)
            while parent_id:
                self.category_tree.item(parent_id, open=True)
                parent_id = self.category_tree.parent(parent_id)
            self._suppress_category_event = True
            try:
                self.category_tree.selection_set(target_id)
                self.category_tree.focus(target_id)
                self.category_tree.see(target_id)
            finally:
                self._suppress_category_event = False
        self._apply_filter(on_complete=lambda: self._select_knob_by_identity(knob), show_loading=True)

    def _select_knob_by_identity(self, target_knob):
        target_identity = self._knob_identity(target_knob)
        for index, knob in enumerate(self.visible_knobs):
            if self._knob_identity(knob) == target_identity:
                item_id = str(index)
                self.knob_tree.selection_set(item_id)
                self.knob_tree.focus(item_id)
                self.knob_tree.see(item_id)
                self._on_knob_selected()
                return

    def _format_option(self, option):
        text = option.get("text", "")
        value = option.get("value", "")
        if text:
            return f"{text}({value})"
        return value

    def _format_option_by_value(self, knob, value):
        option = find_option_by_value(knob.get("options", []), value)
        if option:
            return self._format_option(option)
        return str(value)

    def _editor_values_for_knob(self, knob):
        setup_type = knob.get("setup_type", "").lower()
        if setup_type == "oneof":
            return [self._format_option(option) for option in knob.get("options", [])]
        if setup_type == "checkbox":
            if knob.get("options"):
                return [self._format_option(option) for option in knob.get("options", [])]
            return ["Unchecked / Disabled (0x0)", "Checked / Enabled (0x1)"]
        if setup_type == "numeric":
            values = []
            if knob.get("min"):
                values.append(knob["min"])
            if knob.get("max") and knob.get("max") != knob.get("min"):
                values.append(knob["max"])
            return values
        return []

    def _format_editor_value_by_current(self, knob, value):
        setup_type = knob.get("setup_type", "").lower()
        if setup_type == "checkbox" and not knob.get("options"):
            return "Checked / Enabled (0x1)" if _normalize_int_text(value) == "1" else "Unchecked / Disabled (0x0)"
        if setup_type == "oneof" or knob.get("options"):
            return self._format_option_by_value(knob, value)
        return str(value)

    def _numeric_range_text(self, knob):
        min_value = knob.get("min", "")
        max_value = knob.get("max", "")
        if min_value or max_value:
            return f" [{min_value}..{max_value}]"
        return ""

    def _selected_option_value(self, knob=None):
        knob = knob or self.selected_knob
        if not knob:
            return None
        return self._option_value_from_text(knob, self.option_value_var.get())

    def _option_value_from_text(self, knob, selected_text):
        setup_type = knob.get("setup_type", "").lower()
        if setup_type == "numeric":
            return selected_text.strip()
        if setup_type == "checkbox" and not knob.get("options"):
            return "0x1" if "0x1" in selected_text else "0x0"
        for option in knob.get("options", []):
            if selected_text == self._format_option(option):
                return option.get("value", "")
        match = re.search(r"\((0x[0-9a-fA-F]+|\d+)\)\s*$", selected_text)
        if match:
            return match.group(1)
        return None

    def _clear_editor(self):
        self._hide_inline_editor()
        self.selected_knob = None
        if self.option_combo is not None:
            self.option_combo.configure(values=(), state="disabled")
        self.option_value_var.set("")
        if self.apply_button is not None:
            self.apply_button.configure(state=tk.DISABLED)
        self.edit_status_var.set("Select an option to edit")
        self._update_goto_button()

    def _apply_selected_change(self, quiet=False, knob=None, item_id=None):
        knob = knob or self.selected_knob
        if not knob:
            return False
        locked, reason = self._is_locked(knob)
        if locked:
            if not quiet:
                messagebox.showwarning("BIOS Setup Viewer", reason, parent=self.window)
            return False
        value = self._selected_option_value(knob)
        if value is None:
            if not quiet:
                messagebox.showerror("BIOS Setup Viewer", "Please select a valid option value.", parent=self.window)
            return False

        if item_id is None:
            selected = self.knob_tree.selection()
            item_id = selected[0] if selected else self.inline_item
        return self._set_pending_value_for_knob(knob, value, item_id, quiet=quiet)

    def _set_pending_value_for_knob(self, knob, value, item_id=None, quiet=False):
        locked, reason = self._is_locked(knob)
        if locked:
            if not quiet:
                messagebox.showwarning("BIOS Setup Viewer", reason, parent=self.window)
            return False
        setup_type = knob.get("setup_type", "").lower()
        if setup_type == "numeric":
            valid, normalized_value, error_message = self._validate_numeric_value(knob, value)
            if not valid:
                if not quiet:
                    messagebox.showerror("BIOS Setup Viewer", error_message, parent=self.window)
                return False
            value = normalized_value

        name = knob["name"]
        original = knob.get("current_value", "")
        if _normalize_int_text(value) == _normalize_int_text(original):
            self.pending_changes.pop(name, None)
        else:
            self.pending_changes[name] = value
        self._update_pending_label()
        if item_id:
            self._refresh_knob_tree_row(item_id, knob)
        self._on_knob_selected()
        return True

    def _validate_numeric_value(self, knob, value):
        text = str(value).strip()
        try:
            parsed = _parse_int_value(text)
        except ValueError:
            return False, text, "Numeric BIOS option value must be decimal or hex, for example 10 or 0xA."

        min_text = knob.get("min", "")
        max_text = knob.get("max", "")
        try:
            if min_text and parsed < _parse_int_value(min_text):
                return False, text, f"Value is below minimum {min_text}."
            if max_text and parsed > _parse_int_value(max_text):
                return False, text, f"Value is above maximum {max_text}."
        except ValueError:
            return True, text, ""
        try:
            width = max(2, _parse_int_value(knob.get("size", "1")) * 2)
        except ValueError:
            width = max(2, (parsed.bit_length() + 3) // 4)
        return True, f"0x{parsed:0{width}X}", ""

    def _update_pending_label(self):
        count = len(self.pending_changes)
        if count:
            self.pending_var.set(f"{count} pending change(s)")
        else:
            self.pending_var.set("No pending changes")

    def _target_settings(self):
        if not self.target_settings_getter:
            return None, ["Target Mode"]
        settings = self.target_settings_getter()
        if not settings:
            return None, ["Target Mode"]
        if settings.get("mode") == "local":
            return settings, []
        if settings.get("mode") == "offline":
            missing = []
            if not settings.get("bios_bin"):
                missing.append("BIOS Binary")
            elif not os.path.isfile(settings.get("bios_bin")):
                missing.append("Valid BIOS Binary")
            if missing:
                return None, missing
            return settings, []

        missing = []
        if not settings.get("host"):
            missing.append("Host IP")
        if not settings.get("user"):
            missing.append("User Name")
        if not settings.get("password"):
            missing.append("Password")
        if not settings.get("port"):
            missing.append("Port")
        if missing:
            return None, missing
        return settings, []

    def _show_missing_target_settings(self, action):
        settings, missing = self._target_settings()
        if settings:
            return settings
        messagebox.showerror(
            "BIOS Setup Viewer",
            f"Please fill the following target information before {action}:\n\n" + "\n".join(missing),
            parent=self.window,
        )
        return None

    def _set_toolbar_running(self, running):
        state = tk.DISABLED if running else tk.NORMAL
        if self.save_button is not None:
            self.save_button.configure(state=state)
        if self.save_cold_reset_button is not None:
            self.save_cold_reset_button.configure(state=state)
        if self.save_warm_reset_button is not None:
            self.save_warm_reset_button.configure(state=state)
        if self.load_default_button is not None:
            self.load_default_button.configure(state=state)

    def _set_viewer_running(self, running):
        state = tk.DISABLED if running else tk.NORMAL
        self._hide_inline_editor()
        if self.save_button is not None:
            self.save_button.configure(state=state)
        if self.save_cold_reset_button is not None:
            self.save_cold_reset_button.configure(state=state)
        if self.save_warm_reset_button is not None:
            self.save_warm_reset_button.configure(state=state)
        if self.load_default_button is not None:
            self.load_default_button.configure(state=state)
        self.search_entry.configure(state=state)
        self.clear_button.configure(state=state)
        self.category_tree.configure(selectmode="none" if running else "browse")
        if self.option_combo is not None:
            self.option_combo.configure(state="disabled")
        if self.apply_button is not None:
            self.apply_button.configure(state=tk.DISABLED)
        if running:
            self.edit_status_var.set("Programming BIOS options...")
        else:
            self.edit_status_var.set("Select an option to edit")
            if self.knob_tree.selection():
                self._on_knob_selected()

    def _save_changes(self, reset_action=None):
        if not self._flush_inline_editor(quiet=False):
            return
        if not self.pending_changes:
            messagebox.showinfo("BIOS Setup Viewer", "No pending BIOS option changes.", parent=self.window)
            return
        settings = self._show_missing_target_settings("saving BIOS knob changes")
        if not settings:
            return

        knob_string = ",".join(f"{name}={value}" for name, value in self.pending_changes.items())
        if settings.get("mode") == "local":
            target_text = "local system"
        elif settings.get("mode") == "offline":
            target_text = "offline BIOS binary"
        else:
            target_text = "remote machine"
        if not messagebox.askyesno(
            "Save BIOS Options",
            f"Confirm programming these BIOS knob changes to the {target_text}?\n\n" + knob_string,
            parent=self.window,
        ):
            return

        command_text = "" if settings.get("mode") != "offline" else f"Patch BIOS binary with standalone decoder: {knob_string}"
        self.command_dialog = CommandDialog(self.window, "Programming BIOS Options", command_text)
        self.command_dialog.append(f"Target: {target_text}\n")
        if settings.get("mode") == "offline":
            self.command_dialog.append(f"BIOS binary: {settings.get('bios_bin')}\n")
        elif reset_action in ("cold", "warm"):
            self.command_dialog.append("Reset will run only after the save-success text is observed.\n")
        self._set_viewer_running(True)
        threading.Thread(target=self._save_changes_worker, args=(settings, knob_string, reset_action), daemon=True).start()

    def _save_changes_worker(self, settings, knob_string, reset_action=None):
        def log_callback(text):
            self.window.after(0, lambda chunk=text: self._append_command_log(chunk))

        try:
            if settings.get("mode") == "remote":
                self.window.after(0, lambda: self._append_command_log("[INFO] Stopping existing OpenIPC_x64.exe process before programming...\n"))
                _stop_openipc_processes(settings, log_callback=log_callback)
            if settings.get("mode") == "local":
                exit_code, out, err = program_bios_knobs_local(knob_string, log_callback=log_callback, reset_action=reset_action)
            elif settings.get("mode") == "offline":
                exit_code, out, err = program_bios_knobs_offline(
                    knob_string,
                    settings.get("bios_bin"),
                    output_dir=settings.get("output_dir"),
                    log_callback=log_callback,
                )
            else:
                exit_code, out, err = program_bios_knobs(settings, knob_string, log_callback=log_callback, reset_action=reset_action)
            if exit_code == 0:
                for knob in self.knobs:
                    if knob["name"] in self.pending_changes:
                        value = self.pending_changes[knob["name"]]
                        knob["current_value"] = value
                        knob["current_text"] = resolve_option_text(knob.get("options", []), value)
                self.pending_changes.clear()
                self.window.after(0, lambda stdout=out, stderr=err, mode=settings.get("mode"): self._save_success(stdout, stderr, mode=mode))
            else:
                message = _with_pysvtools_hint(err or f"CvProgKnobs exited with code {exit_code}")
                self.window.after(
                    0,
                    lambda msg=message, stdout=out, stderr=err, install_settings=settings: self._save_failed(
                        msg,
                        out_text=stdout,
                        err_text=stderr,
                        settings=install_settings,
                    ),
                )
        except Exception as error:
            message = _with_pysvtools_hint(str(error))
            self.window.after(
                0,
                lambda msg=message, install_settings=settings: self._save_failed(msg, settings=install_settings),
            )

    def _append_command_output(self, out_text, err_text):
        if self.command_dialog is None:
            return
        if out_text:
            self.command_dialog.append("\n[STDOUT]\n")
            self.command_dialog.append(out_text + "\n")
        if err_text:
            self.command_dialog.append("\n[STDERR]\n")
            self.command_dialog.append(err_text + "\n")

    def _append_command_log(self, text):
        if self.command_dialog is not None and text:
            self.command_dialog.append(text)

    def _save_success(self, out_text="", err_text="", mode=None):
        self._set_viewer_running(False)
        if mode != "local":
            self._append_command_output(out_text, err_text)
        if self.command_dialog is not None:
            if mode == "offline":
                self.command_dialog.finish(True, "Patched BIOS binary was generated successfully.")
            else:
                self.command_dialog.finish(True, "BIOS option changes were sent successfully.")
        self._update_pending_label()
        self._apply_filter()

    def _save_failed(self, message, out_text="", err_text="", settings=None):
        self._set_viewer_running(False)
        if settings is None or settings.get("mode") != "local":
            self._append_command_output(out_text, err_text)
        if self.command_dialog is not None:
            self.command_dialog.finish(False, f"Failed to save BIOS options:\n{message}")
        if _is_missing_pysvtools_error("\n".join((message, out_text, err_text))):
            install_parent = self.command_dialog.window if self.command_dialog is not None else self.window
            self.window.after(100, lambda parent=install_parent, install_settings=settings: prompt_install_pysvtools(parent, install_settings))

    def _load_defaults(self):
        if not messagebox.askyesno(
            "Load Defaults",
            "Set all displayed BIOS options in this viewer to their default values?\n\n"
            "This will not change BIOS settings until you click Save.",
            parent=self.window,
        ):
            return

        self.pending_changes.clear()
        for knob in self.knobs:
            default_value = knob.get("default_value", "")
            if default_value and _normalize_int_text(default_value) != _normalize_int_text(knob.get("current_value", "")):
                self.pending_changes[knob["name"]] = default_value
        self._load_defaults_success()

    def _load_defaults_success(self):
        self._update_pending_label()
        self._apply_filter()
        messagebox.showinfo(
            "BIOS Setup Viewer",
            "Default values have been staged in the viewer. Click Save to program them.",
            parent=self.window,
        )

    def _open_xml_folder(self):
        folder = os.path.dirname(os.path.abspath(self.metadata["xml_path"]))
        os.startfile(folder)


class QueueWriter:
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, text):
        if text:
            self.log_queue.put(("log", text))

    def flush(self):
        return None


class StreamingTextBuffer:
    def __init__(self, callback=None):
        self.callback = callback
        self.parts = []

    def write(self, text):
        if text:
            self.parts.append(text)
            if self.callback:
                self.callback(text)
        return len(text or "")

    def flush(self):
        return None

    def getvalue(self):
        return "".join(self.parts)


class PyPiCredentialDialog:
    def __init__(self, parent):
        self.parent = parent
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.title("Intel PyPI Login")
        self.window.geometry("420x180")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        self.user_var = tk.StringVar(value="")
        self.password_var = tk.StringVar(value="")

        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Intel PyPI requires authentication to install pysvtools.xmlcli.").grid(
            row=0,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(0, 10),
        )
        ttk.Label(frame, text="User").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        user_entry = ttk.Entry(frame, textvariable=self.user_var, width=34)
        user_entry.grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Label(frame, text="Password").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        password_entry = ttk.Entry(frame, textvariable=self.password_var, show="*", width=34)
        password_entry.grid(row=2, column=1, sticky=tk.EW, pady=4)
        frame.columnconfigure(1, weight=1)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky=tk.E, pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Install", command=self._ok).pack(side=tk.RIGHT, padx=(0, 8))

        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.bind("<Return>", lambda _event: self._ok())
        self.window.bind("<Escape>", lambda _event: self._cancel())
        self.window.update_idletasks()
        self._center(parent)
        user_entry.focus_set()

    def _center(self, parent):
        parent.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        win_w = self.window.winfo_width()
        win_h = self.window.winfo_height()
        x = parent_x + max((parent_w - win_w) // 2, 0)
        y = parent_y + max((parent_h - win_h) // 2, 0)
        self.window.geometry(f"+{x}+{y}")

    def _ok(self):
        user_name = self.user_var.get().strip()
        password = self.password_var.get()
        if not user_name or not password:
            messagebox.showerror("Intel PyPI Login", "Please input Intel PyPI user and password.", parent=self.window)
            return
        self.result = {"user": user_name, "password": password}
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        with contextlib.suppress(tk.TclError):
            self.window.grab_release()
            self.window.destroy()


class FitmEditorFrame(ttk.Frame):
    BOOT_GUARD_ROWS = [
        ("Boot Profile", "btg.FwType", "Configures which Boot Policy Profile will be used"),
        ("CPU Debugging", "btg.DisableCpuDebugging", "Enables or disables CPU debugging features"),
        ("BSP Initialization", "btg.DisableBspInitialization", "Enables or disables BSP (Bootstrap Processor) initialization"),
        ("CONSENT", "btg.Consent", "Enable or disable CONSENT debug policy bit"),
        ("S3M Trace", "btg.S3mTrace", "Enable or disable S3M Trace debug policy bit"),
        ("NPK Utilize ITH Buffer", "btg.NpkUtilizeITHBuffer", "Enable or disable storing traces in ITH buffer"),
        ("DAM", "btg.Dam", "Enable or disable DAM debug policy bit"),
        ("TXT Supported", "btg.TxtSupported", "Indicates whether the platform supports Intel TXT. If set, BIOS should provide setup option"),
        ("OEM Unlock", "btg.OemUnlock", "OEM unlock control"),
        ("ACM SVN", "btg.AcmSvn", "ACM security version number used for S-ACM revocation"),
        ("Key Manifest SVN", "btg.KmSvn", "Security version number used for KM revocation"),
        ("Boot Policy Manifest SVN", "btg.BpSvn", "Security version number used for BPM revocation"),
        ("Signature Algorithm", "btg.SignatureAlgorithm", "Signature algorithm used (e.g., RSAPSS, LMS, Dilithium, hybrid)"),
        ("Key Manifest ID", "btg.KeyManifestId", "Identifier of the key manifest used by platform"),
        ("OEM Key Hash Algorithm", "btg.OemKeyHashAlg", "Hash algorithm used for OEM key"),
    ]
    HASH_ALGORITHMS = {0: "SHA-256", 1: "SHA-384", 2: "SHA-512"}
    SIGNATURE_ALGORITHMS = {0: "RSAPSS/2048", 1: "RSAPSS/3072", 2: "LMS", 3: "Dilithium", 4: "Hybrid"}

    def __init__(self, master=None, show_file_toolbar=True):
        super().__init__(master)
        self.show_file_toolbar = show_file_toolbar
        self.cui = load_bios_modify_cui()
        self.core = self.cui.fitm_core()
        self.image = None
        self.current_field = None
        self.current_item = None
        self.current_module = "flash_config"
        self.row_field_map = {}
        self.option_value_map = {}
        self.changed_fields = set()
        self.inline_item = None
        self.inline_has_options = False
        self.inline_original_text = ""
        self.inline_hide_after_id = None
        self.pending_inline_target = None
        self.search_var = tk.StringVar()
        self.module_buttons = {}
        self._configure_style()
        self._build_ui()

    def _configure_style(self):
        self.colors = {
            "background": "#eef3f8",
            "panel": "#ffffff",
            "border": "#d7e0ea",
            "text": "#1f2937",
            "muted": "#5f6b7a",
            "accent": "#0f6cbd",
            "accent_dark": "#0b4f8a",
        }
        with contextlib.suppress(tk.TclError):
            self.configure(style="BiosViewer.TFrame")
        style = ttk.Style(self)
        style.configure("BiosViewer.TFrame", background=self.colors["background"])
        style.configure("BiosTitle.TLabel", background=self.colors["background"], foreground=self.colors["text"], font=("Segoe UI", 15, "bold"))
        style.configure("BiosSubtitle.TLabel", background=self.colors["background"], foreground=self.colors["muted"])
        style.configure("BiosStatus.TLabel", background=self.colors["background"], foreground=self.colors["muted"])
        style.configure("Bios.TButton", padding=(10, 5), background=self.colors["accent"], foreground="#ffffff")
        style.map("Bios.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])
        style.configure("Bios.Treeview", background=self.colors["panel"], fieldbackground=self.colors["panel"], foreground=self.colors["text"], rowheight=25, bordercolor=self.colors["border"], borderwidth=1)
        style.configure("Bios.Treeview.Heading", background="#dbe8f5", foreground=self.colors["text"], font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Bios.Treeview", background=[("selected", self.colors["accent"])], foreground=[("selected", "#ffffff")])

    def _build_ui(self):
        self.path_var = tk.StringVar(value="No image loaded")
        if self.show_file_toolbar:
            toolbar = ttk.Frame(self)
            toolbar.pack(fill=tk.X, padx=8, pady=6)
            ttk.Button(toolbar, text="Open BIOS Binary", command=self.open_image).pack(side=tk.LEFT)
            ttk.Button(toolbar, text="Rebuild Binary", command=self.save_as).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Label(toolbar, textvariable=self.path_var).pack(side=tk.LEFT, padx=12)

        body = ttk.Frame(self, style="BiosViewer.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        navigation_shell = ttk.Frame(body, style="BiosViewer.TFrame")
        navigation_shell.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), pady=(5, 0))
        navigation_canvas = tk.Canvas(navigation_shell, width=155, highlightthickness=0, bg=self.colors["background"])
        self.navigation_canvas = navigation_canvas
        navigation_scroll = ttk.Scrollbar(navigation_shell, orient=tk.VERTICAL, command=navigation_canvas.yview)
        navigation_canvas.configure(yscrollcommand=navigation_scroll.set)
        navigation = ttk.Frame(navigation_canvas, style="BiosViewer.TFrame")
        navigation_window = navigation_canvas.create_window((0, 0), window=navigation, anchor=tk.NW)
        navigation.bind("<Configure>", lambda _event: navigation_canvas.configure(scrollregion=navigation_canvas.bbox("all")))
        navigation_canvas.bind("<Configure>", lambda event: navigation_canvas.itemconfigure(navigation_window, width=event.width))
        navigation_canvas.bind("<MouseWheel>", self.on_navigation_mousewheel)
        navigation.bind("<MouseWheel>", self.on_navigation_mousewheel)
        navigation_canvas.pack(side=tk.LEFT, fill=tk.Y, expand=False)
        navigation_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        module_buttons = [("flash_config", "Flash Configuration"), ("boot_guard", "Boot Guard")]
        module_buttons.extend((f"softstrap{index}", f"Softstrap{index}") for index in range(14))
        for key, label in module_buttons:
            button = ttk.Button(navigation, text=label, command=lambda module=key: self.show_module(module), style="Bios.TButton")
            button.pack(fill=tk.X, pady=(0, 6))
            self.module_buttons[key] = button

        content = ttk.Frame(body, style="BiosViewer.TFrame")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        top = ttk.Frame(content, style="BiosViewer.TFrame")
        top.pack(fill=tk.X)
        self.module_title_var = tk.StringVar(value="Flash Configuration")
        ttk.Label(top, textvariable=self.module_title_var, style="BiosTitle.TLabel").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Select and decode a BIOS binary")
        ttk.Label(top, textvariable=self.status_var, style="BiosStatus.TLabel").pack(side=tk.RIGHT)

        search_frame = ttk.Frame(content, style="BiosViewer.TFrame")
        search_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(search_frame, text="Search Name", style="BiosSubtitle.TLabel").pack(side=tk.LEFT)
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=34)
        search_entry.pack(side=tk.LEFT, padx=(8, 6))
        search_entry.bind("<KeyRelease>", self.on_search_changed)
        ttk.Button(search_frame, text="Clear", command=self.clear_search, style="Bios.TButton").pack(side=tk.LEFT)

        table_frame = ttk.Frame(content, style="BiosViewer.TFrame")
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 8))
        columns = ("value", "description")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="browse", style="Bios.Treeview")
        self.tree.heading("#0", text="Name", anchor=tk.W)
        self.tree.heading("value", text="Value", anchor=tk.W)
        self.tree.heading("description", text="Description", anchor=tk.W)
        self.tree.column("#0", width=260, minwidth=180, anchor=tk.W)
        self.tree.column("value", width=180, minwidth=110, anchor=tk.W)
        self.tree.column("description", width=620, minwidth=260, anchor=tk.W)
        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_release)
        self.tree.tag_configure("changed", foreground="#1f2937", background="#fff2b8")
        self.tree.tag_configure("disabled", foreground="#8a96a3", background="#eef2f6")
        self.tree.tag_configure("editable", foreground="#1f2937")
        self.field_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.value_combo = ttk.Combobox(table_frame, textvariable=self.value_var)
        self.value_combo.bind("<<ComboboxSelected>>", self.apply_inline_value)
        self.value_combo.bind("<Return>", self.apply_inline_value)
        self.value_combo.bind("<Escape>", self.hide_inline_editor)
        self.value_combo.bind("<FocusOut>", self.schedule_hide_inline_editor)

        self.details = tk.Text(content, wrap=tk.WORD, height=6)
        self.details.pack(fill=tk.X, pady=(8, 0))
        self.details.configure(bg="#f7f9fc", fg="#1f2937", relief=tk.FLAT, padx=8, pady=6, font=("Consolas", 9))
        self.show_start_page()

    def on_navigation_mousewheel(self, event):
        if getattr(self, "navigation_canvas", None) is not None:
            self.navigation_canvas.yview_scroll(-1 * int(event.delta / 120), "units")
        return "break"

    def current_platform(self):
        if not self.image:
            return "unknown"
        with contextlib.suppress(Exception):
            return self.image.detect_platform()
        return "unknown"

    def platform_label(self):
        if not self.image:
            return "Unknown platform"
        with contextlib.suppress(Exception):
            return self.image.platform_name()
        return "Unknown platform"

    def raw_strap_count(self):
        if not self.image:
            return 14
        with contextlib.suppress(Exception):
            return self.image.raw_strap_count()
        return 14

    def image_fields(self):
        if self.image and hasattr(self.image, "supported_fields"):
            return self.image.supported_fields()
        return self.core.all_fields()

    def update_navigation_state(self):
        count = self.raw_strap_count()
        for index in range(14):
            button = self.module_buttons.get(f"softstrap{index}")
            if button:
                button.configure(state=tk.NORMAL if index < count else tk.DISABLED)

    def boot_guard_rows(self):
        if self.current_platform() != "bhs":
            return self.BOOT_GUARD_ROWS
        rows = []
        for label, field_name, description in self.BOOT_GUARD_ROWS:
            if label == "CPU Debugging":
                rows.append((label, "btg.BtGuardCpuDebuging", "BHS CPU Debugging setting; stored FIT4 bit is disable_cpu_debug"))
            elif label == "BSP Initialization":
                rows.append((label, "btg.BtGuardBspInitialization", "BHS BSP Initialization setting"))
            else:
                rows.append((label, field_name, description))
        return rows

    def show_start_page(self):
        self.details.delete("1.0", tk.END)
        if self.show_file_toolbar:
            self.details.insert(tk.END, "Open a BIOS/IFWI binary to decode platform-aware flash component straps, IBL softstrap pins, DAM, and CPU debugging policy.\n\n")
            self.details.insert(tk.END, "Apply changes edits only the in-memory buffer. Use Rebuild Binary to write a new binary.\n")
        else:
            self.details.insert(tk.END, "Select and decode a BIOS/IFWI binary from the top offline toolbar to inspect platform-aware flash component straps, IBL softstrap pins, DAM, and CPU debugging policy.\n\n")
            self.details.insert(tk.END, "Apply changes edits the in-memory image. Use Export on 1-bios to save only the BIOS region slice, or use the top Rebuild Binary button to write all staged BIOS knob and flash-region changes.\n")
        self.tree.delete(*self.tree.get_children())
        self.tree.insert("", tk.END, text="Flash Configuration", values=("Decode a BIOS binary to inspect settings", ""), tags=("disabled",))

    def open_image(self):
        path = filedialog.askopenfilename(title="Open BIOS/IFWI binary", filetypes=[("Binary", "*.bin"), ("All files", "*.*")])
        if not path:
            return
        self.load_image_path(path)

    def load_image_path(self, path):
        try:
            self.image = self.core.OksBiosImage(path)
            self.changed_fields.clear()
            self.path_var.set(path)
            self.update_navigation_state()
            if self.current_softstrap_index() is not None and self.current_softstrap_index() >= self.raw_strap_count():
                self.current_module = "flash_config"
            self.show_module(self.current_module)
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc), parent=self.winfo_toplevel())

    def save_as(self):
        if not self.image:
            return
        path = filedialog.asksaveasfilename(title="Save modified binary", defaultextension=".bin")
        if not path:
            return
        try:
            self.image.save(path, overwrite=True)
            self.changed_fields.clear()
            self.populate_tree()
            messagebox.showinfo("Saved", f"Saved to {path}", parent=self.winfo_toplevel())
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.winfo_toplevel())

    def save_in_place(self):
        if not self.image:
            return
        if not messagebox.askyesno("Confirm", "Modify the input binary in place? A .bak backup is created once.", parent=self.winfo_toplevel()):
            return
        try:
            backup = self.image.save_in_place_with_backup()
            self.changed_fields.clear()
            self.populate_tree()
            messagebox.showinfo("Saved", f"Saved in place. Backup: {backup}", parent=self.winfo_toplevel())
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.winfo_toplevel())

    def populate_tree(self):
        self.hide_inline_editor()
        self.tree.delete(*self.tree.get_children())
        self.row_field_map = {}
        if not self.image:
            return
        if self.search_query():
            self.populate_global_search_results()
            return
        if self.current_module == "boot_guard":
            self.populate_boot_guard()
        elif self.current_module.startswith("softstrap"):
            self.populate_softstrap(self.current_softstrap_index())
        else:
            self.populate_flash_configuration()

    def show_module(self, module):
        self.commit_or_hide_inline_editor()
        if self.search_var.get().strip():
            self.search_var.set("")
        self.current_module = module
        strap_index = self.current_softstrap_index()
        if strap_index is not None and strap_index >= self.raw_strap_count():
            self.status_var.set(f"{self.platform_label()} supports Softstrap0..{self.raw_strap_count() - 1}")
            return
        titles = {"boot_guard": "Boot Guard", "flash_config": "Flash Configuration"}
        for index in range(self.raw_strap_count()):
            titles[f"softstrap{index}"] = f"Softstrap{index}"
        self.module_title_var.set(titles.get(module, "Fit Setting"))
        self.populate_tree()
        self.show_image_summary()

    def search_query(self):
        return self.search_var.get().strip().lower()

    def name_matches_search(self, name):
        query = self.search_query()
        return not query or query in str(name).lower()

    def global_matches_search(self, name, description=""):
        query = self.search_query()
        if not query:
            return True
        haystack = f"{name} {description}".lower()
        return query in haystack

    def flash_matches_search(self, name, description=""):
        return self.global_matches_search(name, description)

    def on_search_changed(self, _event=None):
        self.populate_tree()

    def clear_search(self):
        self.search_var.set("")
        self.populate_tree()

    def insert_group_node(self, text):
        return self.tree.insert("", tk.END, text=text, values=("", ""), open=True, tags=("disabled",))

    def populate_global_search_results(self):
        query = self.search_query()
        if not query:
            return

        flash_items = []
        try:
            summary = self.image.summary()
        except Exception:
            summary = {}
        for region in summary.get("regions", []):
            if not region.get("enabled"):
                continue
            region_name = f"Region {region['index']} - {region['name']}"
            region_desc = "Intel flash descriptor region"
            if self.global_matches_search(region_name, region_desc):
                value = f"base=0x{region['base']:08X}, limit=0x{region['limit']:08X}, size=0x{region['size']:X}"
                flash_items.append((None, region_name, value, region_desc, ("disabled",)))
        for field in self.image_fields():
            if field.group != "flcomp":
                continue
            label = field.name.split(".", 1)[1] if "." in field.name else field.name
            try:
                value = self.image.decode_field(field.name)
            except Exception:
                continue
            if not self.global_matches_search(label, value.description):
                continue
            flash_items.append((field.name, label, self.format_decoded_value(value), value.description, self.row_tags(field.name)))
        if flash_items:
            parent = self.insert_group_node("Flash Configuration")
            for field_name, label, value_text, description, tags in flash_items:
                item_id = field_name or f"global:flash:{label}"
                self.tree.insert(parent, tk.END, iid=item_id, text=label, values=(value_text, description), tags=tags)
                if field_name:
                    self.row_field_map[item_id] = field_name

        boot_items = []
        for index, (label, field_name, description) in enumerate(self.boot_guard_rows()):
            if self.global_matches_search(label, description):
                boot_items.append((index, label, field_name, description))
        if boot_items:
            parent = self.insert_group_node("Boot Guard")
            for index, label, field_name, description in boot_items:
                item_id = f"global:btg:{index}"
                self.tree.insert(parent, tk.END, iid=item_id, text=label, values=(self.boot_guard_value(label, field_name), description), tags=self.row_tags(field_name))
                if field_name:
                    self.row_field_map[item_id] = field_name

        raw_by_name = {raw.name: raw for raw in self.safe_raw_straps()}
        fields_by_register = {}
        for field in self.image_fields():
            if field.group == "softstrap" and not self.is_reserved_field(field.name):
                fields_by_register.setdefault(field.register, []).append(field)
        for index in range(self.raw_strap_count()):
            register = f"IBLStrap{index}"
            raw = raw_by_name.get(register)
            if raw is None:
                continue
            display_name = f"Softstrap{index} ({register})"
            root_matches = self.global_matches_search(display_name, raw.description)
            matching_fields = []
            for field in fields_by_register.get(register, []):
                label = field.name.split(".", 1)[1] if "." in field.name else field.name
                try:
                    value = self.image.decode_field(field.name)
                except Exception:
                    continue
                if not root_matches and not self.global_matches_search(label, value.description):
                    continue
                matching_fields.append((field, value, label))
            if not root_matches and not matching_fields:
                continue
            parent = self.tree.insert("", tk.END, iid=f"global:register:{register}", text=display_name, values=(f"0x{raw.value:x}", raw.description), open=True, tags=self.row_tags(register))
            self.row_field_map[f"global:register:{register}"] = register
            for field, value, label in matching_fields:
                self.tree.insert(parent, tk.END, iid=field.name, text=label, values=(self.format_decoded_value(value), value.description), tags=self.row_tags(field.name))
                self.row_field_map[field.name] = field.name

    def current_softstrap_index(self):
        match = re.fullmatch(r"softstrap(\d+)", self.current_module, flags=re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    def populate_boot_guard(self):
        for index, (label, field_name, description) in enumerate(self.boot_guard_rows()):
            if not self.name_matches_search(label):
                continue
            item_id = f"btg:{index}"
            value = self.boot_guard_value(label, field_name)
            self.tree.insert("", tk.END, iid=item_id, text=label, values=(value, description), tags=self.row_tags(field_name))
            if field_name:
                self.row_field_map[item_id] = field_name

    def populate_softstrap(self, strap_index=None):
        target_register = f"IBLStrap{strap_index}" if strap_index is not None else None
        register_node = ""
        pending_fields = []
        root_matches = False
        for raw in self.safe_raw_straps():
            if target_register and raw.name.lower() != target_register.lower():
                continue
            display_name = f"{self.module_title_var.get()} ({raw.name})" if target_register else raw.name
            root_matches = self.name_matches_search(display_name)
            register_info = (raw, display_name)
            break
        else:
            register_info = None
        for field in self.image_fields():
            if field.group != "softstrap":
                continue
            if target_register and field.register.lower() != target_register.lower():
                continue
            if self.is_reserved_field(field.name):
                continue
            try:
                value = self.image.decode_field(field.name)
            except Exception:
                continue
            label = field.name.split(".", 1)[1] if "." in field.name else field.name
            if root_matches or self.name_matches_search(label):
                pending_fields.append((field, value, label))

        if register_info is None or (self.search_query() and not root_matches and not pending_fields):
            return
        raw, display_name = register_info
        register_node = self.tree.insert("", tk.END, iid=f"register:{raw.name}", text=display_name, values=(f"0x{raw.value:x}", raw.description), open=True, tags=self.row_tags(raw.name))
        self.row_field_map[f"register:{raw.name}"] = raw.name
        for field, value, label in pending_fields:
            self.tree.insert(register_node, tk.END, iid=field.name, text=label, values=(self.format_decoded_value(value), value.description), tags=self.row_tags(field.name))
            self.row_field_map[field.name] = field.name

    def populate_flash_configuration(self):
        try:
            summary = self.image.summary()
        except Exception:
            summary = {}
        for region in summary.get("regions", []):
            if not region.get("enabled"):
                continue
            region_name = f"Region {region['index']} - {region['name']}"
            region_desc = "Intel flash descriptor region"
            if not self.flash_matches_search(region_name, region_desc):
                continue
            value = f"base=0x{region['base']:08X}, limit=0x{region['limit']:08X}, size=0x{region['size']:X}"
            self.tree.insert("", tk.END, text=region_name, values=(value, region_desc), tags=("disabled",))
        for field in self.image_fields():
            if field.group != "flcomp":
                continue
            try:
                value = self.image.decode_field(field.name)
            except Exception:
                continue
            label = field.name.split(".", 1)[1] if "." in field.name else field.name
            if not self.flash_matches_search(label, value.description):
                continue
            self.tree.insert("", tk.END, iid=field.name, text=label, values=(self.format_decoded_value(value), value.description), tags=self.row_tags(field.name))
            self.row_field_map[field.name] = field.name

    def safe_raw_straps(self):
        try:
            return self.image.raw_straps()
        except Exception:
            return []

    def row_tags(self, field_name):
        tags = []
        if not self.is_editable_field(field_name):
            tags.append("disabled")
        else:
            tags.append("editable")
        if field_name and (field_name == self.current_field or field_name in self.changed_fields):
            tags.append("changed")
        return tuple(tags)

    def is_reserved_field(self, field_name):
        return bool(field_name and re.search(r"ReservedBits", field_name, flags=re.IGNORECASE))

    def is_signature_algorithm_field(self, field_name):
        return bool(field_name and field_name.lower() == "btg.signaturealgorithm")

    def is_editable_field(self, field_name):
        if not field_name or self.is_reserved_field(field_name):
            return False
        if self.is_signature_algorithm_field(field_name):
            return True
        if re.fullmatch(r"IBLStrap\d+", field_name, flags=re.IGNORECASE):
            return True
        try:
            field = self.core.find_field(field_name, self.current_platform())
        except Exception:
            return False
        return field.name.lower() not in self.core.READ_ONLY_FIELDS

    def format_decoded_value(self, value):
        if value.decoded:
            return value.decoded
        return f"0x{value.value:x}"

    def boot_guard_value(self, label, field_name):
        if label == "Signature Algorithm":
            return self.signature_algorithm_value()
        if not field_name:
            return "N/A"
        try:
            value = self.image.decode_field(field_name)
        except Exception:
            return "N/A"
        raw = value.value
        if label == "CPU Debugging":
            return "Disabled" if raw else "Enabled"
        if label == "BSP Initialization":
            return "Disabled" if raw else "Enabled"
        if label in ("CONSENT", "NPK Utilize ITH Buffer", "DAM", "OEM Unlock"):
            return "Enabled" if raw else "Disabled"
        if label == "TXT Supported":
            return "Yes" if raw else "No"
        if label in ("ACM SVN", "Key Manifest SVN", "Boot Policy Manifest SVN", "Key Manifest ID"):
            return f"0x{raw:x}"
        if label == "OEM Key Hash Algorithm":
            return self.HASH_ALGORITHMS.get(raw, f"0x{raw:x}")
        return value.decoded or f"0x{raw:x}"

    def signature_algorithm_value(self):
        try:
            low = self.image.decode_field("btg.SignatureAlgorithmLowBit").value
            high = self.image.decode_field("btg.SignatureAlgorithmHighBits").value
            code = (high << 1) | low
            return self.SIGNATURE_ALGORITHMS.get(code, f"0x{code:x}")
        except Exception:
            return "N/A"

    @staticmethod
    def bit_range(low, high):
        return str(low) if low == high else f"{high}:{low}"

    def show_image_summary(self):
        if not self.image:
            return
        self.details.delete("1.0", tk.END)
        try:
            summary = self.image.summary()
            self.details.insert(tk.END, f"Image: {summary['path']}\nPlatform: {summary.get('platform_name', self.platform_label())}\nLayout: {summary.get('layout_name') or 'N/A'}\nSize: 0x{summary['size']:x}\nDescriptor: {'yes' if summary['has_descriptor'] else 'no'}\nFIT offset: 0x{summary['fit_offset']:x}\n")
            microcode = summary.get("microcode", [])
            if microcode:
                unique_signatures = sorted({entry.get("processor_signature") for entry in microcode if entry.get("processor_signature")})
                unique_revisions = sorted({entry.get("update_revision") for entry in microcode if entry.get("update_revision")})
                self.details.insert(tk.END, f"Microcode entries: {len(microcode)}\n")
                if unique_signatures:
                    self.details.insert(tk.END, "CPUIDs: " + ", ".join(self._format_hex(value, 8) for value in unique_signatures) + "\n")
                if unique_revisions:
                    self.details.insert(tk.END, "Microcode revisions: " + ", ".join(self._format_hex(value, 8) for value in unique_revisions) + "\n")
            if summary["btg_offset"] is not None:
                self.details.insert(tk.END, f"BTG offset: 0x{summary['btg_offset']:x}\n")
            if summary.get("btg_crc"):
                crc = summary["btg_crc"]
                self.details.insert(tk.END, f"BTG CRC8: stored=0x{crc['stored']:02x}, calculated=0x{crc['calculated']:02x}, {'valid' if crc['valid'] else 'INVALID'}\n")
            self.details.insert(tk.END, "\nClick an editable Value cell to choose an option or type a new raw value. Gray rows are read-only/informational.\n")
        except Exception as exc:
            self.details.insert(tk.END, str(exc))

    def on_select(self, _event=None):
        if not self.image:
            return
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        field_name = self.row_field_map.get(item_id)
        if not field_name or not self.is_editable_field(field_name):
            self.current_field = None
            self.field_var.set("")
            self.value_var.set("")
            self.tree.selection_remove(selected)
            self.status_var.set("Read-only or informational item")
            return
        self.current_item = item_id
        self.current_field = field_name
        self.field_var.set(field_name)
        try:
            if self.is_signature_algorithm_field(field_name):
                low = self.image.decode_field("btg.SignatureAlgorithmLowBit")
                high = self.image.decode_field("btg.SignatureAlgorithmHighBits")
                value = (high.value << 1) | low.value
                self.value_var.set(hex(value))
                self.details.delete("1.0", tk.END)
                self.details.insert(tk.END, f"Signature Algorithm: {self.SIGNATURE_ALGORITHMS.get(value, f'0x{value:x}')} (0x{value:x})\n")
                self.details.insert(tk.END, "Bits: BTG_POLICY_SVN[15] + BTG_POLICY_KEY_TYPE[1:0]\n")
                self.details.insert(tk.END, "Register: BTG_POLICY_SVN / BTG_POLICY_KEY_TYPE\n")
                self.details.insert(tk.END, "\nDescription: Signature algorithm used by the Boot Guard policy.\n")
                return
            if re.fullmatch(r"IBLStrap\d+", field_name, flags=re.IGNORECASE):
                value = self.image.raw_straps()[int(field_name[8:])]
                matched = None
            else:
                value = self.image.decode_field(field_name)
                matched = self.core.find_field(field_name, self.current_platform())
            self.value_var.set(hex(value.value))
            self.details.delete("1.0", tk.END)
            self.details.insert(tk.END, self.core.value_to_text(value) + "\n")
            if matched:
                self.details.insert(tk.END, f"Bits: {self.bit_range(matched.bit_low, matched.bit_high)}\nRegister: {matched.register}\n")
                if matched.name.lower() in self.core.READ_ONLY_FIELDS:
                    self.details.insert(tk.END, "Access: read-only structural field\n")
            self.details.insert(tk.END, f"\nDescription: {value.description}\n")
            if value.warning:
                self.details.insert(tk.END, f"\nWarning: {value.warning}\n")
        except Exception as exc:
            self.details.delete("1.0", tk.END)
            self.details.insert(tk.END, str(exc))

    def on_tree_click(self, event):
        self.commit_or_hide_inline_editor()
        self.pending_inline_target = None
        return None

    def on_tree_release(self, event=None):
        if event is None:
            return None
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return None
        field_name = self.row_field_map.get(item_id)
        if not self.is_editable_field(field_name):
            self.current_field = None
            self.current_item = None
            self.field_var.set("")
            self.value_var.set("")
            self.tree.selection_remove(self.tree.selection())
            self.status_var.set("Read-only or informational item")
            return "break"

        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self.on_select()
        column_id = self.tree.identify_column(event.x)
        if column_id == "#1":
            self.after_idle(lambda: self.show_inline_value_editor(item_id, field_name))
            return "break"
        return None

    def editor_values_for_field(self, field_name):
        self.option_value_map = {}
        if self.is_signature_algorithm_field(field_name):
            values = []
            for value, text in sorted(self.SIGNATURE_ALGORITHMS.items()):
                label = f"{text} (0x{value:x})"
                self.option_value_map[label] = value
                values.append(label)
            return values
        if re.fullmatch(r"IBLStrap\d+", field_name, flags=re.IGNORECASE):
            return []
        try:
            field = self.core.find_field(field_name, self.current_platform())
        except Exception:
            return []
        if not field.values:
            return []
        values = []
        for value, text in sorted(field.values.items()):
            label = f"{text} (0x{value:x})"
            self.option_value_map[label] = value
            values.append(label)
        return values

    def current_editor_text(self, field_name, values):
        try:
            if self.is_signature_algorithm_field(field_name):
                low = self.image.decode_field("btg.SignatureAlgorithmLowBit").value
                high = self.image.decode_field("btg.SignatureAlgorithmHighBits").value
                value = (high << 1) | low
            elif re.fullmatch(r"IBLStrap\d+", field_name, flags=re.IGNORECASE):
                value = self.image.raw_straps()[int(field_name[8:])].value
            else:
                value = self.image.decode_field(field_name).value
        except Exception:
            return self.value_var.get()
        if values:
            for label, mapped_value in self.option_value_map.items():
                if mapped_value == value:
                    return label
        return f"0x{value:x}"

    def show_inline_value_editor(self, item_id, field_name):
        self.cancel_scheduled_inline_hide()
        bbox = self.tree.bbox(item_id, "value")
        if not bbox:
            return
        values = self.editor_values_for_field(field_name)
        x, y, width, height = bbox
        self.inline_item = item_id
        self.current_item = item_id
        self.current_field = field_name
        self.inline_has_options = bool(values)
        self.value_combo.configure(values=values, state="readonly" if values else "normal")
        self.value_var.set(self.current_editor_text(field_name, values))
        self.inline_original_text = self.value_var.get().strip()
        self.value_combo.place(
            x=self.tree.winfo_x() + x,
            y=self.tree.winfo_y() + y,
            width=width,
            height=max(height, 24),
        )
        self.value_combo.focus_set()
        self.value_combo.select_range(0, tk.END)
        if values:
            self.after(30, self.post_value_combo)

    def post_value_combo(self):
        with contextlib.suppress(tk.TclError):
            self.value_combo.tk.call("ttk::combobox::Post", self.value_combo)

    def hide_inline_editor(self, _event=None):
        self.cancel_scheduled_inline_hide()
        with contextlib.suppress(tk.TclError):
            self.value_combo.place_forget()
        self.inline_item = None
        self.inline_has_options = False
        self.inline_original_text = ""
        self.pending_inline_target = None
        return "break"

    def schedule_hide_inline_editor(self, _event=None):
        if self.inline_has_options:
            return None
        self.cancel_scheduled_inline_hide()
        self.inline_hide_after_id = self.after(150, self.commit_or_hide_inline_editor)
        return None

    def cancel_scheduled_inline_hide(self):
        if self.inline_hide_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self.inline_hide_after_id)
            self.inline_hide_after_id = None

    def commit_or_hide_inline_editor(self):
        self.inline_hide_after_id = None
        if self.inline_item and not self.inline_has_options:
            text = self.value_var.get().strip()
            if text and text != self.inline_original_text:
                return self.apply_inline_value()
        return self.hide_inline_editor()

    def apply_inline_value(self, _event=None):
        text = self.value_var.get().strip()
        if not text or not self.current_field:
            self.hide_inline_editor()
            return "break"
        value = self.option_value_map.get(text, text)
        self.apply_value(value)
        self.hide_inline_editor()
        return "break"

    def apply_value(self, value_text=None):
        if not self.image or not self.current_field:
            return
        if not self.is_editable_field(self.current_field):
            self.status_var.set("Read-only or informational item")
            return
        try:
            value_to_apply = self.value_var.get() if value_text is None else value_text
            if self.is_signature_algorithm_field(self.current_field):
                algorithm = self.core.parse_int(value_to_apply)
                if algorithm not in self.SIGNATURE_ALGORITHMS:
                    raise ValueError(f"Unsupported signature algorithm value: 0x{algorithm:x}")
                self.image.set_field("btg.SignatureAlgorithmLowBit", algorithm & 0x1)
                self.image.set_field("btg.SignatureAlgorithmHighBits", (algorithm >> 1) & 0x3)
            elif re.fullmatch(r"IBLStrap\d+", self.current_field, flags=re.IGNORECASE):
                self.image.set_raw_strap(int(self.current_field[8:]), self.core.parse_int(value_to_apply))
            else:
                self.image.set_field(self.current_field, value_to_apply)
            self.changed_fields.add(self.current_field)
            self.populate_tree()
            target_item = getattr(self, "current_item", None)
            if not target_item or not self.tree.exists(target_item):
                target_item = self.current_field if self.tree.exists(self.current_field) else None
            if target_item:
                self.tree.selection_set(target_item)
                self.tree.see(target_item)
            self.on_select()
            self.show_image_summary()
            self.status_var.set("Change staged in memory")
        except Exception as exc:
            messagebox.showerror("Apply failed", str(exc), parent=self.winfo_toplevel())

    def show(self):
        self.parent.wait_window(self.window)
        return self.result


class CommonUefiFrame(ttk.Frame):
    def __init__(self, master=None, region_change_callback=None):
        super().__init__(master, style="BiosViewer.TFrame")
        self.cui = load_bios_modify_cui()
        self.core = self.cui.fitm_core()
        self.image = None
        self.region_change_callback = region_change_callback
        self._configure_style()
        self._build_ui()

    def _configure_style(self):
        self.colors = {
            "background": "#eef3f8",
            "panel": "#ffffff",
            "border": "#d7e0ea",
            "text": "#1f2937",
            "muted": "#5f6b7a",
            "accent": "#0f6cbd",
            "accent_dark": "#0b4f8a",
        }
        with contextlib.suppress(tk.TclError):
            self.configure(style="BiosViewer.TFrame")
        style = ttk.Style(self)
        style.configure("BiosViewer.TFrame", background=self.colors["background"])
        style.configure("Bios.Treeview", background=self.colors["panel"], fieldbackground=self.colors["panel"], foreground=self.colors["text"], rowheight=25, bordercolor=self.colors["border"], borderwidth=1)
        style.configure("Bios.Treeview.Heading", background="#dbe8f5", foreground=self.colors["text"], font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Bios.Treeview", background=[("selected", self.colors["accent"])], foreground=[("selected", "#ffffff")])

    def _build_ui(self):
        self.row_region_map = {}
        self.row_microcode_map = {}
        self.selected_region_item = None
        self.selected_microcode_item = None
        self.selected_selection_kind = None

        content = ttk.Frame(self, style="BiosViewer.TFrame")
        content.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        tree_panel = ttk.Frame(content, style="BiosViewer.TFrame")
        tree_panel.grid(row=0, column=0, sticky="nsew")
        tree_panel.rowconfigure(0, weight=1)
        tree_panel.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_panel, columns=("value",), show="tree headings", style="Bios.Treeview")
        self.tree.heading("#0", text="UEFI Image Area")
        self.tree.heading("value", text="Value / Status")
        self.tree.column("#0", width=260, minwidth=180)
        self.tree.column("value", width=760, minwidth=360)
        yscroll = ttk.Scrollbar(tree_panel, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")

        self.region_action_frame = ttk.LabelFrame(content, text="Selected Entry Actions", style="Bios.TLabelframe")
        self.region_action_frame.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        self.region_export_button = ttk.Button(self.region_action_frame, text="Export", command=self.export_selected_entry, style="Bios.TButton")
        self.region_replace_button = ttk.Button(self.region_action_frame, text="Replace", command=self.replace_selected_entry, style="Bios.TButton")
        self.region_export_button.pack(fill=tk.X, padx=10, pady=(10, 6))
        self.region_replace_button.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.region_note_var = tk.StringVar(value="Select 1-bios or a microcode row to enable Export / Replace.")
        ttk.Label(self.region_action_frame, textvariable=self.region_note_var, style="BiosStatus.TLabel", wraplength=200, justify=tk.LEFT).pack(anchor=tk.W, padx=10, pady=(0, 10))

        self.mcu_convert_frame = ttk.LabelFrame(content, text="MCU Conversion", style="Bios.TLabelframe")
        self.mcu_convert_frame.grid(row=1, column=1, sticky="new", padx=(12, 0), pady=(12, 0))
        ttk.Button(self.mcu_convert_frame, text="INC to Bin", command=self.convert_mcu_inc_to_bin, style="Bios.TButton").pack(fill=tk.X, padx=10, pady=(10, 6))
        ttk.Button(self.mcu_convert_frame, text="Bin to INC", command=self.convert_mcu_bin_to_inc, style="Bios.TButton").pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Label(
            self.mcu_convert_frame,
            text="Convert MCU include/binary files without loading a BIOS image.",
            style="BiosStatus.TLabel",
            wraplength=200,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=10, pady=(0, 10))

        self._set_region_action_state(False)
        self.show_placeholder()

    def show_placeholder(self):
        self.tree.delete(*self.tree.get_children())
        self.row_region_map = {}
        self.row_microcode_map = {}
        self.selected_region_item = None
        self.selected_microcode_item = None
        self.selected_selection_kind = None
        root = self.tree.insert("", tk.END, text="Common UEFI Decode", values=("Select a BIOS binary to inspect image-level content",))
        self.tree.insert(root, tk.END, text="UEFI driver inventory", values=("Planned",))
        self.tree.insert(root, tk.END, text="Microcode / CPUID inventory", values=("Decode FIT type 1 entries",))
        self.region_note_var.set("Select 1-bios or a microcode row to enable Export / Replace.")

    @staticmethod
    def _format_hex(value, width=0):
        try:
            value = int(value)
        except Exception:
            return "N/A"
        if width:
            return f"0x{value:0{width}X}"
        return f"0x{value:X}"

    @staticmethod
    def _microcode_date_text(raw_date):
        try:
            raw_date = int(raw_date)
        except Exception:
            return "N/A"
        def bcd_byte(value):
            high = (value >> 4) & 0xF
            low = value & 0xF
            if high > 9 or low > 9:
                return None
            return high * 10 + low

        def bcd_word(value):
            digits = [(value >> shift) & 0xF for shift in (12, 8, 4, 0)]
            if any(digit > 9 for digit in digits):
                return None
            return digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]

        month = bcd_byte((raw_date >> 24) & 0xFF)
        day = bcd_byte((raw_date >> 16) & 0xFF)
        year = bcd_word(raw_date & 0xFFFF)
        if month is not None and day is not None and year is not None and 1 <= month <= 12 and 1 <= day <= 31 and 1995 <= year <= 2100:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return f"raw {CommonUefiFrame._format_hex(raw_date, 8)}"

    @staticmethod
    def _decode_cpuid_signature(signature):
        signature = int(signature)
        stepping = signature & 0xF
        base_model = (signature >> 4) & 0xF
        base_family = (signature >> 8) & 0xF
        processor_type = (signature >> 12) & 0x3
        extended_model = (signature >> 16) & 0xF
        extended_family = (signature >> 20) & 0xFF
        display_family = base_family + extended_family if base_family == 0xF else base_family
        display_model = base_model + (extended_model << 4) if base_family in (0x6, 0xF) else base_model
        return {
            "signature": signature,
            "stepping": stepping,
            "base_model": base_model,
            "base_family": base_family,
            "processor_type": processor_type,
            "extended_model": extended_model,
            "extended_family": extended_family,
            "display_family": display_family,
            "display_model": display_model,
        }

    _CPU_FAMILY_SIGNATURES = {
        0xA06D: "GNR-SP",
        0xA06E: "GNR-D",
        0xA06F: "SRF-SP",
        0xD06D: "CWF",
        0xB066: "GrandRidge",
        0x400F0: "DMR-OLD",
        0x400F1: "DMR",
        0x400F2: "DMRHD",
        0x400F4: "PMR",
        0x400F8: "COR",
    }

    @classmethod
    def _cpu_family_text(cls, signature):
        if signature is None:
            return "N/A"
        try:
            signature = int(signature)
        except Exception:
            return "N/A"
        family_key = signature >> 4
        family = cls._CPU_FAMILY_SIGNATURES.get(family_key)
        return family if family else cls._format_hex(signature, 8)

    @staticmethod
    def _checksum32_valid(payload):
        if not payload or len(payload) % 4:
            return None
        total = 0
        for offset in range(0, len(payload), 4):
            total = (total + struct.unpack_from("<I", payload, offset)[0]) & 0xFFFFFFFF
        return total == 0

    def _decode_microcode_entries(self, image):
        data = bytes(image.data)
        decoded = []
        try:
            fit_entries = image.fit_entries()
        except Exception as exc:
            return [{"error": f"FIT table unavailable: {exc}"}]
        for fit_entry in fit_entries:
            try:
                entry_type = int(fit_entry.get("type", -1))
            except Exception:
                continue
            if entry_type != 1:
                continue
            entry = dict(fit_entry)
            offset = int(entry.get("absolute_offset", -1))
            entry["offset"] = offset
            entry["offset_text"] = self._format_hex(offset)
            entry["fit_address_text"] = self._format_hex(entry.get("address", 0))
            if offset < 0 or offset + 48 > len(data):
                entry["status"] = "Out of image range"
                decoded.append(entry)
                continue
            header = data[offset:offset + 48]
            (
                header_version,
                update_revision,
                date_raw,
                processor_signature,
                checksum,
                loader_revision,
                processor_flags,
                data_size,
                total_size,
            ) = struct.unpack_from("<IIIIIIIII", header, 0)
            if total_size == 0:
                total_size = 2048
            if data_size == 0 and total_size >= 48:
                data_size = total_size - 48
            checksum_valid = None
            if 48 <= total_size <= 0x2000000 and offset + total_size <= len(data):
                checksum_valid = self._checksum32_valid(data[offset:offset + total_size])
            cpuid = self._decode_cpuid_signature(processor_signature) if processor_signature else None
            status_parts = []
            if header_version != 1:
                status_parts.append(f"unexpected header version {self._format_hex(header_version)}")
            if loader_revision not in (0, 1):
                status_parts.append(f"loader revision {self._format_hex(loader_revision)}")
            if not processor_signature:
                status_parts.append("processor signature is 0")
            if checksum_valid is True:
                status_parts.append("checksum valid")
            elif checksum_valid is False:
                status_parts.append("checksum not zero")
            elif total_size:
                status_parts.append("checksum not checked")
            entry.update({
                "header_version": header_version,
                "update_revision": update_revision,
                "date_raw": date_raw,
                "processor_signature": processor_signature,
                "checksum": checksum,
                "loader_revision": loader_revision,
                "processor_flags": processor_flags,
                "data_size": data_size,
                "total_size": total_size,
                "date_text": self._microcode_date_text(date_raw),
                "cpuid": cpuid,
                "checksum_valid": checksum_valid,
                "status": "; ".join(status_parts) if status_parts else "decoded",
            })
            decoded.append(entry)
        return decoded

    def _insert_microcode_inventory(self, image):
        microcode_root = self.tree.insert("", tk.END, text="Microcode / CPUID", values=("FIT type 1 entries",))
        entries = self._decode_microcode_entries(image)
        if not entries:
            self.tree.insert(microcode_root, tk.END, text="FIT type 1 entries", values=("None found",))
            return
        unique_signatures = sorted({entry.get("processor_signature") for entry in entries if entry.get("processor_signature")})
        unique_revisions = sorted({entry.get("update_revision") for entry in entries if entry.get("update_revision")})
        summary_text = f"{len(entries)} entries"
        if unique_signatures:
            summary_text += "; CPUIDs " + ", ".join(self._format_hex(value, 8) for value in unique_signatures)
        if unique_revisions:
            summary_text += "; microcode revisions " + ", ".join(self._format_hex(value, 8) for value in unique_revisions)
        self.tree.item(microcode_root, values=(summary_text,))
        for entry in entries:
            if entry.get("error"):
                self.tree.insert(microcode_root, tk.END, text="Decode error", values=(entry["error"],))
                continue
            entry_label = f"FIT index {entry.get('index', 'N/A')} @ {entry.get('offset_text', 'N/A')}"
            entry_item_id = f"microcode:{entry.get('index', 'N/A')}"
            revision_text = self._format_hex(entry.get("update_revision", 0), 8) if "update_revision" in entry else "N/A"
            signature = entry.get("processor_signature")
            cpuid_text = self._format_hex(signature, 8) if signature else "N/A"
            family_text = self._cpu_family_text(signature)
            value = f"CPU Family={family_text}, Microcode revision={revision_text}, CPUID={cpuid_text}, date={entry.get('date_text', 'N/A')}"
            node = self.tree.insert(microcode_root, tk.END, iid=entry_item_id, text=entry_label, values=(value,))
            self.row_microcode_map[entry_item_id] = entry
            self.tree.insert(node, tk.END, text="CPU Family", values=(family_text,))
            self.tree.insert(node, tk.END, text="Microcode Revision", values=(revision_text,))
            self.tree.insert(node, tk.END, text="FIT address", values=(entry.get("fit_address_text", "N/A"),))
            self.tree.insert(node, tk.END, text="Header version", values=(self._format_hex(entry.get("header_version", 0)),))
            self.tree.insert(node, tk.END, text="Loader revision", values=(self._format_hex(entry.get("loader_revision", 0)),))
            self.tree.insert(node, tk.END, text="Processor flags / Platform ID", values=(self._format_hex(entry.get("processor_flags", 0), 8),))
            self.tree.insert(node, tk.END, text="Data size", values=(self._format_hex(entry.get("data_size", 0)),))
            self.tree.insert(node, tk.END, text="Total size", values=(self._format_hex(entry.get("total_size", 0)),))
            self.tree.insert(node, tk.END, text="Checksum", values=(self._format_hex(entry.get("checksum", 0), 8),))
            self.tree.insert(node, tk.END, text="Status", values=(entry.get("status", "decoded"),))
            cpuid = entry.get("cpuid")
            if cpuid:
                cpuid_node = self.tree.insert(node, tk.END, text="CPUID signature decode", values=(cpuid_text,))
                self.tree.insert(cpuid_node, tk.END, text="Stepping ID", values=(self._format_hex(cpuid["stepping"]),))
                self.tree.insert(cpuid_node, tk.END, text="Base model", values=(self._format_hex(cpuid["base_model"]),))
                self.tree.insert(cpuid_node, tk.END, text="Base family", values=(self._format_hex(cpuid["base_family"]),))
                self.tree.insert(cpuid_node, tk.END, text="Processor type", values=(self._format_hex(cpuid["processor_type"]),))
                self.tree.insert(cpuid_node, tk.END, text="Extended model", values=(self._format_hex(cpuid["extended_model"]),))
                self.tree.insert(cpuid_node, tk.END, text="Extended family", values=(self._format_hex(cpuid["extended_family"]),))
                self.tree.insert(cpuid_node, tk.END, text="Display family", values=(self._format_hex(cpuid["display_family"]),))
                self.tree.insert(cpuid_node, tk.END, text="Display model", values=(self._format_hex(cpuid["display_model"]),))

    def load_image_path(self, path):
        self.tree.delete(*self.tree.get_children())
        self.row_region_map = {}
        self.row_microcode_map = {}
        self.selected_region_item = None
        self.selected_microcode_item = None
        self.selected_selection_kind = None
        image_path = os.path.abspath(path)
        image_root = self.tree.insert("", tk.END, text="Image", values=(image_path,))
        try:
            self.tree.insert(image_root, tk.END, text="Size", values=(f"0x{os.path.getsize(image_path):X} bytes",))
        except OSError as exc:
            self.tree.insert(image_root, tk.END, text="Size", values=(str(exc),))

        try:
            image = self.core.OksBiosImage(image_path)
            self.image = image
            summary = image.summary()
            self.tree.insert(image_root, tk.END, text="FITm Platform", values=(summary.get("platform_name") or "Unknown",))
            self.tree.insert(image_root, tk.END, text="FITm Layout", values=(summary.get("layout_name") or "N/A",))
            self.tree.insert(image_root, tk.END, text="Intel Flash Descriptor", values=("Present" if summary.get("has_descriptor") else "Not detected",))
            self.tree.insert(image_root, tk.END, text="FIT Table Offset", values=(f"0x{summary.get('fit_offset', 0):X}",))
            if summary.get("btg_offset") is not None:
                self.tree.insert(image_root, tk.END, text="BTG Block Offset", values=(f"0x{summary['btg_offset']:X}",))
            self._insert_microcode_inventory(image)
            regions = self.tree.insert("", tk.END, text="Flash Regions", values=("Descriptor decode",))
            for region in summary.get("regions", []):
                if region.get("enabled"):
                    item_id = f"region:{region['index']}"
                    self.tree.insert(regions, tk.END, iid=item_id, text=f"{region['index']} - {region['name']}", values=(f"base=0x{region['base']:08X}, limit=0x{region['limit']:08X}, size=0x{region['size']:X}",))
                    self.row_region_map[item_id] = region
                    if region.get("index") == 1 and str(region.get("name", "")).lower() == "bios":
                        self.selected_region_item = item_id
        except Exception as exc:
            self.image = None
            self.tree.insert(image_root, tk.END, text="FIT / descriptor summary", values=(f"Unavailable: {exc}",))

        planned = self.tree.insert("", tk.END, text="Common UEFI Decode", values=("Planned parser area",))
        self.tree.insert(planned, tk.END, text="UEFI drivers / FFS modules", values=("Not implemented yet",))
        if self.selected_region_item and self.tree.exists(self.selected_region_item):
            self.tree.selection_set(self.selected_region_item)
            self.tree.focus(self.selected_region_item)
            self.selected_selection_kind = "region"
            self._set_selection_details("region", self.row_region_map.get(self.selected_region_item))
        else:
            self._set_selection_details(None, None)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selected)

    def _on_tree_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            self._set_selection_details(None, None)
            return
        item_id = selected[0]
        region = self.row_region_map.get(item_id)
        if region:
            self.selected_region_item = item_id
            self.selected_microcode_item = None
            self.selected_selection_kind = "region"
            self._set_selection_details("region", region)
            return
        microcode = self.row_microcode_map.get(item_id)
        if microcode:
            self.selected_microcode_item = item_id
            self.selected_region_item = None
            self.selected_selection_kind = "microcode"
            self._set_selection_details("microcode", microcode)
            return
        self.selected_region_item = None
        self.selected_microcode_item = None
        self.selected_selection_kind = None
        self._set_selection_details(None, None)

    def _set_region_action_state(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.region_export_button.configure(state=state)
        self.region_replace_button.configure(state=state)

    def _set_selection_details(self, kind, entry):
        if not kind or not entry:
            self.region_action_frame.configure(text="Selected Entry Actions")
            self.region_note_var.set("Select 1-bios or a microcode row to enable Export / Replace.")
            self.region_export_button.configure(text="Export")
            self.region_replace_button.configure(text="Replace")
            self._set_region_action_state(False)
            return
        if kind == "region":
            region = entry
            actionable = region.get("index") == 1 and str(region.get("name", "")).lower() == "bios"
            self.region_action_frame.configure(text="BIOS Region Actions")
            self.region_note_var.set(f"{region.get('index')} - {region.get('name', 'region')}: Export and Replace are available only for 1-bios.")
            self.region_export_button.configure(text="Export")
            self.region_replace_button.configure(text="Replace")
            self._set_region_action_state(actionable)
            return
        if kind == "microcode":
            self.region_action_frame.configure(text="Microcode Actions")
            self.region_note_var.set(
                f"FIT index {entry.get('index', 'N/A')}: Export/Replace use Fit Address and total size.\n"
                f"Fit Address={entry.get('fit_address_text', 'N/A')}, Data Size=0x{int(entry.get('data_size') or 0):X}, Total Size=0x{int(entry.get('total_size') or 0):X}"
            )
            self.region_export_button.configure(text="Export")
            self.region_replace_button.configure(text="Replace")
            self._set_region_action_state(True)
            return

    def _selected_entry(self):
        if self.selected_selection_kind == "region" and self.tree.selection():
            item_id = self.tree.selection()[0]
            if item_id in self.row_region_map:
                self.selected_region_item = item_id
                return "region", self.row_region_map.get(item_id)
        if self.selected_selection_kind == "microcode" and self.tree.selection():
            item_id = self.tree.selection()[0]
            if item_id in self.row_microcode_map:
                self.selected_microcode_item = item_id
                return "microcode", self.row_microcode_map.get(item_id)
        if self.selected_selection_kind == "region" and self.selected_region_item:
            return self.selected_selection_kind, self.row_region_map.get(self.selected_region_item)
        if self.selected_selection_kind == "microcode" and self.selected_microcode_item:
            return self.selected_selection_kind, self.row_microcode_map.get(self.selected_microcode_item)
        return None, None

    def _microcode_slot_size(self, entry):
        if not self.image:
            raise RuntimeError("No BIOS image is loaded.")
        try:
            current_index = int(entry.get("index"))
            current_offset = int(entry.get("offset"))
        except Exception as exc:
            raise RuntimeError("Microcode entry metadata is invalid") from exc

        fit_entries = []
        for fit_entry in self.image.fit_entries():
            try:
                fit_index = int(fit_entry.get("index", -1))
                fit_offset = int(fit_entry.get("absolute_offset", -1))
            except Exception:
                continue
            if fit_index < 0 or fit_offset < 0:
                continue
            fit_entries.append({"index": fit_index, "offset": fit_offset})

        fit_entries.sort(key=lambda item: item["index"])
        position = next((idx for idx, item in enumerate(fit_entries) if item["index"] == current_index), None)
        if position is None:
            raise RuntimeError(f"FIT index {current_index} was not found in the FIT table")

        if current_index <= 1:
            neighbor_position = position + 1
        else:
            neighbor_position = position - 1

        if neighbor_position < 0 or neighbor_position >= len(fit_entries):
            raise RuntimeError(f"Unable to determine the replacement slot size for FIT index {current_index}")

        neighbor_offset = fit_entries[neighbor_position]["offset"]
        slot_size = abs(current_offset - neighbor_offset)
        if slot_size == 0:
            raise RuntimeError(f"Invalid replacement slot size {slot_size} for FIT index {current_index}")
        return slot_size

    def export_selected_entry(self):
        kind, entry = self._selected_entry()
        if not kind or not entry:
            return
        try:
            if kind == "region":
                self._export_bios_region(entry)
            elif kind == "microcode":
                self._export_microcode_entry(entry)
        except Exception as exc:
            messagebox.showerror("Export", str(exc), parent=self.winfo_toplevel())

    def replace_selected_entry(self):
        kind, entry = self._selected_entry()
        if not kind or not entry:
            return
        try:
            if kind == "region":
                self._replace_bios_region(entry)
            elif kind == "microcode":
                self._replace_microcode_entry(entry)
        except Exception as exc:
            messagebox.showerror("Replace", str(exc), parent=self.winfo_toplevel())

    def _confirm_output_overwrite(self, output_path):
        if os.path.exists(output_path):
            return messagebox.askyesno(
                "Overwrite Output",
                f"{output_path}\n\nOverwrite this file?",
                parent=self.winfo_toplevel(),
            )
        return True

    def _default_outimage_path(self):
        if not self.image:
            raise RuntimeError("No BIOS image is loaded.")
        return str(Path(self.image.path).with_name("outimage.bin"))

    def _save_replaced_image_as_outimage(self, output_path, selected_item=None):
        self.image.save(output_path, overwrite=True)
        self.load_image_path(output_path)
        if selected_item and self.tree.exists(selected_item):
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
            self._on_tree_selected()
        if self.region_change_callback:
            self.region_change_callback(self.image)

    def convert_mcu_inc_to_bin(self):
        inc_path = filedialog.askopenfilename(
            title="Select MCU INC file",
            filetypes=(("INC files", "*.inc *.txt"), ("All files", "*.*")),
            parent=self.winfo_toplevel(),
        )
        if not inc_path:
            return
        output_path = str(Path(inc_path).with_suffix(".bin"))
        if not self._confirm_output_overwrite(output_path):
            return
        try:
            binary, stats = self.cui.convert_mcu_inc_to_bin(inc_path)
            Path(output_path).write_bytes(binary)
        except Exception as exc:
            messagebox.showerror("MCU INC to Bin", str(exc), parent=self.winfo_toplevel())
            return
        messagebox.showinfo(
            "MCU INC to Bin",
            f"Converted MCU INC to BIN:\n{output_path}\n\nLiterals={stats.get('literals_found', 0)}\nBytes={stats.get('bytes_emitted', 0)}",
            parent=self.winfo_toplevel(),
        )

    def convert_mcu_bin_to_inc(self):
        bin_path = filedialog.askopenfilename(
            title="Select MCU BIN file",
            filetypes=(("Binary files", "*.bin *.pdb *.mcb *.rom *.fd *.cap"), ("All files", "*.*")),
            parent=self.winfo_toplevel(),
        )
        if not bin_path:
            return
        output_path = str(Path(bin_path).with_suffix(".inc"))
        if not self._confirm_output_overwrite(output_path):
            return
        try:
            inc_text, stats = self.cui.convert_mcu_bin_to_inc(bin_path)
            Path(output_path).write_text(inc_text, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("MCU Bin to INC", str(exc), parent=self.winfo_toplevel())
            return
        messagebox.showinfo(
            "MCU Bin to INC",
            f"Converted MCU BIN to INC:\n{output_path}\n\nDWORDs={stats.get('dwords_emitted', 0)}\nBytes={stats.get('bytes_read', 0)}",
            parent=self.winfo_toplevel(),
        )

    def _export_bios_region(self, region):
        if not self.image:
            return
        export_dir = filedialog.askdirectory(title="Choose export directory", parent=self.winfo_toplevel())
        if not export_dir:
            return
        export_name = f"{Path(self.image.path).stem}_bios_region.bin"
        export_path = os.path.join(export_dir, export_name)
        if os.path.exists(export_path) and not messagebox.askyesno("Overwrite export", f"{export_path}\n\nOverwrite this file?", parent=self.winfo_toplevel()):
            return
        base = int(region.get("base") or 0)
        limit = int(region.get("limit") or 0)
        size = int(region.get("size") or 0)
        if base < 0 or limit < base or size <= 0:
            raise ValueError("BIOS region base/limit/size are invalid")
        export_data = bytes(self.image.data[base:base + size])
        if len(export_data) != size:
            raise ValueError(f"BIOS region slice length {len(export_data)} does not match region size {size}")
        Path(export_path).write_bytes(export_data)
        messagebox.showinfo(
            "Export BIOS Region",
            f"Exported BIOS region slice to:\n{export_path}\n\nBytes={len(export_data)}\nBase=0x{base:08X}, Limit=0x{limit:08X}, Size=0x{size:X}",
            parent=self.winfo_toplevel(),
        )

    def _replace_bios_region(self, region):
        if not self.image:
            return
        replacement_path = filedialog.askopenfilename(
            title="Select BIOS binary to replace the region",
            filetypes=(("BIOS binary files", "*.bin *.rom *.fd *.cap"), ("All files", "*.*")),
            parent=self.winfo_toplevel(),
        )
        if not replacement_path:
            return
        replacement_data = Path(replacement_path).read_bytes()
        if len(replacement_data) > region["size"]:
            messagebox.showerror(
                "Replace BIOS Region",
                (
                    f"Selected BIOS binary size {len(replacement_data)} bytes exceeds current 1-bios size {region['size']} bytes.\n"
                    "Cannot replace the BIOS region."
                ),
                parent=self.winfo_toplevel(),
            )
            return
        output_path = self._default_outimage_path()
        if not messagebox.askyesno(
            "Replace BIOS Region",
            f"Replace region 1-bios with:\n{replacement_path}\n\nThe original image will not be modified. A new BIOS image will be written to:\n{output_path}\n\nThe replacement may be smaller than 1-bios; the rest will be padded with 0xFF. Continue?",
            parent=self.winfo_toplevel(),
        ):
            return
        if not self._confirm_output_overwrite(output_path):
            return
        self.image.replace_region_bytes(region["index"], replacement_data)
        self._save_replaced_image_as_outimage(output_path, selected_item=self.selected_region_item)
        messagebox.showinfo("Replace BIOS Region", f"Generated new BIOS image:\n{output_path}\n\nOriginal image was not modified.\nSource: {replacement_path}", parent=self.winfo_toplevel())

    def _export_microcode_entry(self, entry):
        if not self.image:
            return
        export_dir = filedialog.askdirectory(title="Choose export directory", parent=self.winfo_toplevel())
        if not export_dir:
            return
        export_name = f"{Path(self.image.path).stem}_fit{entry.get('index', 'N_A')}_microcode.bin"
        export_path = os.path.join(export_dir, export_name)
        if os.path.exists(export_path) and not messagebox.askyesno("Overwrite export", f"{export_path}\n\nOverwrite this file?", parent=self.winfo_toplevel()):
            return
        offset = int(entry.get("offset") or 0)
        total_size = int(entry.get("total_size") or 0)
        if offset < 0 or total_size <= 0 or offset + total_size > len(self.image.data):
            raise ValueError("Microcode entry range is invalid in the current image")
        Path(export_path).write_bytes(bytes(self.image.data[offset:offset + total_size]))
        messagebox.showinfo("Export Microcode", f"Exported microcode entry to:\n{export_path}", parent=self.winfo_toplevel())

    def _replace_microcode_entry(self, entry):
        if not self.image:
            return
        replacement_path = filedialog.askopenfilename(
            title="Select microcode BIN or INC to replace the entry",
            filetypes=(("Microcode files", "*.bin *.inc *.rom *.cap *.fd"), ("Binary files", "*.bin *.rom *.cap *.fd"), ("INC files", "*.inc"), ("All files", "*.*")),
            parent=self.winfo_toplevel(),
        )
        if not replacement_path:
            return
        replacement_file = Path(replacement_path)
        conversion_stats = None
        if replacement_file.suffix.lower() == ".inc":
            messagebox.showinfo(
                "Replace Microcode",
                "Detected an INC file. It will be automatically converted to BIN data before replacing the selected microcode entry.",
                parent=self.winfo_toplevel(),
            )
            replacement_data, conversion_stats = self.cui.convert_mcu_inc_to_bin(replacement_file)
        else:
            replacement_data = replacement_file.read_bytes()
        slot_size = self._microcode_slot_size(entry)
        if len(replacement_data) > slot_size:
            messagebox.showerror(
                "Replace Microcode",
                (
                    f"Selected replacement size {len(replacement_data)} bytes exceeds the available microcode slot size 0x{slot_size:X}.\n"
                    "Cannot replace the microcode entry."
                ),
                parent=self.winfo_toplevel(),
            )
            return
        conversion_text = ""
        if conversion_stats:
            conversion_text = f"\n\nINC conversion: Literals={conversion_stats.get('literals_found', 0)}, Bytes={conversion_stats.get('bytes_emitted', 0)}"
        if not messagebox.askyesno(
            "Replace Microcode",
            f"Replace FIT index {entry.get('index', 'N/A')} with:\n{replacement_path}{conversion_text}\n\nThe original image will not be modified. A new BIOS image will be written to:\n{self._default_outimage_path()}\n\nContinue?",
            parent=self.winfo_toplevel(),
        ):
            return
        output_path = self._default_outimage_path()
        if not self._confirm_output_overwrite(output_path):
            return
        offset = int(entry.get("offset") or 0)
        if offset < 0 or offset + slot_size > len(self.image.data):
            raise ValueError("Microcode entry range is invalid in the current image")
        self.image.data[offset:offset + slot_size] = replacement_data.ljust(slot_size, b"\xff")
        self._save_replaced_image_as_outimage(output_path, selected_item=self.selected_microcode_item)
        messagebox.showinfo(
            "Replace Microcode",
            f"Generated new BIOS image:\n{output_path}\n\nOriginal image was not modified.\nSource: {replacement_path}{conversion_text}",
            parent=self.winfo_toplevel(),
        )


class OfflineBinaryDecodeFrame(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12, style="Export.TFrame")
        self.app = app
        self.decode_thread = None
        self.bios_path_var = app.bios_bin_var
        self.output_dir_var = app.output_dir_var
        self.status_var = tk.StringVar(value="Select a BIOS binary to decode")
        self.knob_viewer = None
        self.current_bios_path = ""
        self.current_xml_path = ""
        self._flash_image_path = ""
        self._uefi_image_path = ""
        self._flash_loaded_path = ""
        self._uefi_loaded_path = ""
        self._build_ui()

    def _build_ui(self):
        selector = ttk.Frame(self, style="Export.TFrame")
        selector.pack(fill=tk.X, pady=(0, 8))
        selector.columnconfigure(1, weight=1)
        ttk.Label(selector, text="BIOS Binary", style="Export.TLabel").grid(row=0, column=0, sticky=tk.W, padx=10, pady=6)
        ttk.Entry(selector, textvariable=self.bios_path_var).grid(row=0, column=1, sticky=tk.EW, padx=10, pady=6)
        ttk.Button(selector, text="Browse", command=self.browse_bios_binary, style="Export.TButton").grid(row=0, column=2, sticky=tk.E, padx=10, pady=6)
        self.decode_button = ttk.Button(selector, text="Decode Binary", command=self.decode_selected_binary, style="ExportAccent.TButton")
        self.decode_button.grid(row=0, column=3, sticky=tk.E, padx=10, pady=6)
        self.save_actions = ttk.Frame(selector, style="Export.TFrame")
        self.save_as_button = ttk.Button(self.save_actions, text="Rebuild Binary", command=self.save_as, state=tk.DISABLED, style="Export.TButton")
        self.replace_button = ttk.Button(self.save_actions, text="Replace", command=self.replace_current_binary, state=tk.DISABLED, style="Export.TButton")
        self.save_as_button.pack(side=tk.LEFT)
        self._show_save_buttons()
        ttk.Label(selector, textvariable=self.status_var, style="ExportStatus.TLabel").grid(row=1, column=3, sticky=tk.E, padx=10, pady=6)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(0, 8))
        self.progress.pack_forget()

        content = ttk.Frame(self, style="Export.TFrame")
        content.pack(fill=tk.BOTH, expand=True)

        self.navigation = ttk.Frame(content, style="Export.TFrame")

        self.pages = ttk.Frame(content, style="Export.TFrame")
        self.pages.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.pages.rowconfigure(0, weight=1)
        self.pages.columnconfigure(0, weight=1)

        self.knobs_tab = ttk.Frame(self.pages, style="Export.TFrame")
        self.flash_tab = ttk.Frame(self.pages, style="Export.TFrame")
        self.uefi_tab = ttk.Frame(self.pages, style="Export.TFrame")
        self.offline_pages = {
            "knobs": self.knobs_tab,
            "flash": self.flash_tab,
            "uefi": self.uefi_tab,
        }
        self.offline_nav_buttons = {}
        for page in self.offline_pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        for key, label in (("knobs", "BIOS Knobs"), ("flash", "Fit Setting"), ("uefi", "Common UEFI")):
            button = ttk.Button(self.navigation, text=label, command=lambda page_key=key: self._select_offline_view(page_key), style="Export.TButton")
            button.pack(fill=tk.X, pady=(0, 6))
            self.offline_nav_buttons[key] = button

        self.knob_placeholder = ttk.Label(self.knobs_tab, text="BIOS knob view will appear here after decoding a binary.", style="ExportStatus.TLabel")
        self.knob_placeholder.pack(anchor=tk.W, padx=12, pady=12)
        self.flash_viewer = FitmEditorFrame(self.flash_tab, show_file_toolbar=False)
        self.flash_viewer.pack(fill=tk.BOTH, expand=True)
        self.uefi_viewer = CommonUefiFrame(self.uefi_tab, region_change_callback=self._sync_region_changes)
        self.uefi_viewer.pack(fill=tk.BOTH, expand=True)
        self._select_offline_view("knobs")

    def _show_offline_navigation(self):
        if not self.navigation.winfo_ismapped():
            self.navigation.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), pady=(5, 0), before=self.pages)

    def _select_offline_view(self, page_key):
        page = self.offline_pages[page_key]
        page.tkraise()
        for key, button in self.offline_nav_buttons.items():
            button.configure(state=tk.DISABLED if key == page_key else tk.NORMAL)
        if page_key == "flash":
            self._ensure_flash_view_loaded()
        elif page_key == "uefi":
            self._ensure_uefi_view_loaded()

    def _ensure_flash_view_loaded(self):
        if not self._flash_image_path or self._flash_loaded_path == self._flash_image_path:
            return
        self.flash_viewer.load_image_path(self._flash_image_path)
        self._flash_loaded_path = self._flash_image_path

    def _ensure_uefi_view_loaded(self):
        if not self._uefi_image_path or self._uefi_loaded_path == self._uefi_image_path:
            return
        self.uefi_viewer.load_image_path(self._uefi_image_path)
        self._uefi_loaded_path = self._uefi_image_path

    def _sync_region_changes(self, image):
        if image is None:
            return
        self._ensure_flash_view_loaded()
        if self.flash_viewer.image is not None:
            self.flash_viewer.image.data[:] = image.data

    def browse_bios_binary(self):
        self.app._browse_bios_binary()
        if self.bios_path_var.get().strip():
            self.output_dir_var.set(os.path.dirname(os.path.abspath(self.bios_path_var.get().strip())))
            self.status_var.set("BIOS binary selected. Click Decode Binary to decode.")

    def decode_selected_binary(self):
        bios_bin = self.bios_path_var.get().strip()
        output_dir = os.path.dirname(os.path.abspath(bios_bin))
        if not bios_bin:
            messagebox.showerror("Missing BIOS Binary", "Please select a BIOS binary file.", parent=self.winfo_toplevel())
            return
        if not os.path.isfile(bios_bin):
            messagebox.showerror("Invalid BIOS Binary", "Please select a valid BIOS binary file.", parent=self.winfo_toplevel())
            return
        if self.decode_thread and self.decode_thread.is_alive():
            return
        self.output_dir_var.set(output_dir)
        self._set_running(True, "Decoding BIOS binary...")
        self.decode_thread = threading.Thread(target=self._decode_worker, args=(bios_bin, output_dir), daemon=True)
        self.decode_thread.start()

    def _decode_worker(self, bios_bin, output_dir):
        xml_path = ""
        metadata = {}
        knobs = []
        knob_error = None
        try:
            os.makedirs(output_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            xml_path = os.path.join(output_dir, f"BIOS_Binary_Knob_{stamp}.xml")
            run_offline_xmlcli_export(xml_path, bios_bin)
            metadata, knobs = parse_bios_knob_xml(xml_path)
        except Exception as exc:
            knob_error = str(exc)
        self.after(0, lambda: self._decode_complete(bios_bin, xml_path, metadata, knobs, knob_error))

    def _decode_complete(self, bios_bin, xml_path, metadata, knobs, knob_error=None):
        self.current_bios_path = os.path.abspath(bios_bin)
        self.bios_path_var.set(self.current_bios_path)
        self.current_xml_path = os.path.abspath(xml_path) if xml_path else ""
        self._flash_image_path = self.current_bios_path
        self._uefi_image_path = self.current_bios_path
        self._flash_loaded_path = ""
        self._uefi_loaded_path = ""
        decode_source = metadata.get("decode_type") or "BiosKnobsDataBin"
        knob_count = len(knobs or [])
        knob_missing = bool(knob_error) or knob_count == 0

        if knob_missing:
            self._show_knob_message("No BIOS knobs were found in this binary. Fit Setting and Common UEFI decode can still be used.")
        else:
            self._show_knob_viewer(xml_path, metadata, knobs)

        self._show_offline_navigation()
        if knob_missing:
            detail = f"\n\nDetails: {knob_error}" if knob_error else ""
            messagebox.showinfo(
                "BIOS Knobs Not Found",
                f"No BIOS knobs were found in this binary. Fit Setting and Common UEFI views are still available.\nDecode source: {decode_source}{detail}",
                parent=self.winfo_toplevel(),
            )

        status = (
            f"Decoded {knob_count} BIOS knob(s); source: {decode_source}"
            if not knob_missing
            else f"BIOS knobs not found; source: {decode_source}"
        )
        self._set_running(False, status)
        self.save_as_button.configure(state=tk.NORMAL)
        self.replace_button.configure(state=tk.NORMAL)

    def _decode_failed(self, error):
        self._set_running(False, "Decode failed")
        messagebox.showerror("Offline BIOS Decode", str(error), parent=self.winfo_toplevel())

    def _show_knob_viewer(self, xml_path, metadata, knobs):
        for child in self.knobs_tab.winfo_children():
            child.destroy()
        self.knob_viewer = BiosSetupViewer(
            self.knobs_tab,
            xml_path,
            target_settings_getter=self.app._offline_target_settings,
            metadata=metadata,
            knobs=knobs,
            embedded=True,
            show_toolbar_actions=False,
            show_setup_menu=False,
        )

    def _show_knob_message(self, message):
        for child in self.knobs_tab.winfo_children():
            child.destroy()
        self.knob_viewer = None
        ttk.Label(self.knobs_tab, text=message, style="ExportStatus.TLabel", wraplength=720, justify=tk.LEFT).pack(anchor=tk.W, padx=12, pady=12)

    def save_as(self):
        if not self.current_bios_path:
            return
        source = os.path.abspath(self.current_bios_path)
        source_dir = os.path.dirname(source)
        stem, ext = os.path.splitext(os.path.basename(source))
        if not ext:
            ext = ".bin"
        output_path = filedialog.asksaveasfilename(
            title="Save modified BIOS binary",
            initialdir=source_dir,
            initialfile=f"{stem}_modified{ext}",
            defaultextension=ext,
            filetypes=(("BIOS binary files", "*.bin *.rom *.fd *.cap"), ("All files", "*.*")),
            parent=self.winfo_toplevel(),
        )
        if not output_path:
            return
        self._save_current_state(output_path, replace=False)

    def replace_current_binary(self):
        if not self.current_bios_path:
            return
        if not messagebox.askyesno(
            "Replace BIOS Binary",
            "This will overwrite the currently decoded BIOS binary with all staged BIOS knob and flash-region changes.\n\nContinue?",
            parent=self.winfo_toplevel(),
        ):
            return
        self._save_current_state(self.current_bios_path, replace=True)

    def _save_current_state(self, output_path, replace=False):
        try:
            saved_path = self._write_current_binary(output_path)
        except Exception as exc:
            messagebox.showerror("Save BIOS Binary", str(exc), parent=self.winfo_toplevel())
            return
        saved_path = os.path.abspath(saved_path)
        if replace:
            self.current_bios_path = saved_path
            self.bios_path_var.set(self.current_bios_path)
            self.output_dir_var.set(os.path.dirname(self.current_bios_path))
            self._commit_pending_knob_values()
            self._flash_image_path = self.current_bios_path
            self._uefi_image_path = self.current_bios_path
            if self._flash_loaded_path == self.current_bios_path:
                self._ensure_flash_view_loaded()
            if self._uefi_loaded_path == self.current_bios_path:
                self._ensure_uefi_view_loaded()
        else:
            self.output_dir_var.set(os.path.dirname(saved_path))
        action = "Replaced" if replace else "Saved"
        self.status_var.set(f"{action}: {saved_path}")
        self._show_save_buttons()
        self.save_as_button.configure(state=tk.NORMAL)
        self.replace_button.configure(state=tk.NORMAL)
        messagebox.showinfo("Save BIOS Binary", f"{action} BIOS binary:\n{saved_path}", parent=self.winfo_toplevel())

    def _show_save_buttons(self):
        self.save_actions.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=10, pady=6)
        if not self.save_as_button.winfo_manager():
            self.save_as_button.pack(side=tk.LEFT)
        if self.replace_button.winfo_manager():
            self.replace_button.pack_forget()

    def _write_current_binary(self, output_path):
        output_path = os.path.abspath(output_path)
        source_path = os.path.abspath(self.current_bios_path or self.bios_path_var.get().strip())
        if not source_path or not os.path.isfile(source_path):
            raise RuntimeError("No decoded BIOS binary is available to save.")
        assignments = self._pending_knob_assignments()
        core = load_bios_modify_cui()
        temp_path = None
        try:
            base_path = source_path
            if self.flash_viewer.image is not None:
                if assignments:
                    temp_path = os.path.join(os.path.dirname(output_path), f".{os.path.basename(output_path)}.flash.tmp")
                    self.flash_viewer.image.save(temp_path, overwrite=True)
                    base_path = temp_path
                else:
                    self.flash_viewer.image.save(output_path, overwrite=True)
                    return output_path
            elif not assignments:
                if os.path.abspath(source_path) != output_path:
                    shutil.copy2(source_path, output_path)
                return output_path

            if assignments:
                if os.path.abspath(base_path) == output_path:
                    temp_path = os.path.join(os.path.dirname(output_path), f".{os.path.basename(output_path)}.knob.tmp")
                    shutil.copy2(base_path, temp_path)
                    base_path = temp_path
                core.patch_bios_file(core.Path(base_path), core.Path(output_path), assignments)
            return output_path
        finally:
            if temp_path and os.path.exists(temp_path):
                with contextlib.suppress(OSError):
                    os.remove(temp_path)

    def _pending_knob_assignments(self):
        if self.knob_viewer is None:
            return []
        return [f"{name}={value}" for name, value in self.knob_viewer.pending_changes.items()]

    def _commit_pending_knob_values(self):
        if self.knob_viewer is None or not self.knob_viewer.pending_changes:
            return
        for knob in self.knob_viewer.knobs:
            if knob["name"] in self.knob_viewer.pending_changes:
                value = self.knob_viewer.pending_changes[knob["name"]]
                knob["current_value"] = value
                knob["current_text"] = resolve_option_text(knob.get("options", []), value)
        self.knob_viewer.pending_changes.clear()
        self.knob_viewer._update_pending_label()
        self.knob_viewer._apply_filter()

    def _set_running(self, running, message):
        self.status_var.set(message)
        self.decode_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        if hasattr(self, "save_as_button"):
            state = tk.DISABLED if running or not self.current_bios_path else tk.NORMAL
            self.save_as_button.configure(state=state)
            self.replace_button.configure(state=state)
        if running:
            self.progress.pack(fill=tk.X, pady=(0, 8))
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()


class LoadingDialog:
    def __init__(self, parent, title, message):
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("360x120")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.attributes("-topmost", True)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=message).pack(anchor=tk.W, pady=(0, 12))
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill=tk.X)
        self.progress.start(12)
        self.window.update_idletasks()

        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        win_w = self.window.winfo_width()
        win_h = self.window.winfo_height()
        x = parent_x + max((parent_w - win_w) // 2, 0)
        y = parent_y + max((parent_h - win_h) // 2, 0)
        self.window.geometry(f"+{x}+{y}")

    def close(self):
        with contextlib.suppress(tk.TclError):
            self.progress.stop()
            self.window.grab_release()
            self.window.destroy()


class CommandDialog:
    def __init__(self, parent, title, command_text):
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("720x380")
        self.window.minsize(620, 320)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self._ignore_close)
        self.finished = False

        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="Running command...")
        ttk.Label(frame, textvariable=self.status_var).pack(anchor=tk.W, pady=(0, 8))

        if command_text:
            command_frame = ttk.LabelFrame(frame, text="Command")
            command_frame.pack(fill=tk.X, pady=(0, 8))
            command_label = ttk.Label(command_frame, text=command_text, wraplength=660)
            command_label.pack(anchor=tk.W, padx=8, pady=6)

        log_frame = ttk.LabelFrame(frame, text="Output")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.output_text = tk.Text(log_frame, wrap=tk.WORD, height=10, state=tk.DISABLED)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.output_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.configure(yscrollcommand=scrollbar.set)

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=(8, 0))
        self.close_button = ttk.Button(button_frame, text="Close", command=self.close, state=tk.DISABLED)
        self.close_button.pack(side=tk.RIGHT)

        self.window.update_idletasks()
        self._center(parent)

    def _center(self, parent):
        parent.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        win_w = self.window.winfo_width()
        win_h = self.window.winfo_height()
        x = parent_x + max((parent_w - win_w) // 2, 0)
        y = parent_y + max((parent_h - win_h) // 2, 0)
        self.window.geometry(f"+{x}+{y}")

    def _ignore_close(self):
        if self.finished:
            self.close()

    def append(self, text):
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
        self.output_text.configure(state=tk.DISABLED)
        self.window.update_idletasks()

    def finish(self, success, message):
        self.finished = True
        prefix = "Completed" if success else "Failed"
        self.status_var.set(f"{prefix}: {message}")
        self.append("\n" + message + "\n")
        self.close_button.configure(state=tk.NORMAL)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        if not self.finished:
            return
        with contextlib.suppress(tk.TclError):
            self.window.grab_release()
            self.window.destroy()


class BiosKnobExportApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"BIOS Automation Tool v{__version__}")
        self.root.geometry("1280x820")
        self.root.minsize(980, 640)

        self.log_queue = queue.Queue()
        self.worker_thread = None
        self.config = self._load_config()
        self.remote_system_profiles = self._load_remote_system_profiles()
        self.remote_system_profile_map = {profile["label"]: profile for profile in self.remote_system_profiles}

        self.mode_var = tk.StringVar(value="local")
        self.remote_system_var = tk.StringVar(value="Manual Input")
        self.host_var = tk.StringVar(value=self.config.get("host", ""))
        self.port_var = tk.StringVar(value="22")
        self.user_var = tk.StringVar(value=self.config.get("user", ""))
        self.password_var = tk.StringVar(value="")
        self.remote_file_var = tk.StringVar(value=r"C:\BIOS_Knob.xml")
        self.bios_bin_var = tk.StringVar(value="")
        default_output_dir = self.config.get("bios_knob_output_dir") or os.path.join(
            self.config.get("rak_result_dir", os.getcwd()), "bios_knobs"
        )
        self.output_dir_var = tk.StringVar(value=default_output_dir)
        self.status_var = tk.StringVar(value="Ready")
        self.remote_widgets = []
        self.offline_widgets = []
        self.remote_widget_grid = {}
        self.offline_widget_grid = {}
        self.remote_section = None
        self.local_output_section = None
        self.loading_dialog = None
        self.command_dialog = None
        self.viewer_load_in_progress = False

        self._configure_style()
        self._build_ui()
        self._update_mode_state()
        self.root.after(100, self._pump_log_queue)

    def _configure_style(self):
        self.colors = {
            "background": "#f3f6fa",
            "panel": "#ffffff",
            "panel_alt": "#f7f9fc",
            "selection_bg": "#0b4f8a",
            "border": "#d6dee8",
            "text": "#1f2937",
            "muted": "#5f6b7a",
            "accent": "#0f6cbd",
            "accent_dark": "#0b4f8a",
        }
        self.root.configure(bg=self.colors["background"])
        style = ttk.Style(self.root)
        with contextlib.suppress(tk.TclError):
            style.theme_use("clam")

        style.configure("Export.TFrame", background=self.colors["background"])
        style.configure("ExportPanel.TFrame", background=self.colors["panel"])
        style.configure("Selection.TFrame", background=self.colors["selection_bg"])
        style.configure("Selection.TLabel", background=self.colors["selection_bg"], foreground="#ffffff")
        style.configure(
            "Selection.TCombobox",
            fieldbackground=self.colors["selection_bg"],
            background=self.colors["selection_bg"],
            foreground="#ffffff",
            arrowcolor="#ffffff",
        )
        style.map(
            "Selection.TCombobox",
            fieldbackground=[("readonly", self.colors["selection_bg"]), ("!readonly", self.colors["selection_bg"]), ("active", self.colors["selection_bg"])],
            background=[("readonly", self.colors["selection_bg"]), ("!readonly", self.colors["selection_bg"]), ("active", self.colors["selection_bg"])],
            foreground=[("readonly", "#ffffff"), ("!readonly", "#ffffff"), ("active", "#ffffff")],
            arrowcolor=[("readonly", "#ffffff"), ("!readonly", "#ffffff"), ("active", "#ffffff")],
        )
        style.configure("Export.TLabel", background=self.colors["panel"], foreground=self.colors["text"])
        style.configure("ExportStatus.TLabel", background=self.colors["background"], foreground=self.colors["muted"])
        style.configure("Export.TLabelframe", background=self.colors["panel"], bordercolor=self.colors["border"], relief="solid")
        style.configure("Export.TLabelframe.Label", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 9, "bold"))
        style.configure("TButton", padding=(10, 5), background=self.colors["accent"], foreground="#ffffff")
        style.map("TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])
        style.configure("Export.TButton", padding=(10, 5), background=self.colors["accent"], foreground="#ffffff")
        style.map("Export.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])
        style.configure("ExportAccent.TButton", padding=(12, 5), background=self.colors["accent"], foreground="#ffffff")
        style.map("ExportAccent.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#b8c7d8")], foreground=[("disabled", "#f2f5f8")])

    def _load_config(self):
        if not os.path.isfile(CONFIG_FILE):
            return {}
        try:
            return load_config(CONFIG_FILE)
        except Exception as error:
            messagebox.showwarning("Config Load Warning", f"Failed to load config:\n{error}", parent=self.root)
            return {}

    def _load_remote_system_profiles(self):
        raw_profiles = []
        for source_path in (REMOTE_SYSTEM_INFO_FILE, REMOTE_SYSTEM_INFO_FALLBACK_FILE):
            if not os.path.isfile(source_path):
                continue
            try:
                with open(source_path, "r", encoding="utf-8") as handle:
                    loaded_profiles = json.load(handle)
            except Exception as error:
                messagebox.showwarning("Remote System List Warning", f"Failed to load remote system list:\n{error}", parent=self.root)
                continue
            if isinstance(loaded_profiles, list):
                raw_profiles.extend(loaded_profiles)

        if not raw_profiles:
            return []

        merged_profiles = {}
        for entry in raw_profiles:
            if not isinstance(entry, dict):
                continue
            host = str(entry.get("HOST", entry.get("host", ""))).strip()
            user = str(entry.get("USER", entry.get("user", ""))).strip()
            ip = str(entry.get("IP", entry.get("ip", ""))).strip()
            system_type = str(entry.get("Type", entry.get("type", ""))).strip()
            if not host and not ip:
                continue

            connection_host = ip or host
            username = user or ""
            label_parts = []
            if system_type:
                label_parts.append(system_type)
            label_parts.append(host or connection_host)
            if ip and ip != host:
                label_parts.append(ip)
            label = " | ".join(label_parts)

            port_value = entry.get("Port", entry.get("port", 22))
            try:
                port = int(str(port_value).strip()) if str(port_value).strip() else 22
            except ValueError:
                port = 22

            key = (system_type, host, ip, user)
            profile = merged_profiles.get(key, {
                "label": label,
                "host": connection_host,
                "host_name": host,
                "ip": ip,
                "user": username,
                "port": port,
                "password": "",
            })
            profile["label"] = label
            profile["host"] = connection_host
            profile["host_name"] = host
            profile["ip"] = ip
            profile["user"] = username
            profile["port"] = port
            password = str(entry.get("password", entry.get("Password", ""))).strip()
            if password:
                profile["password"] = password
            merged_profiles[key] = profile

        return list(merged_profiles.values())

    def _apply_remote_system_profile(self, profile, *, host_var, port_var, user_var, password_var):
        host_var.set(profile.get("host", ""))
        user_var.set(profile.get("user", ""))
        port_var.set(str(profile.get("port", 22) or 22))
        password_var.set(profile.get("password", ""))

    def _on_remote_system_selected(self, _event=None):
        selected = self.remote_system_var.get().strip()
        if not selected or selected == "Manual Input":
            return
        profile = self.remote_system_profile_map.get(selected)
        if profile:
            self._apply_remote_system_profile(
                profile,
                host_var=self.host_var,
                port_var=self.port_var,
                user_var=self.user_var,
                password_var=self.password_var,
            )

    def _open_combobox_dropdown(self, combo):
        with contextlib.suppress(tk.TclError):
            combo.tk.call("ttk::combobox::Post", combo)
        return "break"

    def _build_ui(self):
        padding = {"padx": 10, "pady": 5}
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook = notebook

        offline = OfflineBinaryDecodeFrame(notebook, self)
        notebook.add(offline, text="Offline BIOS Binary Decode")

        main = ttk.Frame(notebook, padding=12, style="Export.TFrame")
        notebook.add(main, text="Online BIOS Knobs Change")
        notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

        mode_frame = ttk.LabelFrame(main, text="Modify Target", style="Export.TLabelframe")
        mode_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Radiobutton(
            mode_frame,
            text="Local System Modify BIOS Knobs",
            variable=self.mode_var,
            value="local",
            command=self._update_mode_state,
        ).pack(side=tk.LEFT, padx=10, pady=6)
        ttk.Radiobutton(
            mode_frame,
            text="Remote System Modify BIOS Knobs",
            variable=self.mode_var,
            value="remote",
            command=self._update_mode_state,
        ).pack(side=tk.LEFT, padx=10, pady=6)

        remote_section = ttk.Frame(main, style="Export.TFrame")
        remote_section.pack(fill=tk.X, pady=(0, 8))
        self.remote_section = remote_section

        form = ttk.LabelFrame(remote_section, text="Manual Remote System Input", style="Export.TLabelframe")
        form.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        system_label = ttk.Label(form, text="Common System Selection", style="Export.TLabel")
        system_label.grid(row=0, column=0, sticky=tk.W, **padding)
        system_select = ttk.Frame(form, style="Selection.TFrame")
        system_select.grid(row=0, column=1, columnspan=3, sticky=tk.EW, **padding)
        system_values = ["Manual Input"] + [profile["label"] for profile in self.remote_system_profiles]
        system_combo = ttk.Combobox(system_select, textvariable=self.remote_system_var, values=system_values, state="readonly", width=62, style="Selection.TCombobox")
        system_combo.pack(fill=tk.X, expand=True)
        system_combo.bind("<<ComboboxSelected>>", self._on_remote_system_selected)

        host_label = ttk.Label(form, text="Host IP", style="Export.TLabel")
        host_label.grid(row=1, column=0, sticky=tk.W, **padding)
        host_entry = ttk.Entry(form, textvariable=self.host_var, width=32)
        host_entry.grid(row=1, column=1, sticky=tk.EW, **padding)
        port_label = ttk.Label(form, text="Port", style="Export.TLabel")
        port_label.grid(row=1, column=2, sticky=tk.W, **padding)
        port_entry = ttk.Entry(form, textvariable=self.port_var, width=8)
        port_entry.grid(row=1, column=3, sticky=tk.W, **padding)

        user_label = ttk.Label(form, text="User Name", style="Export.TLabel")
        user_label.grid(row=2, column=0, sticky=tk.W, **padding)
        user_entry = ttk.Entry(form, textvariable=self.user_var, width=32)
        user_entry.grid(row=2, column=1, sticky=tk.EW, **padding)
        password_label = ttk.Label(form, text="Password", style="Export.TLabel")
        password_label.grid(row=2, column=2, sticky=tk.W, **padding)
        password_entry = ttk.Entry(form, textvariable=self.password_var, show="*", width=24)
        password_entry.grid(row=2, column=3, sticky=tk.EW, **padding)
        self.remote_widgets = [
            system_label,
            system_combo,
            host_label,
            host_entry,
            port_label,
            port_entry,
            user_label,
            user_entry,
            password_label,
            password_entry,
        ]
        self.remote_widget_grid = {widget: widget.grid_info() for widget in self.remote_widgets}

        output_section = ttk.LabelFrame(main, text="BIOS XML File Output", style="Export.TLabelframe")
        output_section.pack(fill=tk.X, pady=(0, 8))
        self.local_output_section = output_section

        output_padding = {"padx": 10, "pady": 5}
        ttk.Label(output_section, text="BIOS XML File Output", style="Export.TLabel").grid(row=0, column=0, sticky=tk.W, **output_padding)
        ttk.Entry(output_section, textvariable=self.output_dir_var).grid(row=0, column=1, columnspan=2, sticky=tk.EW, **output_padding)
        ttk.Button(output_section, text="Browse", command=self._browse_output_dir, style="Export.TButton").grid(row=0, column=3, sticky=tk.E, **output_padding)

        output_section.columnconfigure(1, weight=1)
        output_section.columnconfigure(3, weight=1)

        actions = ttk.Frame(main, style="Export.TFrame")
        actions.pack(fill=tk.X, pady=(10, 8))

        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=0)

        export_action = ttk.Frame(actions, style="Export.TFrame")
        export_action.grid(row=0, column=0, sticky=tk.EW, pady=(0, 6))
        self.start_button = ttk.Button(export_action, text="Get Remote System BIOS Knob Configuration", command=self._start_export, style="ExportAccent.TButton", width=42)
        self.start_button.pack(side=tk.LEFT)
        self.start_description_var = tk.StringVar(value="Fetch BIOS knob configuration from the selected remote system.")
        ttk.Label(
            export_action,
            textvariable=self.start_description_var,
            style="ExportStatus.TLabel",
            wraplength=360,
        ).pack(side=tk.LEFT, padx=(10, 0))

        open_xml_action = ttk.Frame(actions, style="Export.TFrame")
        open_xml_action.grid(row=1, column=0, sticky=tk.EW, pady=6)
        ttk.Button(open_xml_action, text="Load BIOS Setup from Existing XML", command=self._open_existing_xml, style="Export.TButton", width=42).pack(side=tk.LEFT)
        ttk.Label(
            open_xml_action,
            text="Open the BIOS Setup viewer from an existing XML file.",
            style="ExportStatus.TLabel",
            wraplength=360,
        ).pack(side=tk.LEFT, padx=(10, 0))

        folder_action = ttk.Frame(actions, style="Export.TFrame")
        folder_action.grid(row=2, column=0, sticky=tk.EW, pady=(6, 0))
        ttk.Button(folder_action, text="Open Output Folder", command=self._open_output_dir, style="Export.TButton", width=42).pack(side=tk.LEFT)
        ttk.Label(
            folder_action,
            text="Open the folder where exported XML files are stored.",
            style="ExportStatus.TLabel",
            wraplength=360,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(actions, textvariable=self.status_var, style="ExportStatus.TLabel").grid(row=0, column=1, rowspan=3, sticky=tk.NE, padx=(12, 0))

        log_frame = ttk.LabelFrame(main, text="Log", style="Export.TLabelframe")
        log_frame.pack(fill=tk.X, expand=False)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=8)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.configure(
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief=tk.FLAT,
            borderwidth=1,
            padx=8,
            pady=6,
            font=("Consolas", 9),
        )

    def _update_mode_state(self):
        mode = self.mode_var.get()
        show_remote = mode == "remote"
        if self.remote_section is not None:
            if show_remote:
                if self.local_output_section is not None:
                    self.remote_section.pack(fill=tk.X, pady=(0, 8), before=self.local_output_section)
                else:
                    self.remote_section.pack(fill=tk.X, pady=(0, 8))
            else:
                self.remote_section.pack_forget()
        for widget in self.remote_widgets:
            with contextlib.suppress(tk.TclError):
                widget.state(["!disabled"] if show_remote else ["disabled"])
        show_offline = mode == "offline"
        for widget in self.offline_widgets:
            with contextlib.suppress(tk.TclError):
                if show_offline:
                    widget.grid(**self.offline_widget_grid[widget])
                else:
                    widget.grid_remove()
        if hasattr(self, "start_button"):
            button_text_by_mode = {
                "remote": "Get Remote System BIOS Knob Configuration",
                "local": "Get Local System BIOS Knob Configuration",
                "offline": "Get BIOS Knob Configuration from Binary",
            }
            description_by_mode = {
                "remote": "Fetch BIOS knob configuration from the selected remote system.",
                "local": "Fetch BIOS knob configuration from the local system.",
                "offline": "Fetch BIOS knob configuration from the selected BIOS binary.",
            }
            button_text = button_text_by_mode.get(mode, "Get BIOS Knob Configuration")
            self.start_button.configure(text=button_text)
            self.start_description_var.set(description_by_mode.get(mode, "Fetch BIOS knob configuration."))

    def _browse_bios_binary(self):
        selected = filedialog.askopenfilename(
            initialdir=os.path.dirname(self.bios_bin_var.get()) if self.bios_bin_var.get() else os.getcwd(),
            title="Select BIOS Binary",
            filetypes=(
                ("BIOS binary files", "*.bin *.rom *.fd *.cap"),
                ("All files", "*.*"),
            ),
        )
        if selected:
            self.bios_bin_var.set(selected)

    def _browse_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or os.getcwd())
        if selected:
            self.output_dir_var.set(selected)

    def _on_notebook_tab_changed(self, event):
        return None

    def _open_output_dir(self):
        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            return
        os.makedirs(output_dir, exist_ok=True)
        os.startfile(output_dir)

    def _open_existing_xml(self):
        xml_path = filedialog.askopenfilename(
            initialdir=self.output_dir_var.get() or os.getcwd(),
            title="Open BIOS Knob XML",
            filetypes=(("XML files", "*.xml"), ("All files", "*.*")),
        )
        if xml_path:
            self._open_setup_viewer(xml_path)

    def _open_setup_viewer(self, xml_path):
        if self.viewer_load_in_progress:
            return
        self.viewer_load_in_progress = True
        self.status_var.set("Loading XML")
        viewer = BiosSetupViewer(
            self.root,
            xml_path,
            target_settings_getter=self._viewer_target_settings,
            metadata={"xml_path": xml_path, "product": "BIOS Setup"},
            knobs=[],
            defer_load=True,
        )
        threading.Thread(target=self._load_setup_viewer_worker, args=(xml_path, viewer), daemon=True).start()

    def _load_setup_viewer_worker(self, xml_path, viewer):
        try:
            metadata, knobs = parse_bios_knob_xml(xml_path)
            self.root.after(0, lambda: self._finish_open_setup_viewer(viewer, metadata, knobs, None))
        except Exception as error:
            self.root.after(0, lambda load_error=error: self._finish_open_setup_viewer(viewer, None, None, load_error))

    def _finish_open_setup_viewer(self, viewer, metadata, knobs, error):
        self.viewer_load_in_progress = False
        self.status_var.set("Ready")
        try:
            if not viewer.window.winfo_exists():
                return
        except tk.TclError:
            return
        if error is not None:
            viewer.load_failed(str(error))
            return

        try:
            viewer.load_parsed_xml(metadata, knobs)
        except Exception as viewer_error:
            viewer.load_failed(str(viewer_error))

    def _viewer_target_settings(self):
        if self.mode_var.get() == "local":
            return {"mode": "local"}
        if self.mode_var.get() == "offline":
            return {
                "mode": "offline",
                "bios_bin": self.bios_bin_var.get().strip(),
                "output_dir": self.output_dir_var.get().strip(),
            }
        try:
            port = int(self.port_var.get().strip() or "22")
        except ValueError:
            port = None
        return {
            "mode": "remote",
            "host": self.host_var.get().strip(),
            "port": port,
            "user": self.user_var.get().strip(),
            "password": self.password_var.get(),
        }

    def _offline_target_settings(self):
        return {
            "mode": "offline",
            "bios_bin": self.bios_bin_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
        }

    def _append_log(self, text):
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def _set_running(self, running):
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)

    def _validate_inputs(self):
        mode = self.mode_var.get()
        host = self.host_var.get().strip()
        user_name = self.user_var.get().strip()
        password = self.password_var.get()
        remote_file = r"C:\BIOS_Knob.xml"
        bios_bin = self.bios_bin_var.get().strip()
        output_dir = self.output_dir_var.get().strip()

        if mode == "remote" and not host:
            messagebox.showerror("Missing Host IP", "Please input remote host IP.", parent=self.root)
            return None
        if mode == "remote" and not user_name:
            messagebox.showerror("Missing User Name", "Please input remote user name.", parent=self.root)
            return None
        if mode == "remote" and not password:
            messagebox.showerror("Missing Password", "Please input remote password.", parent=self.root)
            return None
        if mode == "offline" and not bios_bin:
            messagebox.showerror("Missing BIOS Binary", "Please select a BIOS binary file.", parent=self.root)
            return None
        if mode == "offline" and not os.path.isfile(bios_bin):
            messagebox.showerror("Invalid BIOS Binary", "Please select a valid BIOS binary file.", parent=self.root)
            return None
        if not output_dir:
            messagebox.showerror("Missing BIOS XML File Output", "Please input BIOS XML file output directory.", parent=self.root)
            return None

        port = None
        if mode == "remote":
            try:
                port = int(self.port_var.get().strip() or "22")
            except ValueError:
                messagebox.showerror("Invalid Port", "Port must be a number.", parent=self.root)
                return None

        return {
            "mode": mode,
            "host": host,
            "port": port,
            "user": user_name,
            "password": password,
            "remote_file": remote_file,
            "bios_bin": bios_bin,
            "output_dir": output_dir,
        }

    def _start_export(self):
        settings = self._validate_inputs()
        if settings is None:
            return

        if self.worker_thread and self.worker_thread.is_alive():
            return

        self.log_text.delete("1.0", tk.END)
        self.status_var.set("Running")
        self._set_running(True)
        self.worker_thread = threading.Thread(target=self._run_export_worker, args=(settings,), daemon=True)
        self.worker_thread.start()

    def _run_export_worker(self, settings):
        local_file = None
        exit_code = 1
        error_message = ""
        writer = QueueWriter(self.log_queue)

        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            client = None
            try:
                if settings.get("mode") == "local":
                    os.makedirs(settings["output_dir"], exist_ok=True)
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    local_file = os.path.join(settings["output_dir"], f"BIOS_Knob_{stamp}.xml")
                    exit_code = run_local_xmlcli_export(local_file)
                    if exit_code == 0:
                        with contextlib.suppress(Exception):
                            if _remove_file_if_exists(r"C:\BIOS_Knob.xml"):
                                print("[INFO] Removed temporary local XML: C:\\BIOS_Knob.xml")
                elif settings.get("mode") == "offline":
                    os.makedirs(settings["output_dir"], exist_ok=True)
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    local_file = os.path.join(settings["output_dir"], f"BIOS_Binary_Knob_{stamp}.xml")
                    exit_code = run_offline_xmlcli_export(local_file, settings["bios_bin"])
                else:
                    print(f"[INFO] Connecting to {settings['user']}@{settings['host']}:{settings['port']} ...")
                    client = connect(settings["host"], settings["port"], settings["user"], settings["password"])
                    print("[INFO] Terminating remote OpenIPC_x64.exe process before XmlCli export ...")
                    _stop_openipc_processes(settings, client=client)
                    exit_code = run_xmlcli_export(
                        client,
                        settings["remote_file"],
                        timeout_seconds=180,
                        log_callback=lambda text: self.log_queue.put(("log", text)),
                    )
                    if exit_code == 0:
                        _stop_openipc_processes(settings, client=client)
                        local_file = download_file(client, settings["remote_file"], settings["output_dir"])
            except Exception as error:
                error_message = _with_pysvtools_hint(str(error))
                print(f"[ERROR] {error_message}")
            finally:
                if client is not None:
                    client.close()
                    print("[INFO] SSH connection closed.")

            if exit_code == 0 and local_file:
                print(f"[INFO] Local XML: {os.path.abspath(local_file)}")

        self.log_queue.put(("done", exit_code, local_file, error_message, settings))

    def _pump_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item[0] == "log":
                    self._append_log(item[1])
                elif item[0] == "done":
                    self._handle_done(item[1], item[2], item[3] if len(item) > 3 else "", item[4] if len(item) > 4 else None)
        except queue.Empty:
            pass
        self.root.after(25, self._pump_log_queue)

    def _handle_done(self, exit_code, local_file, error_message="", settings=None):
        self._set_running(False)
        if exit_code == 0 and local_file:
            self.status_var.set("Completed")
            if messagebox.askyesno(
                "BIOS Knob Export",
                "BIOS knob configuration XML was generated successfully.\n\n"
                f"XML file:\n{os.path.abspath(local_file)}\n\n"
                "Open the BIOS Setup viewer now?",
                parent=self.root,
            ):
                self._open_setup_viewer(local_file)
        else:
            self.status_var.set("Failed")
            detail = _with_pysvtools_hint(error_message)
            message = "Export failed. Check the log area for details."
            if detail:
                message += "\n\n" + detail
            messagebox.showerror("BIOS Knob Export", message, parent=self.root)
            if _is_missing_pysvtools_error(detail):
                self.root.after(100, lambda install_settings=settings: prompt_install_pysvtools(self.root, install_settings))


def main():
    root = tk.Tk()
    app = BiosKnobExportApp(root)
    root.mainloop()

def _report_startup_error(exc):
    log_path = os.path.join(SCRIPT_DIR, "bios_firmware_decoder_startup_error.log")
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            log_file.write(details)
    except OSError:
        log_path = ""

    message = f"BIOS Firmware Decoder failed to start.\n\n{exc}"
    if log_path:
        message += f"\n\nDetails were written to:\n{log_path}"
    try:
        parent = tk.Tk()
        parent.withdraw()
        messagebox.showerror("BIOS Firmware Decoder", message, parent=parent)
        parent.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _report_startup_error(exc)
        raise