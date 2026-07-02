"""Tests for lyrics_provider search variants and ranking."""
from unittest.mock import AsyncMock

import pytest

from bot.services.lyrics_provider import (
    _rank_lyric_hints,
    lyric_fragment_matches_query,
    resolve_lyrics_from_candidates,
    search_by_lyrics,
)
from bot.services.search_engine import normalize_query


class TestLyricFragmentMatch:
    def test_exact_line_in_lyrics(self):
        q = normalize_query("я теперь твоё воспоминанье")
        lyrics = "Я теперь твоё воспоминанье\nНе возвращай меня\n"
        assert lyric_fragment_matches_query(q, lyrics)

    def test_rejects_unrelated_lyrics(self):
        q = normalize_query("дай нам мам кокаина")
        assert not lyric_fragment_matches_query(q, "совсем другой текст песни")

    def test_inflection_vospominanie(self):
        q = normalize_query("я теперь твоё воспоминанье")
        lyrics = "Я теперь твоё воспоминание\nНе возвращай меня\n"
        assert lyric_fragment_matches_query(q, lyrics)


class TestRankLyricHints:
    def test_prefers_title_with_distinctive_word(self):
        hints = [
            {"artist": "Wrong Artist", "title": "Random Song", "source": "musixmatch"},
            {"artist": "Alesya Anis", "title": "Кокаина", "source": "musixmatch"},
        ]
        ranked = _rank_lyric_hints(hints, "дай нам мам кокаина")
        assert ranked[0]["title"] == "Кокаина"


@pytest.mark.asyncio
async def test_search_by_lyrics_tries_variants(monkeypatch):
    calls: list[str] = []

    async def fake_musixmatch(query: str, limit: int) -> list[dict]:
        calls.append(query)
        if query == "воспоминанье":
            return [{"artist": "Ellai", "title": "Помню как было", "source": "musixmatch"}]
        return []

    async def fake_genius(query: str, limit: int) -> list[dict]:
        return []

    async def fake_cache_set(*args, **kwargs):
        return None

    class FakeRedis:
        async def get(self, key):
            return None

        async def setex(self, *args, **kwargs):
            return await fake_cache_set()

    class FakeCache:
        redis = FakeRedis()

    monkeypatch.setattr("bot.services.lyrics_provider._search_musixmatch_lyrics", fake_musixmatch)
    monkeypatch.setattr("bot.services.lyrics_provider._search_genius_lyrics", fake_genius)
    monkeypatch.setattr("bot.services.cache.cache", FakeCache())

    results = await search_by_lyrics("я теперь твоё воспоминанье", limit=3)
    assert results
    assert results[0]["artist"] == "Ellai"


@pytest.mark.asyncio
async def test_resolve_lyrics_from_candidates(monkeypatch):
    async def fake_lrclib(artist, title):
        if "nyusha" in artist.lower():
            return "Я теперь твоё воспоминанье\nНе возвращай меня"
        return None

    monkeypatch.setattr(
        "bot.services.lyrics_provider._lrclib_fetch_plain_lyrics",
        fake_lrclib,
    )
    candidates = [
        {"uploader": "NYUSHA", "title": "Воспоминание"},
        {"uploader": "Other", "title": "Random"},
    ]
    hits = await resolve_lyrics_from_candidates(
        "я теперь твоё воспоминанье",
        candidates,
        limit=2,
    )
    assert hits
    assert hits[0]["artist"] == "NYUSHA"
    assert hits[0]["source"] == "lrclib"
