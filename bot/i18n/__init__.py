import json
from functools import lru_cache
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent
_SUPPORTED = {"ru", "kg", "en"}


@lru_cache(maxsize=None)
def _load(lang: str) -> dict:
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = _LOCALES_DIR / "ru.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def t(lang: str, key: str, **kwargs: object) -> str:
    if lang not in _SUPPORTED:
        lang = "ru"
    text = _load(lang).get(key, key)
    return text.format(**kwargs) if kwargs else text
