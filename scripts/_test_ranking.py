#!/usr/bin/env python3
"""Quick local test of the new ranking logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("BOT_TOKEN", "fake")

from bot.services.search_engine import (
    normalize_query, _relevance_score, deduplicate_results, detect_script
)

QUERY = "Ари Ури мы на Иссык куле"
qn = normalize_query(QUERY)

# Simulate the results from providers (exact data from VPS test)
ym_results = [
    {"video_id": "ym_1", "uploader": "Aktilek", "title": "Ари-Ури", "source": "yandex", "_provider_pos": 0, "duration": 190},
]
yt_results = [
    {"video_id": "yt_1", "uploader": "MC Mara & 312", "title": "Ari Uri (2005)", "source": "youtube", "_provider_pos": 0, "duration": 237},
    {"video_id": "yt_2", "uploader": "MC Mara", "title": "Ари Ури [ ft Calipso & Dengerous & Ulik ] [ 2005 год.]", "source": "youtube", "_provider_pos": 1, "duration": 326},
    {"video_id": "yt_3", "uploader": "312", "title": '"Зона Отдыха 312"', "source": "youtube", "_provider_pos": 2, "duration": 225},
    {"video_id": "yt_4", "uploader": "Акапелла", "title": "Ари Ури - Acapella - Ari Uri", "source": "youtube", "_provider_pos": 3, "duration": 237},
    {"video_id": "yt_5", "uploader": "Aktilek", "title": "Ари Ури мы на Иссык Куле", "source": "youtube", "_provider_pos": 4, "duration": 192},
    {"video_id": "yt_6", "uploader": "Astana Gorod", "title": 'Асхат Норузбаев " На Иссык-Куле"', "source": "youtube", "_provider_pos": 5, "duration": 200},
]

print(f"Query: {QUERY}")
print(f"Normalized: {qn}")
print(f"Script: {detect_script(QUERY)}")
print()

# Show individual scores
print("=== Individual scores ===")
all_tracks = ym_results + yt_results
for t in all_tracks:
    score = _relevance_score(qn, t["uploader"], t["title"], t.get("_provider_pos", 5))
    print(f"  {score:.3f}  [{t['source']}] {t['uploader']} - {t['title']}")

# Run full dedup + ranking
print("\n=== After dedup + ranking ===")
script = detect_script(QUERY)
ranked = deduplicate_results(all_tracks, lang_hint=script, query=QUERY)
for i, t in enumerate(ranked):
    score = _relevance_score(qn, t["uploader"], t["title"], t.get("_provider_pos", 5))
    print(f"  #{i}: {score:.3f}  [{t['source']}] {t['uploader']} - {t['title']}")
