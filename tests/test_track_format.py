"""Tests for clean track display metadata."""
import pytest


class TestCleanTitle:
    def test_official_video(self):
        from bot.services.track_format import clean_title

        assert clean_title("Song Name (Official Video)") == "Song Name"

    def test_remaster(self):
        from bot.services.track_format import clean_title

        assert clean_title("Track (Remastered 2021)") == "Track"

    def test_slowed_reverb(self):
        from bot.services.track_format import clean_title

        assert clean_title("Hit (slowed+reverb)") == "Hit"

    def test_clip_suffix(self):
        from bot.services.track_format import clean_title

        assert clean_title("B O S S / Жаны клип") == "B O S S"

    def test_mp3_extension(self):
        from bot.services.track_format import clean_title

        assert clean_title("Song.mp3") == "Song"


class TestFormatTrackDisplay:
    def test_strips_topic_suffix_from_artist(self):
        from bot.services.track_format import format_track_display

        artist, title = format_track_display("MACAN - Topic", "MACAN — L")
        assert artist == "MACAN"
        assert title == "L"

    def test_dedupes_artist_in_title(self):
        from bot.services.track_format import format_track_display

        artist, title = format_track_display("MATRANG", "MATRANG — Руки на руке")
        assert artist == "MATRANG"
        assert title == "Руки на руке"

    def test_audio_tag_kwargs_from_info(self):
        from bot.services.track_format import audio_tag_kwargs_from_info

        kw = audio_tag_kwargs_from_info(
            {"uploader": "Mc Amir - Topic", "title": "B O S S / Жаны клип"}
        )
        assert kw["performer"] == "Mc Amir"
        assert kw["title"] == "B O S S"


class TestParseArtistTitle:
    def test_dash_separator(self):
        from bot.services.track_format import parse_artist_title

        artist, title = parse_artist_title("Artist - Song (Official Video)", "Uploader")
        assert artist == "Artist"
        assert title == "Song"
