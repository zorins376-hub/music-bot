"""One-shot deploy script: setup SSH key + deploy to VPS."""
import paramiko
import pathlib
import sys
import time

HOST = "89.169.52.174"
USER = "root"
PASS = "YjfWW9v6j2m5"

def ssh_exec(client, cmd, timeout=120):
    """Execute command and print output in real-time."""
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip():
        print(out.strip())
    if err.strip():
        for line in err.strip().split("\n"):
            if not line.startswith("WARNING") and "debconf" not in line:
                print(f"  [stderr] {line}")
    return out.strip(), stdout.channel.recv_exit_status()

def main():
    # 1. Setup SSH key
    key_path = pathlib.Path.home() / ".ssh" / "id_rsa"
    pub_path = key_path.with_suffix(".pub")
    
    if not key_path.exists():
        print("Generating SSH key...")
        key = paramiko.RSAKey.generate(4096)
        key_path.parent.mkdir(exist_ok=True)
        key.write_private_key_file(str(key_path))
        with open(pub_path, "w") as f:
            f.write(f"ssh-rsa {key.get_base64()} deploy@musicbot\n")
        print("SSH key generated")
    
    pub_key = pub_path.read_text().strip()
    
    # 2. Connect
    print(f"\nConnecting to {HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=15)
    print("Connected!")
    
    # 3. Install SSH key
    ssh_exec(client, f'mkdir -p ~/.ssh && grep -qF "{pub_key}" ~/.ssh/authorized_keys 2>/dev/null || echo "{pub_key}" >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys && echo "SSH key installed"')
    
    # 4. Check what's on the server
    out, _ = ssh_exec(client, "ls /root/music-bot/.git/HEAD 2>/dev/null && echo REPO_EXISTS || echo NO_REPO")
    has_repo = "REPO_EXISTS" in out
    
    # 5. Check Docker
    out, code = ssh_exec(client, "docker --version 2>/dev/null && docker compose version 2>/dev/null || echo NO_DOCKER")
    if "NO_DOCKER" in out or code != 0:
        print("\nInstalling Docker...")
        ssh_exec(client, "curl -fsSL https://get.docker.com | sh", timeout=300)
        ssh_exec(client, "systemctl enable docker && systemctl start docker")
    
    # 6. Clone or pull
    if has_repo:
        print("\nRepo exists, pulling latest...")
        ssh_exec(client, "cd /root/music-bot && git stash 2>/dev/null; git pull origin main")
    else:
        print("\nCloning repo...")
        ssh_exec(client, "cd /root && git clone https://github.com/zorins376-hub/music-bot.git")
    
    # 7. Show latest commit
    ssh_exec(client, "cd /root/music-bot && git log --oneline -1")
    
    # 8. Check .env
    out, _ = ssh_exec(client, "test -f /root/music-bot/.env && echo ENV_EXISTS || echo NO_ENV")
    if "NO_ENV" in out:
        print("\n⚠️  No .env file found! Copying from deploy template...")
        ssh_exec(client, "cp /root/music-bot/deploy/.env.vps.local /root/music-bot/.env 2>/dev/null || cp /root/music-bot/.env.example /root/music-bot/.env")
        print("⚠️  You need to edit /root/music-bot/.env with your tokens!")
    
    # 9. Build and start
    print("\nBuilding and starting containers...")
    out, code = ssh_exec(client, "cd /root/music-bot && docker compose up -d --build 2>&1", timeout=600)
    
    # 10. Check status
    time.sleep(5)
    ssh_exec(client, "cd /root/music-bot && docker compose ps")
    
    # 11. Show recent logs
    ssh_exec(client, "cd /root/music-bot && docker compose logs --tail=20 2>&1 | tail -20")
    
    client.close()
    print("\n✅ Deploy complete!")

if __name__ == "__main__":
    main()
