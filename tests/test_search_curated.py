"""Tests for curated search pins and aliases."""
from bot.services.search_curated import (
    CURATED_QUERY_PINS,
    curated_track_for_query,
    inject_curated_track,
    query_search_aliases,
)
from bot.services.search_engine import _relevance_score, deduplicate_results, normalize_query, parse_query


class TestSearchCurated:
    def test_koka_lova_aliases(self):
        aliases = query_search_aliases("кока лова")
        assert "Koka Lova" in aliases
        assert "Jax 02.14 Koka Lova" in aliases

    def test_curated_track_koka_lova(self):
        t = curated_track_for_query("кока лова")
        assert t and t["video_id"] == "ym_114644167"

    def test_curated_track_scriptonite(self):
        t = curated_track_for_query("скриптонит это моя вечеринка")
        assert t and t["ym_track_id"] == 48592103
        assert "скриптонит" in t["uploader"].lower()

    def test_inject_curated_prepends(self):
        out = inject_curated_track([{"video_id": "x", "title": "Other"}], "матранг рука")
        assert out[0]["video_id"] == "ym_78269648"

    def test_scriptonite_ranks_above_uicidekid(self):
        query = "Скриптонит это моя вечеринка"
        parsed = parse_query(query)
        qn = normalize_query(query)
        correct = {
            "title": "Вечеринка",
            "uploader": "Скриптонит",
            "source": "yandex",
            "_provider_pos": 0,
            "_hint_bonus": 3.0,
        }
        wrong = {
            "title": "Это моя вечеринка",
            "uploader": "$UICIDEKID",
            "source": "yandex",
            "_provider_pos": 0,
        }
        assert _relevance_score(qn, correct["uploader"], correct["title"], parsed=parsed) + 3.0 > \
            _relevance_score(qn, wrong["uploader"], wrong["title"], parsed=parsed)

    def test_dedup_curated_scriptonite_first(self):
        query = "скриптонит это моя вечеринка"
        results = inject_curated_track([
            {
                "title": "Это моя вечеринка",
                "uploader": "$UICIDEKID",
                "source": "yandex",
                "video_id": "ym_65612064",
                "_provider_pos": 0,
            },
        ], query)
        ranked = deduplicate_results(results, query=query, lang_hint="cyrillic")
        assert ranked[0]["uploader"] == "Скриптонит"

    def test_all_pins_resolve(self):
        for q, ym_id in CURATED_QUERY_PINS.items():
            t = curated_track_for_query(q)
            assert t is not None, q
            assert t["ym_track_id"] == ym_id, q

    def test_dash_query_scriptonite(self):
        t = curated_track_for_query("скриптонит – вечеринка")
        assert t and t["ym_track_id"] == 48592103

    def test_makan_porusan_typo(self):
        q = "макан " + "порус" + "an"
        t = curated_track_for_query(q)
        assert t and t["ym_track_id"] == 138207754

    def test_ampersand_klava_krash(self):
        t = curated_track_for_query("клава кока  & niletto  краш")
        assert t and t["ym_track_id"] == 66869588

        t = curated_track_for_query("асха принц гододная собака")
        assert t and t["ym_track_id"] == 113906634

    def test_junk_query_filter(self):
        from bot.services.search_curated import is_junk_search_query
        assert is_junk_search_query("@tsmymusicbot_bot")
        assert not is_junk_search_query("кока лова")
        assert not is_junk_search_query(
            "https://music.yandex.ru/album/14307741/track/79040176"
            "?utm_medium=copy_link&ref_id=a84692b7-446f-45fe-951f-89b6af1d7e9e"
        )
