from bot.config import settings
yt = settings.YANDEX_MUSIC_TOKEN
print("YANDEX_MUSIC_TOKEN:", yt[:10] + "..." if yt else "NOT SET")
from bot.services.yandex_provider import _load_tokens
toks = _load_tokens()
print("Loaded tokens:", len(toks))
for i, t in enumerate(toks):
    print(f"  [{i}] {t[:10]}...")
