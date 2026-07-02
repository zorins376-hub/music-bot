"""Smoke-test all 10 Supabase Edge Functions with correct API formats."""
import json
import os
import sys
import urllib.request
import ssl
from urllib.parse import urlencode

BASE = os.environ.get(
    "SUPABASE_AI_FUNCTIONS_URL",
    "https://vexyurbyobnpzyatiikw.supabase.co/functions/v1",
)
KEY = os.environ.get("SUPABASE_AI_DB_KEY")
if not KEY:
    sys.exit("SUPABASE_AI_DB_KEY is not set — export the service-role key before running")
CTX = ssl.create_default_context()

USER_ID = 8280273907

# (name, method, query_params_or_None, json_body_or_None)
TESTS = [
    # GET endpoints (query params)
    ("recommend", "GET", {"user_id": USER_ID, "limit": 3}, None),
    ("trending", "POST", None, {"period_days": 30, "limit": 3}),
    ("similar", "GET", {"source_id": "1575091720", "limit": 3}, None),
    ("search", "GET", {"q": "dizzi", "limit": 3}, None),
    # POST endpoints (JSON body)
    ("feedback", "POST", None, {"user_id": USER_ID, "feedback": "like", "source_id": "1575091720"}),
    ("ingest", "POST", None, {"event": "play", "user_id": USER_ID, "track": {"source_id": "smoke_test_123", "title": "Smoke Test", "artist": "Test Artist"}}),
    ("update-profile", "POST", None, {"user_id": USER_ID}),
    ("analytics", "POST", None, {"period": "week"}),
    ("ai-playlist", "POST", None, {"user_id": USER_ID, "prompt": "веселая музыка", "limit": 3}),
    ("embed-tracks", "POST", None, {"limit": 3}),
]

passed = 0
failed = 0

for name, method, params, body in TESTS:
    url = f"{BASE}/{name}"
    if params:
        url += "?" + urlencode(params)

    data = json.dumps(body).encode() if body else None
    headers = {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, context=CTX, timeout=30)
        result = json.loads(resp.read())
        summary = json.dumps(result, ensure_ascii=False)
        if len(summary) > 150:
            summary = summary[:150] + "..."
        print(f"  OK  {name:20s} {resp.status} {summary}")
        passed += 1
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:150]
        print(f"  ERR {name:20s} {e.code} {body_text}")
        failed += 1
    except Exception as e:
        print(f"  ERR {name:20s} {e}")
        failed += 1

print(f"\n{passed}/{len(TESTS)} functions OK, {failed} failed")
