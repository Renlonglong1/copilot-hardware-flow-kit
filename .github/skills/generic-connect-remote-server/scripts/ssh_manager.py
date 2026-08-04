"""
ssh_manager.py
CLI entry-point for the os-connect-remote-server skill.

Usage examples:
  python ssh_manager.py connect   --ip 192.168.1.10 --user root --password secret --cmd "uname -a"
  python ssh_manager.py upload    --ip 192.168.1.10 --user root --password secret --local ./file.tar --remote /tmp/file.tar
  python ssh_manager.py run-test  --ip 192.168.1.10 --user root --password secret --script /opt/tests/run_all.sh
  python ssh_manager.py save-creds --ip 192.168.1.10 --user root --password secret
  python ssh_manager.py list-ips
  python ssh_manager.py forget    --ip 192.168.1.10

Credentials are loaded automatically from the vault if --password is omitted.
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

try:
    import paramiko
except ImportError:
    raise SystemExit("Missing dependency. Run:  pip install paramiko cryptography")

# Allow importing credential_store from the same scripts/ directory
sys.path.insert(0, str(Path(__file__).parent))
import credential_store as cs

DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------

def _make_client(ip: str, port: int, username: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507 — trust-on-first-use
    client.connect(
        hostname=ip,
        port=port,
        username=username,
        password=password,
        timeout=DEFAULT_TIMEOUT,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def _resolve_creds(args) -> tuple[str, str]:
    """Return (username, password), loading from vault if flags are absent."""
    username = args.user
    password = getattr(args, "password", None)

    if not username or not password:
        saved = cs.load_credentials(args.ip)
        if saved:
            username = username or saved["username"]
            password = password or saved["password"]

    if not username:
        username = input("Username: ")
    if not password:
        import getpass
        password = getpass.getpass("Password: ")

    return username, password


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_connect(args) -> int:
    username, password = _resolve_creds(args)
    try:
        client = _make_client(args.ip, args.port, username, password)
    except paramiko.AuthenticationException:
        print("[ERROR] Authentication failed. Check username/password.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] Cannot connect to {args.ip}:{args.port} — {exc}", file=sys.stderr)
        return 1

    cs.record_ip(args.ip)
    command = args.cmd or "echo Connected"

    stdin, stdout, stderr = client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    client.close()

    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
    return exit_code


def cmd_upload(args) -> int:
    if not args.local or not args.remote:
        print("[ERROR] --local and --remote are required for upload.", file=sys.stderr)
        return 1

    local_path = Path(args.local)
    if not local_path.exists():
        print(f"[ERROR] Local file not found: {local_path}", file=sys.stderr)
        return 1

    username, password = _resolve_creds(args)
    try:
        client = _make_client(args.ip, args.port, username, password)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    cs.record_ip(args.ip)

    sftp = client.open_sftp()
    try:
        sftp.put(str(local_path), args.remote)
        print(f"[OK] Uploaded {local_path} → {args.ip}:{args.remote}")
    finally:
        sftp.close()
        client.close()

    return 0


def cmd_run_test(args) -> int:
    if not args.script:
        print("[ERROR] --script is required for run-test.", file=sys.stderr)
        return 1

    args.cmd = f"bash {args.script}"
    return cmd_connect(args)


def cmd_save_creds(args) -> int:
    username = args.user
    password = getattr(args, "password", None)
    if not username:
        username = input("Username: ")
    if not password:
        import getpass
        password = getpass.getpass("Password: ")
    cs.save_credentials(args.ip, username, password)
    return 0


def cmd_list_ips(_args) -> int:
    history = cs.get_ip_history()
    saved = cs.list_saved_ips()

    print("=== IP History (most recent first) ===")
    if history:
        for i, ip in enumerate(history, 1):
            tag = " [saved]" if ip in saved else ""
            print(f"  {i:2}. {ip}{tag}")
    else:
        print("  (no history yet)")

    if saved:
        extra = [ip for ip in saved if ip not in history]
        if extra:
            print("\n=== Saved credentials (not in history) ===")
            for ip in extra:
                print(f"  {ip}")
    return 0


def cmd_forget(args) -> int:
    removed = cs.forget_credentials(args.ip)
    if not removed:
        print(f"[INFO] No saved credentials found for {args.ip}.")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Linux Remote Manager — SSH/SFTP helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_host_args(p):
        p.add_argument("--ip", required=True, help="Remote IP or hostname")
        p.add_argument("--port", type=int, default=DEFAULT_PORT)
        p.add_argument("--user", default=None, help="SSH username")
        p.add_argument("--password", default=None, help="SSH password")

    # connect
    p_conn = sub.add_parser("connect", help="Run a command over SSH")
    add_host_args(p_conn)
    p_conn.add_argument("--cmd", default=None, help="Shell command to run (default: echo Connected)")

    # upload
    p_up = sub.add_parser("upload", help="Upload a file via SFTP")
    add_host_args(p_up)
    p_up.add_argument("--local", required=True, help="Local file path")
    p_up.add_argument("--remote", required=True, help="Remote destination path")

    # run-test
    p_test = sub.add_parser("run-test", help="Run a shell script on the remote host")
    add_host_args(p_test)
    p_test.add_argument("--script", required=True, help="Absolute path to script on remote host")

    # save-creds
    p_save = sub.add_parser("save-creds", help="Encrypt and save credentials for an IP")
    add_host_args(p_save)

    # list-ips
    sub.add_parser("list-ips", help="Show IP history and saved credentials")

    # forget
    p_forget = sub.add_parser("forget", help="Remove saved credentials for an IP")
    p_forget.add_argument("--ip", required=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "connect": cmd_connect,
        "upload": cmd_upload,
        "run-test": cmd_run_test,
        "save-creds": cmd_save_creds,
        "list-ips": cmd_list_ips,
        "forget": cmd_forget,
    }

    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
