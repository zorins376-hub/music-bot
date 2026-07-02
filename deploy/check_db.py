"""Check remote Postgres health via SSH."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_common import connect_ssh

PROJECT_DIR = __import__("os").environ.get("DEPLOY_PROJECT_DIR", "/opt/music-bot").strip()


def main():
    ssh = connect_ssh(timeout=30)

    cmd = (
        f"cd {PROJECT_DIR} && docker compose exec -T postgres psql -U postgres -d musicbot "
        '-c "SELECT count(*) FROM pg_stat_activity;"'
    )
    _, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    print("DB Connections:")
    print(stdout.read().decode())

    cmd2 = (
        f"cd {PROJECT_DIR} && docker compose exec -T postgres psql -U postgres "
        '-c "SHOW max_connections;"'
    )
    _, stdout, stderr = ssh.exec_command(cmd2, timeout=30)
    print("Max connections:")
    print(stdout.read().decode())

    cmd3 = f"grep YANDEX_TOKEN {PROJECT_DIR}/.env || echo \"NOT SET\""
    _, stdout, stderr = ssh.exec_command(cmd3, timeout=30)
    print("YANDEX_TOKEN:")
    print(stdout.read().decode())

    ssh.close()


if __name__ == "__main__":
    main()
