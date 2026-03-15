"""Run Supabase->local sync on the VPS via SSH."""
import paramiko

HOST = "89.169.52.174"
KEY_FILE = r"C:\Users\sherh\.ssh\id_rsa"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", key_filename=KEY_FILE, timeout=15)

# Run sync script inside the bot container
cmd = 'cd /root/music-bot && docker compose exec -T bot python /app/deploy/sync_supabase_to_local.py'
print(f"Running: {cmd}\n")

stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
out = stdout.read().decode()
err = stderr.read().decode()

print("=== STDOUT ===")
print(out)
if err:
    print("=== STDERR ===")
    print(err)

client.close()
