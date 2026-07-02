from bot.services.track_flair import is_koka_lova_jax_track, track_extra_caption_lines


class TestKokaLovaFlair:
    def test_detects_ym_video_id(self):
        assert is_koka_lova_jax_track({"video_id": "ym_114644167"})

    def test_detects_title_and_artist(self):
        assert is_koka_lova_jax_track({
            "title": "Koka Lova",
            "uploader": "Jax (02.14), Nel (02.14)",
        })

    def test_rejects_unrelated_track(self):
        assert not is_koka_lova_jax_track({
            "title": "Коко Джамбо",
            "uploader": "ГАМОРА",
        })

    def test_caption_includes_teni_flair(self):
        from bot.handlers.search import _track_caption

        info = {
            "duration_fmt": "2:14",
            "upload_year": 2023,
            "title": "Koka Lova",
            "uploader": "Jax (02.14), Nel (02.14)",
            "video_id": "ym_114644167",
        }
        caption = _track_caption("ru", info, 192)
        assert "Тени" in caption
        assert "B L A C K R O O M" in caption
        assert "🜏" in caption

    def test_flair_line_ru(self):
        line = track_extra_caption_lines("ru", {"video_id": "ym_114644167"})
        assert line and "тени" in line.lower()
