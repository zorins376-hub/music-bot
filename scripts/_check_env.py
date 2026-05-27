import os
print("GENIUS_TOKEN:", "SET" if os.environ.get("GENIUS_TOKEN") else "NOT SET")
print("GENIUS_PROXY_URL:", os.environ.get("GENIUS_PROXY_URL", "NOT SET"))
print("SPOTIFY_CLIENT_ID:", "SET" if os.environ.get("SPOTIFY_CLIENT_ID") else "NOT SET")
print("SPOTIFY_CLIENT_SECRET:", "SET" if os.environ.get("SPOTIFY_CLIENT_SECRET") else "NOT SET")
print("VK_TOKEN:", "SET" if os.environ.get("VK_TOKEN") else "NOT SET")
print("YANDEX_TOKENS set:", "SET" if os.environ.get("YANDEX_MUSIC_TOKENS") or os.environ.get("YANDEX_TOKEN") else "NOT SET")
