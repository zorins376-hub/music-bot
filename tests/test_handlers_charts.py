"""Tests for bot/handlers/charts.py — chart helpers and parsers."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_callback, make_message


def _make_user(lang="ru"):
    u = MagicMock()
    u.id = 1
    u.language = lang
    return u


# ── _has_cyrillic ────────────────────────────────────────────────────────

class TestHasCyrillic:
    def test_cyrillic_text(self):
        from bot.handlers.charts import _has_cyrillic
        assert _has_cyrillic("Привет") is True

    def test_latin_text(self):
        from bot.handlers.charts import _has_cyrillic
        assert _has_cyrillic("Hello World") is False

    def test_mixed(self):
        from bot.handlers.charts import _has_cyrillic
        assert _has_cyrillic("Hello Мир") is True

    def test_empty(self):
        from bot.handlers.charts import _has_cyrillic
        assert _has_cyrillic("") is False

    def test_numbers(self):
        from bot.handlers.charts import _has_cyrillic
        assert _has_cyrillic("12345") is False


# ── _parse_yt_entries ────────────────────────────────────────────────────

class TestParseYtEntries:
    def test_normal_entries(self):
        from bot.handlers.charts import _parse_yt_entries
        entries = [
            {"title": "Artist - Song Title", "duration": 200, "id": "abc"},
            {"title": "Another - Track", "duration": 180, "id": "def"},
        ]
        result = _parse_yt_entries(entries)
        assert len(result) == 2
        assert result[0]["artist"] == "Artist"
        assert result[0]["title"] == "Song Title"

    def test_skip_compilations(self):
        from bot.handlers.charts import _parse_yt_entries
        entries = [
            {"title": "Artist - Song", "duration": 200, "id": "a"},
            {"title": "DJ Mix - 1 Hour Compilation", "duration": 3600, "id": "b"},  # > 8 min
        ]
        result = _parse_yt_entries(entries)
        assert len(result) == 1

    def test_no_separator_uses_uploader(self):
        from bot.handlers.charts import _parse_yt_entries
        entries = [{"title": "Song Without Dash", "uploader": "TheArtist", "duration": 120, "id": "x"}]
        result = _parse_yt_entries(entries)
        assert result[0]["artist"] == "TheArtist"
        assert result[0]["title"] == "Song Without Dash"

    def test_cyrillic_only_filter(self):
        from bot.handlers.charts import _parse_yt_entries
        entries = [
            {"title": "Артист - Песня", "duration": 200, "id": "a"},
            {"title": "English - Song", "duration": 200, "id": "b"},
        ]
        result = _parse_yt_entries(entries, cyrillic_only=True)
        assert len(result) == 1
        assert result[0]["artist"] == "Артист"

    def test_empty_entries(self):
        from bot.handlers.charts import _parse_yt_entries
        assert _parse_yt_entries([]) == []

    def test_none_entries_in_list(self):
        from bot.handlers.charts import _parse_yt_entries
        entries = [None, {"title": "A - B", "duration": 100, "id": "c"}]
        result = _parse_yt_entries(entries)
        assert len(result) == 1

    def test_em_dash_separator(self):
        from bot.handlers.charts import _parse_yt_entries
        entries = [{"title": "Artist \u2014 Song", "duration": 200, "id": "x"}]
        result = _parse_yt_entries(entries)
        assert result[0]["artist"] == "Artist"

    def test_en_dash_separator(self):
        from bot.handlers.charts import _parse_yt_entries
        entries = [{"title": "Artist \u2013 Song", "duration": 200, "id": "x"}]
        result = _parse_yt_entries(entries)
        assert result[0]["artist"] == "Artist"


# ── _extract_json_array ──────────────────────────────────────────────────

class TestExtractJsonArray:
    def test_basic_extraction(self):
        from bot.handlers.charts import _extract_json_array
        html = '{"tracks": [{"title": "A"}, {"title": "B"}]}'
        result = _extract_json_array(html, "tracks")
        assert len(result) == 2
        assert result[0]["title"] == "A"

    def test_no_key_found(self):
        from bot.handlers.charts import _extract_json_array
        html = '{"other": [1, 2, 3]}'
        result = _extract_json_array(html, "tracks")
        assert result == []

    def test_empty_html(self):
        from bot.handlers.charts import _extract_json_array
        result = _extract_json_array("", "tracks")
        assert result == []

    def test_escaped_json(self):
        from bot.handlers.charts import _extract_json_array
        html = '\\"tracks\\":[{\\"title\\":\\"A\\"}]'
        result = _extract_json_array(html, "tracks")
        assert len(result) == 1

    def test_nested_arrays(self):
        from bot.handlers.charts import _extract_json_array
        html = '{"tracks": [[1, 2], [3, 4]]}'
        result = _extract_json_array(html, "tracks")
        assert len(result) == 2


# ── _parse_rusradio_json ─────────────────────────────────────────────────

class TestParseRusradioJson:
    def test_valid_tracks(self):
        from bot.handlers.charts import _parse_rusradio_json
        data = {
            "tracks": [
                {"title": "Песня", "artist": "Артист", "duration": 200},
                {"title": "Другая", "artist": "Исполнитель", "duration": 180},
            ]
        }
        html = json.dumps(data)
        result = _parse_rusradio_json(html)
        assert len(result) == 2

    def test_skip_compilations(self):
        from bot.handlers.charts import _parse_rusradio_json
        data = {"tracks": [{"title": "Mix", "artist": "DJ", "duration": 600}]}
        html = json.dumps(data)
        result = _parse_rusradio_json(html)
        assert len(result) == 0

    def test_skip_missing_fields(self):
        from bot.handlers.charts import _parse_rusradio_json
        data = {"tracks": [{"title": "", "artist": "A"}]}
        html = json.dumps(data)
        result = _parse_rusradio_json(html)
        assert len(result) == 0

    def test_deduplication(self):
        from bot.handlers.charts import _parse_rusradio_json
        data = {"tracks": [
            {"title": "Song", "artist": "Artist"},
            {"title": "Song", "artist": "Artist"},  # duplicate
        ]}
        html = json.dumps(data)
        result = _parse_rusradio_json(html)
        assert len(result) == 1

    def test_no_tracks_key(self):
        from bot.handlers.charts import _parse_rusradio_json
        html = '{"other": "data"}'
        result = _parse_rusradio_json(html)
        assert result == []


# ── ChartCb / ChartDl callback data ─────────────────────────────────────

class TestCallbackData:
    def test_chart_cb_pack(self):
        from bot.handlers.charts import ChartCb
        cb = ChartCb(src="shazam", p=0)
        packed = cb.pack()
        unpacked = ChartCb.unpack(packed)
        assert unpacked.src == "shazam"
        assert unpacked.p == 0

    def test_chart_dl_pack(self):
        from bot.handlers.charts import ChartDl
        cb = ChartDl(sid="abc", i=3)
        packed = cb.pack()
        unpacked = ChartDl.unpack(packed)
        assert unpacked.sid == "abc"
        assert unpacked.i == 3


# ── Constants ────────────────────────────────────────────────────────────

class TestConstants:
    def test_per_page(self):
        from bot.handlers.charts import _PER_PAGE
        assert _PER_PAGE == 5

    def test_chart_ttl(self):
        from bot.handlers.charts import _CHART_TTL
        assert _CHART_TTL == 6 * 3600
