#!/usr/bin/env python3
"""Regression test: check ranking for various query types."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("BOT_TOKEN", "fake")

from bot.services.search_engine import normalize_query, _relevance_score

def test(query, tracks):
    qn = normalize_query(query)
    print(f"\nQuery: {query}")
    for artist, title, src in tracks:
        score = _relevance_score(qn, artist, title, position=0)
        print(f"  {score:.3f}  {artist} - {title}")

# Test 1: Short query (2 words) — no coverage penalty expected
test("Miyagi Патрон", [
    ("Miyagi & Andy Panda", "Патрон", "yandex"),
    ("Miyagi", "Minor", "yandex"),
    ("Патрон", "Другая песня", "youtube"),
])

# Test 2: Exact artist-title
test("Скриптонит Вечеринка", [
    ("Скриптонит", "Вечеринка", "yandex"),
    ("Скриптонит", "Положение", "yandex"),
    ("Вечеринка хитов", "Сборник", "youtube"),
])

# Test 3: Long query (the fixed case)
test("Ари Ури мы на Иссык куле", [
    ("Aktilek", "Ари Ури мы на Иссык Куле", "youtube"),
    ("Акапелла", "Ари Ури - Acapella - Ari Uri", "youtube"),
    ("Astana Gorod", 'Асхат Норузбаев " На Иссык-Куле"', "youtube"),
    ("Aktilek", "Ари-Ури", "yandex"),
])

# Test 4: Mixed language query
test("Eminem Lose Yourself", [
    ("Eminem", "Lose Yourself", "spotify"),
    ("Eminem", "Without Me", "spotify"),
    ("DJ Mix", "Lose Yourself Remix", "youtube"),
])
