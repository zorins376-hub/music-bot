"""Debug Chrome CDP launch - capture stderr."""
import subprocess
import time
import urllib.request
import json

proc = subprocess.Popen(
    [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--enable-logging=stderr",
        "--v=1",
        "about:blank"
    ],
    stderr=subprocess.PIPE,
    stdout=subprocess.PIPE,
)
print(f"Chrome PID: {proc.pid}")

# Read stderr for a few seconds
time.sleep(5)

# Check if process is still running
if proc.poll() is not None:
    print(f"Chrome exited with code: {proc.returncode}")
    out = proc.stderr.read().decode("utf-8", errors="replace")
    print(f"STDERR:\n{out[:3000]}")
else:
    print("Chrome is running")
    # Check port
    try:
        r = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        d = json.loads(r.read())
        print(f"CDP OK: {d.get('Browser', '?')}")
    except Exception as e:
        print(f"CDP failed: {e}")

    # Check DevToolsActivePort
    import os
    user_data = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    port_file = os.path.join(user_data, "DevToolsActivePort")
    if os.path.exists(port_file):
        with open(port_file) as f:
            content = f.read()
        print(f"DevToolsActivePort content:\n{content}")
    else:
        print("DevToolsActivePort file NOT found")

    # Check what ports Chrome is listening on
    import socket
    for port in [9222, 9229, 9515]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        print(f"Port {port}: {'OPEN' if result == 0 else 'CLOSED'}")

    proc.terminate()
