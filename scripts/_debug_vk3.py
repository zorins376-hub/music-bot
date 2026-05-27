#!/usr/bin/env python3
"""Debug: inspect raw VK al_audio.php search response."""
import sys, json
sys.path.insert(0, "/app")
from dotenv import load_dotenv
load_dotenv()
from bot.config import settings

import vk_api

session = vk_api.VkApi(token=settings.VK_TOKEN)
session.token = {"access_token": settings.VK_TOKEN}
# Get user_id from token
try:
    api = session.get_api()
    me = api.users.get()
    uid = me[0]["id"] if me else 0
except Exception:
    uid = 0
print(f"user_id: {uid}")

response = session.http.post(
    "https://vk.com/al_audio.php",
    data={
        "al": 1,
        "act": "section",
        "claim": 0,
        "is_layer": 0,
        "owner_id": uid,
        "section": "search",
        "q": "Треск ACAPELLA",
    },
)

raw = response.text.replace("<!--", "")
data = json.loads(raw)

payload = data.get("payload", [])
print(f"payload length: {len(payload)}")
if len(payload) > 1:
    p1 = payload[1]
    print(f"payload[1] type: {type(p1).__name__}, len: {len(p1) if isinstance(p1, (list,dict)) else 'N/A'}")
    if isinstance(p1, list):
        for i, item in enumerate(p1):
            t = type(item).__name__
            if isinstance(item, dict):
                print(f"  payload[1][{i}]: dict keys={list(item.keys())[:15]}")
            elif isinstance(item, list):
                print(f"  payload[1][{i}]: list len={len(item)}")
            elif isinstance(item, str):
                print(f"  payload[1][{i}]: str len={len(item)} preview={item[:80]}")
            else:
                print(f"  payload[1][{i}]: {t} = {str(item)[:80]}")
    elif isinstance(p1, dict):
        print(f"  payload[1] keys: {list(p1.keys())[:15]}")

# Try to find playlist data in the structure
def find_key(obj, target, depth=0, path=""):
    if depth > 5:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target:
                if isinstance(v, dict):
                    print(f"FOUND '{target}' at {path}.{k}: dict keys={list(v.keys())[:10]}")
                elif isinstance(v, list):
                    print(f"FOUND '{target}' at {path}.{k}: list len={len(v)}")
                else:
                    print(f"FOUND '{target}' at {path}.{k}: {type(v).__name__}={str(v)[:60]}")
            find_key(v, target, depth+1, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            find_key(v, target, depth+1, f"{path}[{i}]")

print("\n--- Searching for 'playlist' key ---")
find_key(data, "playlist")
print("\n--- Searching for 'sectionId' key ---")
find_key(data, "sectionId")
print("\n--- Searching for 'list' key (audio list) ---")
find_key(data, "list")
