"""Quick SSH command runner."""
import paramiko
import sys
import time

HOST = "89.169.52.174"
USER = "root"
PASS = "YjfWW9v6j2m5"


def ssh_exec(cmd: str, timeout: int = 30) -> str:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30)
    
    chan = client.get_transport().open_session()
    chan.settimeout(None)
    chan.exec_command(cmd)
    
    out_parts = []
    while True:
        if chan.recv_ready():
            out_parts.append(chan.recv(4096).decode(errors='replace'))
        elif chan.exit_status_ready():
            while chan.recv_ready():
                out_parts.append(chan.recv(4096).decode(errors='replace'))
            break
        else:
            time.sleep(0.3)
    
    result = ''.join(out_parts).strip()
    client.close()
    return result


if __name__ == "__main__":
    cmd = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else "echo 'Usage: python ssh_cmd.py <command>'"
    print(ssh_exec(cmd))
