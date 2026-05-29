"""Export YouTube cookies from Chrome to Netscape format cookies.txt

Uses yt-dlp's internal cookie extraction with a monkeypatched copy
to handle Chrome's locked database via Windows esentutl + VSS.
"""
import os
import shutil
import subprocess
import sys

# Monkeypatch shutil.copy to use esentutl for locked Chrome DB
_original_copy = shutil.copy

def _vss_copy(src, dst, *args, **kwargs):
    """Try normal copy first; on failure use esentutl /vss (Windows shadow copy)."""
    try:
        return _original_copy(src, dst, *args, **kwargs)
    except PermissionError:
        result = subprocess.run(
            ["esentutl", "/y", src, "/vss", "/d", dst],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not os.path.exists(dst):
            raise
        return dst

shutil.copy = _vss_copy

# Now use yt-dlp's cookie extraction which will handle v20 decryption
from yt_dlp.cookies import extract_cookies_from_browser
from http.cookiejar import MozillaCookieJar

jar = extract_cookies_from_browser("chrome")

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
mcj = MozillaCookieJar(out_path)
for cookie in jar:
    mcj.set_cookie(cookie)
mcj.save(ignore_discard=True, ignore_expires=True)

# Restore original
shutil.copy = _original_copy

count = len(list(jar))
print(f"Exported {count} cookies to {out_path}")
