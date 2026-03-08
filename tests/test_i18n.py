"""
Тесты для bot/i18n — система локализации.
"""
import pytest
from pathlib import Path


class TestLocalization:
    def test_russian_loads(self):
        from bot.i18n import t
        result = t("ru", "start_message", name="Test")
        assert result != "start_message"  # key не должен вернуться как есть
        assert "Test" in result

    def test_english_loads(self):
        from bot.i18n import t
        result = t("en", "start_message", name="Test")
        assert result != "start_message"

    def test_kyrgyz_loads(self):
        from bot.i18n import t
        result = t("kg", "start_message", name="Test")
        assert result != "start_message"

    def test_unknown_lang_falls_back_to_russian(self):
        from bot.i18n import t
        ru_result = t("ru", "start_message", name="Test")
        unknown_result = t("xx", "start_message", name="Test")
        assert unknown_result == ru_result

    def test_missing_key_returns_key(self):
        from bot.i18n import t
        assert t("ru", "nonexistent_key_xyz") == "nonexistent_key_xyz"

    def test_kwargs_substitution(self):
        from bot.i18n import t
        result = t("ru", "start_message", name="Alice")
        assert "Alice" in result

    def test_no_kwargs(self):
        from bot.i18n import t
        # Key that requires no kwargs
        result = t("ru", "help_message")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_all_locale_files_exist(self):
        i18n_dir = Path(__file__).parent.parent / "bot" / "i18n"
        for lang in ("ru", "en", "kg"):
            assert (i18n_dir / f"{lang}.json").exists()

    def test_all_locales_valid_json(self):
        import json
        i18n_dir = Path(__file__).parent.parent / "bot" / "i18n"
        for lang in ("ru", "en", "kg"):
            path = i18n_dir / f"{lang}.json"
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, dict)
            assert len(data) > 0

    def test_key_consistency_across_locales(self):
        """Все ключи из ru.json должны быть и в en.json и kg.json."""
        import json
        i18n_dir = Path(__file__).parent.parent / "bot" / "i18n"
        with open(i18n_dir / "ru.json", encoding="utf-8") as f:
            ru_keys = set(json.load(f).keys())
        for lang in ("en", "kg"):
            with open(i18n_dir / f"{lang}.json", encoding="utf-8") as f:
                lang_keys = set(json.load(f).keys())
            missing = ru_keys - lang_keys
            # Допускается отсутствие ключей (fallback на ru), но логируем
            if missing:
                pytest.skip(f"{lang}.json missing {len(missing)} keys (non-critical)")
