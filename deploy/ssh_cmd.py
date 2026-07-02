"""Quick SSH command runner."""
import sys
import time

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_common import connect_ssh


def ssh_exec(cmd: str) -> str:
    client = connect_ssh(timeout=30)

    chan = client.get_transport().open_session()
    chan.settimeout(None)
    chan.exec_command(cmd)

    out_parts = []
    while True:
        if chan.recv_ready():
            out_parts.append(chan.recv(4096).decode(errors="replace"))
        elif chan.exit_status_ready():
            while chan.recv_ready():
                out_parts.append(chan.recv(4096).decode(errors="replace"))
            break
        else:
            time.sleep(0.3)

    result = "".join(out_parts).strip()
    client.close()
    return result


if __name__ == "__main__":
    cmd = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "echo 'Usage: python deploy/ssh_cmd.py <command>'"
    print(ssh_exec(cmd))
