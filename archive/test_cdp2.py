"""Test CDP - no pipe."""
import subprocess
import time
import urllib.request
import json
import tempfile

tmpdir = tempfile.mkdtemp(prefix="chrome_cdp2_")
print(f"Temp dir: {tmpdir}")

proc = subprocess.Popen(
    [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        f"--user-data-dir={tmpdir}",
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ],
)
print(f"Chrome PID: {proc.pid}")

for i in range(10):
    time.sleep(2)
    poll = proc.poll()
    if poll is not None:
        print(f"Chrome exited with code: {poll}")
        break
    try:
        r = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        d = json.loads(r.read())
        print(f"CDP OK: {d.get('Browser', '?')}")
        break
    except Exception:
        print(f"Attempt {i+1}: waiting...")
else:
    print("CDP FAILED - Chrome still running but port closed")
    proc.terminate()
