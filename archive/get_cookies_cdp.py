"""Extract YouTube cookies from Chrome via Chrome DevTools Protocol.

Launches a temporary Chrome window using the user's existing profile
to access cookies through CDP, which bypasses the v20 encryption issue.
"""
import json
import subprocess
import time
import http.client
import os
import sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9222
PROFILE = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
TEMP_PROFILE = os.path.join(os.environ["TEMP"], "chrome_debug_profile")

# Check if Chrome is running with debugging already
def get_cookies_via_cdp(port):
    """Connect to Chrome DevTools Protocol and extract cookies."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    
    # Get list of targets
    conn.request("GET", "/json")
    resp = conn.getresponse()
    targets = json.loads(resp.read())
    
    if not targets:
        print("No Chrome tabs found")
        return None
    
    # Use WebSocket to get cookies through the first target
    # Actually, we can use the /json/protocol endpoint and HTTP-based CDP
    # For cookies, we need to use the browser-level endpoint
    
    conn.request("GET", "/json/version")
    resp = conn.getresponse()
    version_info = json.loads(resp.read())
    ws_url = version_info.get("webSocketDebuggerUrl", "")
    print(f"Chrome version: {version_info.get('Browser', 'unknown')}")
    
    # Use websocket to send CDP command
    import websocket
    ws = websocket.create_connection(ws_url)
    
    # Get all cookies
    ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
    result = json.loads(ws.recv())
    ws.close()
    conn.close()
    
    all_cookies = result.get("result", {}).get("cookies", [])
    # Filter YouTube and Google cookies
    yt_cookies = [c for c in all_cookies 
                  if ".youtube.com" in c.get("domain", "") 
                  or ".google.com" in c.get("domain", "")]
    
    return yt_cookies


def write_netscape_cookies(cookies, output_path):
    """Write cookies in Netscape format."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n\n")
        for c in cookies:
            domain = c["domain"]
            is_domain = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            expires = int(c.get("expires", 0))
            name = c["name"]
            value = c["value"]
            if not value:
                continue
            f.write(f"{domain}\t{is_domain}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
    return len([c for c in cookies if c.get("value")])


if __name__ == "__main__":
    # Try connecting to existing debugging port first
    try:
        cookies = get_cookies_via_cdp(PORT)
        if cookies:
            count = write_netscape_cookies(cookies, "cookies.txt")
            print(f"Exported {count} YouTube/Google cookies to cookies.txt")
            sys.exit(0)
    except Exception:
        pass
    
    print(f"Launching Chrome with remote debugging on port {PORT}...")
    print("A Chrome window will open briefly - DO NOT close it manually.")
    
    proc = subprocess.Popen([
        CHROME,
        f"--remote-debugging-port={PORT}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={PROFILE}",
        "--restore-last-session",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Retry connecting to CDP with backoff
    cookies = None
    for attempt in range(15):
        time.sleep(2)
        try:
            cookies = get_cookies_via_cdp(PORT)
            if cookies:
                break
        except Exception as e:
            print(f"  Attempt {attempt+1}/15: waiting for Chrome... ({e})")
    
    try:
        if cookies:
            count = write_netscape_cookies(cookies, "cookies.txt")
            print(f"Exported {count} YouTube/Google cookies to cookies.txt")
        else:
            print("No cookies found after all attempts!")
    finally:
        proc.terminate()
