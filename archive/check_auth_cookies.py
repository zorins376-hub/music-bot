"""Check all cookies from CDP - look for auth cookies."""
import json
import http.client
import time
import websocket


def get_page_ws(port=9222):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/json")
    targets = json.loads(conn.getresponse().read())
    conn.close()
    for t in targets:
        ws_url = t.get("webSocketDebuggerUrl")
        if ws_url:
            return ws_url
    raise RuntimeError("No debuggable pages found")


def cdp_call(ws, method, params=None, msg_id=None):
    if msg_id is None:
        msg_id = hash(method) & 0xFFFF
    msg = {"id": msg_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp.get("result", {})


ws_url = get_page_ws()
ws = websocket.create_connection(ws_url)

# Navigate to accounts.google.com
print("Navigating to accounts.google.com...")
cdp_call(ws, "Page.navigate", {"url": "https://accounts.google.com"}, 1)
time.sleep(5)

# Reconnect
ws.close()
time.sleep(1)
ws_url = get_page_ws()
ws = websocket.create_connection(ws_url)

# Get all cookies
result = cdp_call(ws, "Network.getAllCookies", msg_id=10)
all_cookies = result.get("cookies", [])
print(f"Total cookies: {len(all_cookies)}")

# Group by domain
domains = {}
for c in all_cookies:
    d = c.get("domain", "?")
    if d not in domains:
        domains[d] = []
    domains[d].append(c["name"])

for d in sorted(domains):
    print(f"  {d}: {', '.join(sorted(domains[d]))}")

# Check for auth cookies specifically
AUTH_NAMES = ["SID", "SSID", "HSID", "APISID", "SAPISID",
              "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO",
              "__Secure-1PAPISID", "__Secure-3PAPISID"]

auth_found = [c["name"] for c in all_cookies if c["name"] in AUTH_NAMES]
print(f"\nAuth cookies found: {auth_found}")
if not auth_found:
    print("NO AUTH COOKIES - user is NOT logged in to Google in this Chrome profile!")

ws.close()
