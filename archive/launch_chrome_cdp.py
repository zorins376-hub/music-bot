"""Launch Chrome with CDP and check connection."""
import subprocess
import time
import urllib.request
import json

proc = subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    "--no-first-run",
    "https://www.youtube.com"
])
print(f"Chrome PID: {proc.pid}")

for i in range(15):
    time.sleep(2)
    try:
        r = urllib.request.urlopen("http://localhost:9222/json/version")
        d = json.loads(r.read())
        browser = d.get("Browser", "?")
        print(f"CDP OK: {browser}")
        break
    except Exception as e:
        print(f"Attempt {i+1}: not ready yet")
else:
    print("CDP FAILED after all attempts")
