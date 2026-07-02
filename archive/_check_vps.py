import paramiko

HOST = "89.169.52.174"
KEY_FILE = r"C:\Users\sherh\.ssh\id_rsa"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", key_filename=KEY_FILE, timeout=15)

cmd = "cd /root/music-bot && docker compose build bot 2>&1 | tail -5 && docker compose up -d bot && sleep 5 && docker compose ps && echo '---LOGS---' && docker compose logs bot --tail=5 2>&1"
stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
print(stdout.read().decode())
print(stderr.read().decode())
client.close()
