"""Tests for bot/services/search_engine.py — TASK-001."""
import pytest
from bot.services.search_engine import (
    normalize_query,
    detect_script,
    transliterate_cyr_to_lat,
    transliterate_lat_to_cyr,
    deduplicate_results,
    suggest_query,
    _normalize_for_dedup,
    _jaccard_similarity,
)


# ── normalize_query ───────────────────────────────────────────────────────

class TestNormalizeQuery:
    def test_strip_and_lower(self):
        assert normalize_query("  Hello World  ") == "hello world"

    def test_strip_junk(self):
        assert normalize_query("Queen?!") == "queen"

    def test_collapse_spaces(self):
        assert normalize_query("a   b     c") == "a b c"

    def test_strip_the_prefix(self):
        assert normalize_query("The Beatles") == "beatles"

    def test_no_strip_the_mid(self):
        assert normalize_query("Something the way") == "something the way"

    def test_empty(self):
        assert normalize_query("") == ""

    def test_brackets(self):
        assert normalize_query("Track [remix]") == "track remix"


# ── detect_script ─────────────────────────────────────────────────────────

class TestDetectScript:
    def test_cyrillic(self):
        assert detect_script("Кино") == "cyrillic"

    def test_latin(self):
        assert detect_script("Metallica") == "latin"

    def test_mixed(self):
        assert detect_script("AC/DС") == "mixed"  # DC = кириллица С

    def test_numbers_only(self):
        assert detect_script("123") == "mixed"


# ── transliterate ─────────────────────────────────────────────────────────

class TestTransliterate:
    def test_cyr_to_lat(self):
        assert transliterate_cyr_to_lat("кино") == "kino"

    def test_cyr_to_lat_complex(self):
        result = transliterate_cyr_to_lat("жуки")
        assert result == "zhuki"

    def test_lat_to_cyr(self):
        assert transliterate_lat_to_cyr("kino") == "кино"

    def test_lat_to_cyr_digraphs(self):
        assert transliterate_lat_to_cyr("zhuki") == "жуки"

    def test_round_trip_cyr(self):
        # Not always exact round-trip, but should be close
        original = "кино"
        lat = transliterate_cyr_to_lat(original)
        back = transliterate_lat_to_cyr(lat)
        assert back == original

    def test_preserves_non_alpha(self):
        assert transliterate_cyr_to_lat("кино 2") == "kino 2"


# ── _normalize_for_dedup ─────────────────────────────────────────────────

class TestNormalizeForDedup:
    def test_basic(self):
        key = _normalize_for_dedup("Queen", "Bohemian Rhapsody")
        assert key == "queen bohemian rhapsody"

    def test_strips_feat(self):
        key = _normalize_for_dedup("Artist feat. Someone", "Song")
        assert "someone" not in key

    def test_strips_ft(self):
        key = _normalize_for_dedup("Artist (ft. Someone)", "Song")
        assert "someone" not in key


# ── _jaccard_similarity ──────────────────────────────────────────────────

class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert _jaccard_similarity("hello", "world") == 0.0

    def test_partial(self):
        sim = _jaccard_similarity("a b c", "b c d")
        assert 0.4 < sim < 0.6  # 2/4 = 0.5

    def test_empty(self):
        assert _jaccard_similarity("", "hello") == 0.0


# ── deduplicate_results ──────────────────────────────────────────────────

class TestDeduplicateResults:
    def test_empty(self):
        assert deduplicate_results([]) == []

    def test_no_duplicates(self):
        results = [
            {"title": "Song A", "uploader": "Artist A", "source": "youtube"},
            {"title": "Song B", "uploader": "Artist B", "source": "spotify"},
        ]
        assert len(deduplicate_results(results)) == 2

    def test_removes_duplicate_keeps_best_source(self):
        results = [
            {"title": "Bohemian Rhapsody", "uploader": "Queen", "source": "youtube"},
            {"title": "Bohemian Rhapsody", "uploader": "Queen", "source": "yandex"},
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0]["source"] == "yandex"  # higher rank

    def test_fuzzy_duplicate(self):
        results = [
            {"title": "Bohemian Rhapsody (Remastered)", "uploader": "Queen", "source": "spotify"},
            {"title": "Bohemian Rhapsody", "uploader": "Queen", "source": "youtube"},
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0]["source"] == "spotify"  # higher rank

    def test_different_tracks_kept(self):
        results = [
            {"title": "Song A", "uploader": "Artist X", "source": "youtube"},
            {"title": "Song B", "uploader": "Artist Y", "source": "youtube"},
        ]
        assert len(deduplicate_results(results)) == 2

    def test_channel_highest_priority(self):
        results = [
            {"title": "Track", "uploader": "DJ", "source": "yandex"},
            {"title": "Track", "uploader": "DJ", "source": "channel"},
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0]["source"] == "channel"


# ── suggest_query ────────────────────────────────────────────────────────

class TestSuggestQuery:
    def test_exact_match(self):
        corpus = ["Queen - Bohemian Rhapsody", "Metallica - Nothing Else Matters"]
        result = suggest_query("bohemian rhapsody", corpus)
        assert len(result) == 1
        assert "Bohemian Rhapsody" in result[0]

    def test_typo(self):
        corpus = ["Nirvana - Smells Like Teen Spirit", "AC/DC - Thunderstruck"]
        result = suggest_query("nirvana smells", corpus)
        assert len(result) == 1
        assert "Nirvana" in result[0]

    def test_no_match(self):
        corpus = ["Queen - Bohemian Rhapsody"]
        result = suggest_query("xyzabc", corpus)
        assert result == []

    def test_empty_query(self):
        assert suggest_query("", ["something"]) == []

    def test_empty_corpus(self):
        assert suggest_query("test", []) == []
