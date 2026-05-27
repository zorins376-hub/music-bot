from bot.config import settings
print("GENIUS_TOKEN:", "SET" if settings.GENIUS_TOKEN else "NOT SET")
print("SPOTIFY_CLIENT_ID:", "SET" if settings.SPOTIFY_CLIENT_ID else "NOT SET") 
print("VK_TOKEN:", "SET" if settings.VK_TOKEN else "NOT SET")
yt = getattr(settings, 'YANDEX_MUSIC_TOKENS', None) or getattr(settings, 'YANDEX_TOKEN', None)
print("YANDEX tokens:", "SET" if yt else "NOT SET")
# check what env_file is being used
import os
print("env_file dir:", os.listdir('/app')[:5])
print(".env present in /app:", os.path.exists('/app/.env'))
