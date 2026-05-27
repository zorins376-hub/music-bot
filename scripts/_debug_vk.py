#!/usr/bin/env python3
"""Debug VK provider error."""
import traceback, sys, os
sys.path.insert(0, "/app")
from dotenv import load_dotenv
load_dotenv()
from bot.config import settings

print("VK_TOKEN set:", bool(settings.VK_TOKEN))
print("VK_TOKEN first 10:", settings.VK_TOKEN[:10] if settings.VK_TOKEN else "N/A")

try:
    import vk_api
    from vk_api.audio import VkAudio
    session = vk_api.VkApi(token=settings.VK_TOKEN)
    va = VkAudio(session)
    print("VkAudio created OK")
    print("Searching 'test'...")
    tracks = list(va.search(q="test", count=3))
    print(f"OK, got {len(tracks)} tracks for 'test'")
    for t in tracks[:2]:
        print(f"  {t.get('artist','')} - {t.get('title','')}")
except Exception:
    traceback.print_exc()

print("\n--- Now searching target query ---")
try:
    import vk_api
    from vk_api.audio import VkAudio
    session = vk_api.VkApi(token=settings.VK_TOKEN)
    va = VkAudio(session)
    tracks = list(va.search(q="Ари Ури мы на Иссык куле", count=5))
    print(f"Got {len(tracks)} tracks")
    for t in tracks[:5]:
        print(f"  {t.get('artist','')} - {t.get('title','')}")
except Exception:
    traceback.print_exc()
