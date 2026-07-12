import os
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    os.environ["VPS_HOST"],
    username=os.environ.get("VPS_USER", "root"),
    password=os.environ["VPS_PASS"],
    timeout=30,
)

# Check DB connections
cmd = 'cd /opt/music-bot && docker compose exec -T postgres psql -U postgres -d musicbot -c "SELECT count(*) FROM pg_stat_activity;"'
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
print('DB Connections:')
print(stdout.read().decode())

# Check max_connections
cmd2 = 'cd /opt/music-bot && docker compose exec -T postgres psql -U postgres -c "SHOW max_connections;"'
stdin, stdout, stderr = ssh.exec_command(cmd2, timeout=30)
print('Max connections:')
print(stdout.read().decode())

# Check if YANDEX_TOKEN exists
cmd3 = 'grep YANDEX_TOKEN /opt/music-bot/.env || echo "NOT SET"'
stdin, stdout, stderr = ssh.exec_command(cmd3, timeout=30)
print('YANDEX_TOKEN:')
print(stdout.read().decode())

ssh.close()
