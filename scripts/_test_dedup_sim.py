import sys; sys.path.insert(0, "/app")
from dotenv import load_dotenv; load_dotenv()
from rapidfuzz import fuzz
from bot.services.search_engine import _normalize_for_dedup

k1 = _normalize_for_dedup("Акапелла", "Ари Ури - Acapella - Ari Uri")
k2 = _normalize_for_dedup("ACAPELLA", "Треск")
sim = fuzz.token_sort_ratio(k1, k2) / 100.0
print(f"key1: {k1}")
print(f"key2: {k2}")
print(f"similarity: {sim:.3f}")
print(f"threshold: 0.7")
print(f"is_dup: {sim >= 0.7}")
