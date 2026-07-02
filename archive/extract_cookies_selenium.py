"""Extract YouTube/Google cookies from Chrome using Selenium.

Uses the existing Chrome user profile to preserve the logged-in session.
Writes cookies in Netscape format to cookies.txt.
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import os

USER_DATA = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
PROFILE = "Default"
OUT = "cookies.txt"

DOMAINS = [".youtube.com", "youtube.com", ".google.com",
           "google.com", ".googlevideo.com"]


def matches(domain):
    return any(d in domain for d in DOMAINS)


def cookie_line(c):
    domain = c["domain"]
    is_domain = "TRUE" if domain.startswith(".") else "FALSE"
    path = c.get("path", "/")
    secure = "TRUE" if c.get("secure", False) else "FALSE"
    expires = int(c.get("expiry", 0))
    name = c["name"]
    value = c.get("value", "")
    return f"{domain}\t{is_domain}\t{path}\t{secure}\t{expires}\t{name}\t{value}"


def main():
    opts = Options()
    opts.add_argument(f"--user-data-dir={USER_DATA}")
    opts.add_argument(f"--profile-directory={PROFILE}")
    opts.add_argument("--no-first-run")

    driver = webdriver.Chrome(options=opts)

    # YouTube cookies
    driver.get("https://www.youtube.com")
    time.sleep(5)
    yt_cookies = [c for c in driver.get_cookies() if matches(c.get("domain", ""))]
    print(f"YouTube cookies: {len(yt_cookies)}")

    # Google cookies
    driver.get("https://accounts.google.com")
    time.sleep(3)
    g_cookies = [c for c in driver.get_cookies() if matches(c.get("domain", ""))]
    print(f"Google cookies: {len(g_cookies)}")

    # Merge
    seen = set()
    merged = []
    for c in yt_cookies + g_cookies:
        key = (c["domain"], c["name"])
        if key not in seen and c.get("value"):
            seen.add(key)
            merged.append(c)

    # Write Netscape format
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n\n")
        for c in merged:
            f.write(cookie_line(c) + "\n")

    print(f"Wrote {len(merged)} cookies to {OUT}")

    driver.quit()
    print("Done!")


if __name__ == "__main__":
    main()
