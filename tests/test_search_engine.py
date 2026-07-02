"""Tests for bot/services/search_engine.py — TASK-001."""
import pytest
from bot.services.search_engine import (
    normalize_query,
    detect_script,
    transliterate_cyr_to_lat,
    transliterate_lat_to_cyr,
    deduplicate_results,
    suggest_query,
    parse_query,
    _normalize_for_dedup,
    _jaccard_similarity,
    _relevance_score,
    is_lyric_like_query,
    needs_lyrics_search_boost,
    lyric_search_variants,
    extract_distinctive_lyric_words,
)


# ── normalize_query ───────────────────────────────────────────────────────

class TestNormalizeQuery:
    def test_strip_and_lower(self):
        assert normalize_query("  Hello World  ") == "hello world"

    def test_strip_junk(self):
        assert normalize_query("Queen?!") == "queen"

    def test_collapse_spaces(self):
        assert normalize_query("a   b     c") == "a b c"

    def test_preserves_the_prefix(self):
        assert normalize_query("The Beatles") == "the beatles"

    def test_the_weeknd(self):
        assert normalize_query("The Weeknd") == "the weeknd"

    def test_no_strip_the_mid(self):
        assert normalize_query("Something the way") == "something the way"

    def test_empty(self):
        assert normalize_query("") == ""

    def test_brackets(self):
        assert normalize_query("Track [remix]") == "track"
        assert normalize_query("Track (official video)") == "track"


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


# ── Cyrillic artist + title relevance ─────────────────────────────────────

class TestLyricFragmentSearch:
    def test_parse_two_word_cyrillic(self):
        parsed = parse_query("матранг рука")
        assert parsed["artist_hint"] == "матранг"
        assert parsed["title_hint"] == "рука"

    def test_is_lyric_like_query(self):
        assert is_lyric_like_query("любит небо")
        assert is_lyric_like_query("хочется жить каждый день")
        assert not is_lyric_like_query("AC/DC - Thunderstruck")

    def test_matrang_ruka_prefers_matching_title(self):
        query = "матранг рука"
        qn = normalize_query(query)
        parsed = parse_query(query)
        with_ruka = {"title": "Руки на руке", "uploader": "MATRANG", "source": "yandex", "_provider_pos": 0}
        with_krug = {"title": "Круг", "uploader": "MATRANG", "source": "yandex", "_provider_pos": 1}
        assert _relevance_score(
            qn, with_ruka["uploader"], with_ruka["title"], parsed=parsed
        ) > _relevance_score(
            qn, with_krug["uploader"], with_krug["title"], parsed=parsed
        )

    def test_priezzhai_prefers_title_word(self):
        query = "104 приезжай"
        qn = normalize_query(query)
        parsed = parse_query(query)
        correct = {"title": "Приезжай", "uploader": "104", "source": "yandex", "_provider_pos": 0}
        wrong = {"title": "Движения", "uploader": "104, Скриптонит, Kali", "source": "yandex", "_provider_pos": 0}
        assert _relevance_score(
            qn, correct["uploader"], correct["title"], parsed=parsed
        ) > _relevance_score(
            qn, wrong["uploader"], wrong["title"], parsed=parsed
        )

    def test_needs_lyrics_boost_when_title_words_missing(self):
        top = {"uploader": "Матранг", "title": "Круг", "_provider_pos": 0}
        assert needs_lyrics_search_boost("матранг рука", top, parsed=parse_query("матранг рука"))
        good = {"uploader": "MATRANG", "title": "Руки на руке", "_provider_pos": 0}
        assert not needs_lyrics_search_boost("матранг рука", good, parsed=parse_query("матранг рука"))

    def test_matrang_ruka_dedup_order(self):
        query = "матранг рука"
        results = deduplicate_results(
            [
                {"title": "Круг", "uploader": "MATRANG", "source": "yandex", "_provider_pos": 1},
                {"title": "Руки на руке", "uploader": "MATRANG", "source": "yandex", "_provider_pos": 0},
            ],
            lang_hint="cyrillic",
            query=query,
        )
        assert "рук" in normalize_query(results[0]["title"])


