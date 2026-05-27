#!/usr/bin/env python3
"""Try various VK audio search approaches."""
import sys, json, requests
sys.path.insert(0, "/app")
from dotenv import load_dotenv
load_dotenv()
from bot.config import settings

TOKEN = settings.VK_TOKEN
QUERY = "Треск Ари Ури"

# Method 1: Try older API version (5.95 - Kate Mobile era)
print("=== API v5.95 ===")
try:
    r = requests.get("https://api.vk.com/method/audio.search", params={
        "q": QUERY, "count": 5, "access_token": TOKEN, "v": "5.95"
    }, timeout=10)
    d = r.json()
    if "error" in d:
        print(f"  Error: {d['error'].get('error_code')} {d['error'].get('error_msg','')}")
    else:
        items = d.get("response", {}).get("items", [])
        print(f"  Got {len(items)} items")
        for it in items[:3]:
            print(f"    {it.get('artist','')} - {it.get('title','')} url={bool(it.get('url',''))}")
except Exception as e:
    print(f"  Failed: {e}")

# Method 2: Try v5.116 (last version some tokens worked)
print("\n=== API v5.116 ===")
try:
    r = requests.get("https://api.vk.com/method/audio.search", params={
        "q": QUERY, "count": 5, "access_token": TOKEN, "v": "5.116"
    }, timeout=10)
    d = r.json()
    if "error" in d:
        print(f"  Error: {d['error'].get('error_code')} {d['error'].get('error_msg','')}")
    else:
        items = d.get("response", {}).get("items", [])
        print(f"  Got {len(items)} items")
        for it in items[:3]:
            print(f"    {it.get('artist','')} - {it.get('title','')} url={bool(it.get('url',''))}")
except Exception as e:
    print(f"  Failed: {e}")

# Method 3: Try catalog.getAudio
print("\n=== catalog.getAudio v5.131 ===")
try:
    r = requests.get("https://api.vk.com/method/catalog.getAudio", params={
        "need_blocks": 0, "access_token": TOKEN, "v": "5.131"
    }, timeout=10)
    d = r.json()
    if "error" in d:
        print(f"  Error: {d['error'].get('error_code')} {d['error'].get('error_msg','')}")
    else:
        print(f"  Response keys: {list(d.get('response',{}).keys())[:10]}")
except Exception as e:
    print(f"  Failed: {e}")

# Method 4: Try audio.search with Kate Mobile app headers/params
print("\n=== API with Kate Mobile params ===")
try:
    r = requests.get("https://api.vk.com/method/audio.search", params={
        "q": QUERY, "count": 5, "access_token": TOKEN, "v": "5.95",
        "device_id": "0123456789abcdef",
    }, headers={
        "User-Agent": "VKAndroidApp/7.48-16291 (Android 11; SDK 30; x86_64; unknown; ru; 1080x1920)"
    }, timeout=10)
    d = r.json()
    if "error" in d:
        print(f"  Error: {d['error'].get('error_code')} {d['error'].get('error_msg','')}")
    else:
        items = d.get("response", {}).get("items", [])
        print(f"  Got {len(items)} items")
        for it in items[:3]:
            print(f"    {it.get('artist','')} - {it.get('title','')} url={bool(it.get('url',''))}")
except Exception as e:
    print(f"  Failed: {e}")

# Method 5: Check token permissions
print("\n=== Token info ===")
try:
    r = requests.get("https://api.vk.com/method/account.getAppPermissions", params={
        "access_token": TOKEN, "v": "5.131"
    }, timeout=10)
    d = r.json()
    perms = d.get("response", 0)
    print(f"  Permissions bitmask: {perms}")
    # audio = 8
    print(f"  Has audio (bit 3): {bool(perms & 8)}")
except Exception as e:
    print(f"  Failed: {e}")
