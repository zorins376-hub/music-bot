"""Extract YouTube cookies from Chrome via Chrome DevTools Protocol.

Connects to Chrome running with --remote-debugging-port=9222,
navigates to YouTube + Google to load cookies, then exports them
in Netscape cookies.txt format.
"""
import json
import http.client
import time
import websocket


def get_page_ws(port=9222):
    """Get WebSocket URL for the first browser page."""
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
    """Send CDP command and return result."""
    if msg_id is None:
        msg_id = hash(method) & 0xFFFF
    msg = {"id": msg_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    # Read until we get our response (skip events)
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp.get("result", {})


def main():
    ws_url = get_page_ws()
    ws = websocket.create_connection(ws_url)

    # Navigate to YouTube to load cookies
    print("Navigating to YouTube...")
    cdp_call(ws, "Page.navigate", {"url": "https://www.youtube.com"}, 1)
    time.sleep(5)

    # After navigation, need to reconnect as page context changes
    ws.close()
    time.sleep(1)

    ws_url = get_page_ws()
    ws = websocket.create_connection(ws_url)

    # Get ALL cookies (not just for current domain)
    print("Extracting cookies...")
    result = cdp_call(ws, "Network.getAllCookies", msg_id=10)
    all_cookies = result.get("cookies", [])
    ws.close()

    # Filter YouTube + Google cookies
    yt_cookies = [c for c in all_cookies
                  if any(d in c.get("domain", "") for d in
                         [".youtube.com", "youtube.com",
                          ".google.com", "google.com",
                          ".googlevideo.com"])]

    print(f"Total cookies: {len(all_cookies)}")
    print(f"YouTube/Google cookies: {len(yt_cookies)}")

    # Write Netscape format
    out = "cookies.txt"
    count = 0
    with open(out, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n\n")
        for c in yt_cookies:
            domain = c["domain"]
            is_domain = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            expires = int(c.get("expires", 0))
            name = c["name"]
            value = c.get("value", "")
            if not value:
                continue
            f.write(f"{domain}\t{is_domain}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            count += 1

    print(f"Wrote {count} cookies to {out}")

    # Show key cookie names
    names = sorted(set(c["name"] for c in yt_cookies if c.get("value")))
    print(f"Cookie names: {names}")


if __name__ == "__main__":
    main()