class TestCyrillicArtistTitleRelevance:
    def test_parse_query_splits_cyrillic_without_dash(self):
        parsed = parse_query("Скриптонит это моя вечеринка")
        assert parsed["artist_hint"] == "скриптонит"
        assert parsed["title_hint"] == "это моя вечеринка"

    def test_scriptonite_ranks_above_partial_yandex_match(self):
        query = "Скриптонит это моя вечеринка"
        qn = normalize_query(query)
        parsed = parse_query(query)
        correct = {
            "title": "Это моя вечеринка",
            "uploader": "Скриптонит",
            "source": "youtube",
            "_provider_pos": 1,
        }
        wrong = {
            "title": "Моя вечеринка 2024",
            "uploader": "DJ Smash",
            "source": "yandex",
            "_provider_pos": 0,
        }
        assert _relevance_score(
            qn, correct["uploader"], correct["title"], parsed=parsed
        ) > _relevance_score(
            qn, wrong["uploader"], wrong["title"], parsed=parsed
        )

    def test_dedup_puts_scriptonite_first(self):
        query = "Скриптонит это моя вечеринка"
        results = deduplicate_results(
            [
                {
                    "title": "Моя вечеринка 2024",
                    "uploader": "DJ Smash",
                    "source": "yandex",
                    "_provider_pos": 0,
                },
                {
                    "title": "Это моя вечеринка",
                    "uploader": "Скриптонит",
                    "source": "youtube",
                    "_provider_pos": 1,
                },
            ],
            lang_hint="cyrillic",
            query=query,
        )
        assert results[0]["uploader"] == "Скриптонит"


class TestTypoAndAliasRelevance:
    def test_parse_asxa_prince_short_title(self):
        parsed = parse_query("асха принц су")
        assert parsed["artist_hint"] == "асха принц"
        assert parsed["title_hint"] == "су"

    def test_typo_surname_artist_only(self):
        q = "леонид партной"
        parsed = parse_query(q)
        qn = normalize_query(q)
        sc = _relevance_score(qn, "Леонид Портной", "Кто тебя создал такую", parsed=parsed)
        assert sc >= 1.0

    def test_asxa_prince_typo_title_ranks_high(self):
        q = "асха принц гододная собака"
        parsed = parse_query(q)
        qn = normalize_query(q)
        good = _relevance_score(qn, "V $ X V PRiNCE", "Голодная собака", parsed=parsed)
        wrong = _relevance_score(qn, "V $ X V PRiNCE", "Модная подруга", parsed=parsed)
        assert good >= 1.45
        assert good > wrong + 0.3

    def test_lyric_kokaina_title_word(self):
        q = "Дай нам мам кокаина"
        parsed = parse_query(q)
        qn = normalize_query(q)
        sc = _relevance_score(qn, "Alesya Anis, LEO.K", "Кокаина", parsed=parsed)
        assert sc >= 0.9

    def test_lyric_wrong_song_penalized(self):
        q = "я теперь твоё воспоминанье"
        parsed = parse_query(q)
        qn = normalize_query(q)
        wrong = _relevance_score(qn, "Ellai", "Помню твоё тело", parsed=parsed)
        ideal = _relevance_score(
            qn, "Artist", "Я теперь твоё воспоминанье", parsed=parsed,
        )
        assert wrong < ideal


class TestLyricSearchVariants:
    def test_vospominanie_variants(self):
        q = "я теперь твоё воспоминанье"
        variants = lyric_search_variants(q)
        assert variants[0] == normalize_query(q)
        assert "воспоминанье" in variants
        assert any("твоё" in v for v in variants)

    def test_distinctive_word_kokaina(self):
        words = extract_distinctive_lyric_words("дай нам мам кокаина")
        assert "кокаина" in words

    def test_koka_lova_not_artist_title_split(self):
        parsed = parse_query("кока лова")
        assert parsed.get("artist_hint") is None
        assert parsed.get("title_hint") is None
        assert is_lyric_like_query("кока лова", parsed)

    def test_koka_lova_aliases(self):
        from bot.services.search_engine import get_query_search_aliases
        aliases = get_query_search_aliases("кока лова")
        assert "Koka Lova" in aliases
        assert "Jax 02.14 Koka Lova" in aliases
        assert "кокаина" not in aliases

    def test_koka_stem_matches_kokaina_title(self):
        from bot.services.search_engine import query_title_hint_coverage, normalize_query
        # «кока лова» is the song title Koka Lova, not «Кокаина»
        cov = query_title_hint_coverage(normalize_query("koka lova"), "Koka Lova", None)
        assert cov >= 0.5

    def test_lyrics_hint_track_ranks_with_score_query(self):
        query = "я теперь твоё воспоминанье"
        wrong = {
            "title": "Помню твоё тело",
            "uploader": "Ellai",
            "source": "yandex",
            "_provider_pos": 0,
        }
        resolved = {
            "title": "Помню как было",
            "uploader": "Ellai",
            "source": "yandex",
            "_provider_pos": 0,
            "_score_query": "ellai помню как было",
            "_hint_bonus": 2.45,
            "_from_lyrics": True,
        }
        ranked = deduplicate_results([wrong, resolved], query=query)
        assert ranked[0]["title"] == "Помню как было"
