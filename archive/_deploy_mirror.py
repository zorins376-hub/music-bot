import paramiko

HOST = "89.169.52.174"
KEY_FILE = r"C:\Users\sherh\.ssh\id_rsa"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", key_filename=KEY_FILE, timeout=15)

cmds = [
    "cd /root/music-bot && git pull origin main",
    "cd /root/music-bot && docker compose build --no-cache bot",
    "cd /root/music-bot && docker compose up -d bot",
    "sleep 3 && docker ps --format 'table {{.Names}}\t{{.Status}}'",
]

for cmd in cmds:
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err:
        print(err)

client.close()
print("\nDone!")
