"""Test that age-restricted video works with cookies."""
import subprocess
import json

result = subprocess.run(
    ["python", "-m", "yt_dlp", "--cookies", "cookies.txt",
     "--skip-download", "-j",
     "https://www.youtube.com/watch?v=rmxswDZg-IA"],
    capture_output=True, text=True, timeout=60
)

stderr = result.stderr or ""
stdout = result.stdout or ""
print(f"Return code: {result.returncode}")
print(f"STDERR (first 500): {stderr[:500]}")

if stdout.strip():
    try:
        d = json.loads(stdout)
        print(f"Title: {d.get('title', '?')}")
        print(f"Age limit: {d.get('age_limit', '?')}")
        print(f"Duration: {d.get('duration', '?')}s")
        print("SUCCESS - age-restricted video accessible!")
    except json.JSONDecodeError:
        print(f"STDOUT (not JSON): {stdout[:500]}")
else:
    print("No stdout output")
