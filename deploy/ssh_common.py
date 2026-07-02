"""Shared SSH connection helpers for deploy scripts."""
import os
import sys
from pathlib import Path

import paramiko


def _load_deploy_env() -> None:
    """Load deploy/.env if present (gitignored local secrets)."""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def get_ssh_config() -> tuple[str, str, str, str]:
    _load_deploy_env()
    host = os.environ.get("DEPLOY_SSH_HOST", "").strip()
    user = os.environ.get("DEPLOY_SSH_USER", "root").strip() or "root"
    key_path = os.environ.get("DEPLOY_SSH_KEY_PATH", "").strip()
    password = os.environ.get("DEPLOY_SSH_PASSWORD", "").strip()
    if not host:
        sys.exit("DEPLOY_SSH_HOST is required (set in env or deploy/.env)")
    if not key_path and not password:
        sys.exit("DEPLOY_SSH_KEY_PATH or DEPLOY_SSH_PASSWORD is required")
    return host, user, key_path, password


def connect_ssh(timeout: int = 30) -> paramiko.SSHClient:
    host, user, key_path, password = get_ssh_config()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs: dict = {"hostname": host, "username": user, "timeout": timeout}
    if key_path:
        connect_kwargs["key_filename"] = key_path
    else:
        connect_kwargs["password"] = password
    client.connect(**connect_kwargs)
    return client
