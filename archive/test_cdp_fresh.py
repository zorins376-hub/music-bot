"""Test CDP with a fresh temp user data dir."""
import subprocess
import time
import urllib.request
import json
import tempfile
import os

tmpdir = tempfile.mkdtemp(prefix="chrome_cdp_")
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
    stderr=subprocess.PIPE,
    stdout=subprocess.PIPE,
)
print(f"Chrome PID: {proc.pid}")

for i in range(10):
    time.sleep(2)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        d = json.loads(r.read())
        print(f"CDP OK: {d.get('Browser', '?')}")
        break
    except Exception:
        print(f"Attempt {i+1}: waiting...")
else:
    print("CDP FAILED")
    if proc.poll() is not None:
        print(f"Chrome exited with code: {proc.returncode}")
        print(proc.stderr.read().decode("utf-8", errors="replace")[:2000])

proc.terminate()
