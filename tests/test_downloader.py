"""
Тесты для bot/services/downloader.py — парсинг, очистка заголовков, утилиты.
"""
import pytest
from pathlib import Path
from unittest.mock import patch


class TestCleanTitle:
    def test_strips_official_video(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name (Official Video)") == "Song Name"

    def test_strips_official_audio(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name [Official Audio]") == "Song Name"

    def test_strips_music_video(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song (Music Video)") == "Song"

    def test_strips_lyrics_video(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name (Lyric Video)") == "Song Name"

    def test_strips_lyrics(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name (Lyrics)") == "Song Name"

    def test_strips_hd(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name [HD]") == "Song Name"

    def test_strips_4k(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name [4K]") == "Song Name"

    def test_strips_feat(self):
        from bot.services.downloader import _clean_title
        result = _clean_title("Song Name (feat. Artist)")
        assert "feat" not in result.lower()

    def test_strips_pipe_suffix(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name | Some Channel") == "Song Name"

    def test_strips_hash_tags(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name #music") == "Song Name"

    def test_strips_empty_parens(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name ()") == "Song Name"

    def test_strips_trailing_lyrics(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name lyrics") == "Song Name"

    def test_strips_trailing_audio(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Song Name audio") == "Song Name"

    def test_preserves_clean_title(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Imagine Dragons - Bones") == "Imagine Dragons - Bones"

    def test_normalizes_whitespace(self):
        from bot.services.downloader import _clean_title
        assert "  " not in _clean_title("Song   Name   (HD)")

    def test_strips_russian_keywords(self):
        from bot.services.downloader import _clean_title
        assert _clean_title("Песня (клип)") == "Песня"
        assert _clean_title("Песня (видеоклип)") == "Песня"

    def test_multiple_junk_items(self):
        from bot.services.downloader import _clean_title
        result = _clean_title("Song (Official Video) (Lyrics) | Channel #trending")
        assert "Official" not in result
        assert "Channel" not in result


class TestParseArtistTitle:
    def test_dash_separator(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Imagine Dragons - Bones", "SomeChannel")
        assert artist == "Imagine Dragons"
        assert title == "Bones"

    def test_em_dash_separator(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Artist — Title", "Channel")
        assert artist == "Artist"
        assert title == "Title"

    def test_en_dash_separator(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Artist – Title", "Channel")
        assert artist == "Artist"
        assert title == "Title"

    def test_fallback_to_uploader(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Just A Song Title", "Cool Channel")
        assert artist == "Cool Channel"
        assert title == "Just A Song Title"

    def test_strips_topic_from_uploader(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Just A Song", "Artist Name - Topic")
        assert artist == "Artist Name"

    def test_strips_tema_from_uploader(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Песня", "Исполнитель - Тема")
        assert artist == "Исполнитель"

    def test_strips_vevo(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Song Title", "ArtistVEVO")
        assert artist == "Artist"

    def test_cleans_junk_before_parsing(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Bones (Official Video) - Imagine Dragons", "Channel")
        # After cleaning: "Bones - Imagine Dragons"
        assert artist == "Bones"
        assert title == "Imagine Dragons"

    def test_empty_uploader_fallback(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Some Song", "")
        assert artist == "Unknown"

    def test_none_uploader_fallback(self):
        from bot.services.downloader import _parse_artist_title
        artist, title = _parse_artist_title("Some Song", None)
        assert artist == "Unknown"


class TestFmtDuration:
    def test_seconds_less_than_minute(self):
        from bot.services.downloader import _fmt_duration
        assert _fmt_duration(45) == "0:45"

    def test_exact_minute(self):
        from bot.services.downloader import _fmt_duration
        assert _fmt_duration(60) == "1:00"

    def test_minutes_and_seconds(self):
        from bot.services.downloader import _fmt_duration
        assert _fmt_duration(195) == "3:15"

    def test_zero(self):
        from bot.services.downloader import _fmt_duration
        assert _fmt_duration(0) == "0:00"

    def test_long_duration(self):
        from bot.services.downloader import _fmt_duration
        assert _fmt_duration(600) == "10:00"

    def test_single_digit_seconds_padded(self):
        from bot.services.downloader import _fmt_duration
        assert _fmt_duration(65) == "1:05"


class TestExtractYear:
    def test_from_upload_date(self):
        from bot.services.downloader import _extract_year
        assert _extract_year({"upload_date": "20230515"}) == "2023"

    def test_from_release_date(self):
        from bot.services.downloader import _extract_year
        assert _extract_year({"release_date": "20210101"}) == "2021"

    def test_from_release_year(self):
        from bot.services.downloader import _extract_year
        assert _extract_year({"release_year": 2020}) == "2020"

    def test_no_data(self):
        from bot.services.downloader import _extract_year
        assert _extract_year({}) is None

    def test_empty_upload_date(self):
        from bot.services.downloader import _extract_year
        assert _extract_year({"upload_date": ""}) is None

    def test_upload_date_takes_priority(self):
        from bot.services.downloader import _extract_year
        result = _extract_year({"upload_date": "20230101", "release_year": 2020})
        assert result == "2023"


class TestIsSpotifyUrl:
    def test_valid_spotify_url(self):
        from bot.services.downloader import is_spotify_url
        assert is_spotify_url("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6") is True

    def test_http_url(self):
        from bot.services.downloader import is_spotify_url
        assert is_spotify_url("http://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6") is True

    def test_invalid_url(self):
        from bot.services.downloader import is_spotify_url
        assert is_spotify_url("https://youtube.com/watch?v=abc") is False

    def test_plain_text(self):
        from bot.services.downloader import is_spotify_url
        assert is_spotify_url("just some text") is False

    def test_empty_string(self):
        from bot.services.downloader import is_spotify_url
        assert is_spotify_url("") is False


class TestIsYoutubeUrl:
    def test_standard_url(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_short_url(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_mobile_url(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_music_url(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_url_with_extra_params(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s") is True

    def test_not_youtube(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("https://open.spotify.com/track/abc123") is False

    def test_plain_text(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("some random text") is False

    def test_empty(self):
        from bot.services.downloader import is_youtube_url
        assert is_youtube_url("") is False


class TestExtractYoutubeVideoId:
    def test_standard_url(self):
        from bot.services.downloader import extract_youtube_video_id
        assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        from bot.services.downloader import extract_youtube_video_id
        assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_mobile_url(self):
        from bot.services.downloader import extract_youtube_video_id
        assert extract_youtube_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_no_match(self):
        from bot.services.downloader import extract_youtube_video_id
        assert extract_youtube_video_id("just text") is None

    def test_url_in_message(self):
        from bot.services.downloader import extract_youtube_video_id
        assert extract_youtube_video_id("check this out https://youtu.be/dQw4w9WgXcQ nice song") == "dQw4w9WgXcQ"


class TestCleanupFile:
    def test_cleanup_existing_file(self, tmp_path):
        from bot.services.downloader import cleanup_file
        f = tmp_path / "test.mp3"
        f.write_bytes(b"data")
        cleanup_file(f)
        assert not f.exists()

    def test_cleanup_with_thumbnails(self, tmp_path):
        from bot.services.downloader import cleanup_file
        f = tmp_path / "test.mp3"
        f.write_bytes(b"data")
        thumb = tmp_path / "test.jpg"
        thumb.write_bytes(b"thumbnail")
        cleanup_file(f)
        assert not f.exists()
        assert not thumb.exists()

    def test_cleanup_nonexistent_file(self, tmp_path):
        from bot.services.downloader import cleanup_file
        f = tmp_path / "nonexistent.mp3"
        cleanup_file(f)  # Should not raise
