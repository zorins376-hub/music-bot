import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('89.169.52.174', username='root', password='YjfWW9v6j2m5', timeout=30)

# Add/update settings in .env
updates = """
# Fix for geo-blocked Yandex and DB pool
sed -i '/CHART_YANDEX_ENABLED/d' /opt/music-bot/.env
sed -i '/DB_POOL_SIZE/d' /opt/music-bot/.env
sed -i '/DB_MAX_OVERFLOW/d' /opt/music-bot/.env

echo 'CHART_YANDEX_ENABLED=false' >> /opt/music-bot/.env
echo 'DB_POOL_SIZE=5' >> /opt/music-bot/.env
echo 'DB_MAX_OVERFLOW=10' >> /opt/music-bot/.env
"""
stdin, stdout, stderr = ssh.exec_command(updates, timeout=30)
print(stdout.read().decode())
print(stderr.read().decode())

# Verify
stdin, stdout, stderr = ssh.exec_command('grep -E "CHART_YANDEX|DB_POOL" /opt/music-bot/.env', timeout=30)
print('Updated .env:')
print(stdout.read().decode())

ssh.close()
print('Done!')
