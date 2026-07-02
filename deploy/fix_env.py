"""Patch remote .env on VPS via SSH."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_common import connect_ssh

PROJECT_DIR = __import__("os").environ.get("DEPLOY_PROJECT_DIR", "/opt/music-bot").strip()


def main():
    ssh = connect_ssh(timeout=30)

    updates = f"""
sed -i '/CHART_YANDEX_ENABLED/d' {PROJECT_DIR}/.env
sed -i '/DB_POOL_SIZE/d' {PROJECT_DIR}/.env
sed -i '/DB_MAX_OVERFLOW/d' {PROJECT_DIR}/.env

echo 'CHART_YANDEX_ENABLED=false' >> {PROJECT_DIR}/.env
echo 'DB_POOL_SIZE=5' >> {PROJECT_DIR}/.env
echo 'DB_MAX_OVERFLOW=10' >> {PROJECT_DIR}/.env
"""
    _, stdout, stderr = ssh.exec_command(updates, timeout=30)
    print(stdout.read().decode())
    print(stderr.read().decode())

    _, stdout, stderr = ssh.exec_command(
        f'grep -E "CHART_YANDEX|DB_POOL" {PROJECT_DIR}/.env', timeout=30
    )
    print("Updated .env:")
    print(stdout.read().decode())

    ssh.close()
    print("Done!")


if __name__ == "__main__":
    main()
