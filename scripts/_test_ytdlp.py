"""Quick test: does yt-dlp Python API resolve formats with remote_components?"""
from yt_dlp import YoutubeDL

opts = {
    "remote_components": {"ejs:github"},
    "listformats": True,
    "cookiefile": "/app/data/cookies.txt",
    "js_runtimes": {"deno": {"path": "/usr/local/bin/deno"}},
}
with YoutubeDL(opts) as ydl:
    ydl.download(["dQw4w9WgXcQ"])
