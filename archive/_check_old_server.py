import paramiko, sys

OLD_HOST = "31.129.33.216"

# Try both passwords
for pwd in ["YjfWW9v6j2m5", "changeme"]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(OLD_HOST, username="root", password=pwd, timeout=10)
        print(f"Connected with password: {'***' + pwd[-3:]}")
        stdin, stdout, stderr = client.exec_command("docker ps --format '{{.Names}}'")
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        print(f"Containers: {out or 'none'}")
        if err:
            print(f"Err: {err}")
        
        # Try pg_dump
        stdin, stdout, stderr = client.exec_command(
            "docker exec $(docker ps -qf 'name=postgres') pg_dump -U musicbot musicbot 2>/dev/null | head -20"
        )
        dump = stdout.read().decode().strip()
        if dump:
            print(f"DB dump available! First lines:\n{dump}")
        else:
            print("No pg_dump output")
            print(stderr.read().decode()[:200])
        
        client.close()
        sys.exit(0)
    except Exception as e:
        print(f"Password {'***'+pwd[-3:]} failed: {e}")
        try:
            client.close()
        except:
            pass

print("Could not connect to old server")
sys.exit(1)
