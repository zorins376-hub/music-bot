#!/usr/bin/env python3
"""Test direct VK API audio.search (bypassing broken vk_api.audio parser)."""
import sys, os
sys.path.insert(0, "/app")
from dotenv import load_dotenv
load_dotenv()
from bot.config import settings

import vk_api

session = vk_api.VkApi(token=settings.VK_TOKEN)
api = session.get_api()

print("=== Method 1: api.audio.search ===")
try:
    resp = api.audio.search(q="Ари Ури мы на Иссык куле", count=5)
    print(f"Got {resp.get('count', 0)} total, items: {len(resp.get('items', []))}")
    for item in resp.get("items", [])[:5]:
        print(f"  {item.get('artist','')} - {item.get('title','')} (dur={item.get('duration',0)})")
except Exception as e:
    print(f"Failed: {e}")

print("\n=== Method 2: session.method ===")
try:
    resp = session.method("audio.search", {"q": "Ари Ури мы на Иссык куле", "count": 5})
    print(f"Got {resp.get('count', 0)} total, items: {len(resp.get('items', []))}")
    for item in resp.get("items", [])[:5]:
        print(f"  {item.get('artist','')} - {item.get('title','')} (dur={item.get('duration',0)})")
        print(f"    url present: {bool(item.get('url',''))}")
except Exception as e:
    print(f"Failed: {e}")

print("\n=== Method 3: direct HTTP ===")
try:
    import requests
    resp = requests.get("https://api.vk.com/method/audio.search", params={
        "q": "Ари Ури мы на Иссык куле",
        "count": 5,
        "access_token": settings.VK_TOKEN,
        "v": "5.131",
    }, timeout=10)
    data = resp.json()
    if "error" in data:
        print(f"API error: {data['error'].get('error_msg','')}")
    else:
        items = data.get("response", {}).get("items", [])
        print(f"Got {len(items)} items")
        for item in items[:5]:
            print(f"  {item.get('artist','')} - {item.get('title','')} (dur={item.get('duration',0)})")
            print(f"    url present: {bool(item.get('url',''))}")
except Exception as e:
    print(f"Failed: {e}")
