"""
credential_store.py
Manages encrypted credential vault and IP history for os-connect-remote-server.

Storage layout (relative to this script's parent directory):
  ../credentials/vault.json   — AES-256-GCM encrypted credentials keyed by IP
  ../credentials/ip_history.json — ordered list of recently used IPs
  ../credentials/.salt        — random 16-byte salt (hex), generated once
"""

from __future__ import annotations

import json
import os
import socket
import secrets
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    import base64
except ImportError:
    raise SystemExit(
        "Missing dependency. Run:  pip install cryptography"
    )

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SKILLS_DIR = Path(__file__).resolve().parent.parent
_CREDS_DIR = _SKILLS_DIR / "credentials"
_VAULT_FILE = _CREDS_DIR / "vault.json"
_HISTORY_FILE = _CREDS_DIR / "ip_history.json"
_SALT_FILE = _CREDS_DIR / ".salt"

MAX_HISTORY = 20  # keep last N IPs


def _ensure_creds_dir() -> None:
    _CREDS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _load_or_create_salt() -> bytes:
    _ensure_creds_dir()
    if _SALT_FILE.exists():
        return bytes.fromhex(_SALT_FILE.read_text().strip())
    salt = secrets.token_bytes(16)
    _SALT_FILE.write_text(salt.hex())
    return salt


def _derive_key(salt: bytes) -> bytes:
    """Derive a 32-byte AES key from hostname + salt via PBKDF2-SHA256."""
    password = socket.gethostname().encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390_000,
    )
    return kdf.derive(password)


def _get_key() -> bytes:
    return _derive_key(_load_or_create_salt())


# ---------------------------------------------------------------------------
# Encrypt / Decrypt helpers
# ---------------------------------------------------------------------------

def _encrypt(plaintext: str, key: bytes) -> str:
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt(token: str, key: bytes) -> str:
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()


# ---------------------------------------------------------------------------
# Vault operations
# ---------------------------------------------------------------------------

def _load_vault() -> dict:
    if not _VAULT_FILE.exists():
        return {}
    return json.loads(_VAULT_FILE.read_text())


def _save_vault(vault: dict) -> None:
    _ensure_creds_dir()
    _VAULT_FILE.write_text(json.dumps(vault, indent=2))


def save_credentials(ip: str, username: str, password: str) -> None:
    """Encrypt and persist credentials for the given IP."""
    key = _get_key()
    vault = _load_vault()
    vault[ip] = {
        "username": username,
        "password": _encrypt(password, key),
    }
    _save_vault(vault)
    print(f"[credential_store] Credentials saved for {ip}.")


def load_credentials(ip: str) -> Optional[dict]:
    """Return {'username': ..., 'password': ...} or None if not found."""
    vault = _load_vault()
    if ip not in vault:
        return None
    key = _get_key()
    entry = vault[ip]
    try:
        return {
            "username": entry["username"],
            "password": _decrypt(entry["password"], key),
        }
    except Exception:
        return None


def forget_credentials(ip: str) -> bool:
    """Remove saved credentials for an IP. Returns True if removed."""
    vault = _load_vault()
    if ip in vault:
        del vault[ip]
        _save_vault(vault)
        print(f"[credential_store] Credentials removed for {ip}.")
        return True
    return False


def list_saved_ips() -> list[str]:
    return list(_load_vault().keys())


# ---------------------------------------------------------------------------
# IP history
# ---------------------------------------------------------------------------

def _load_history() -> list[str]:
    if not _HISTORY_FILE.exists():
        return []
    return json.loads(_HISTORY_FILE.read_text())


def _save_history(history: list[str]) -> None:
    _ensure_creds_dir()
    _HISTORY_FILE.write_text(json.dumps(history, indent=2))


def record_ip(ip: str) -> None:
    """Add IP to history (most-recent first, no duplicates)."""
    history = _load_history()
    if ip in history:
        history.remove(ip)
    history.insert(0, ip)
    _save_history(history[:MAX_HISTORY])


def get_ip_history() -> list[str]:
    return _load_history()
