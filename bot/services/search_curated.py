"""Curated search aliases + known track IDs for queries Yandex search misses."""
from __future__ import annotations

import re

_QUERY_WORD_TYPOS: dict[str, str] = {
    "гододная": "голодная",
    "партной": "портной",
    "хоми": "homie",
    "тогибадзе": "тотибадзе",
    "алмата": "almaty",
    "almatinka": "almaty",
    "nightmer": "nightmare",
    "porusan": "l",
    "порусan": "l",
    "порusan": "l",
    "purosangue": "l",
}

QUERY_SEARCH_ALIASES: dict[str, list[str]] = {
    "кока лова": ["Koka Lova", "koka lova", "Jax 02.14 Koka Lova", "Jax Koka Lova"],
    "лова кока": ["Koka Lova", "koka lova", "Jax 02.14 Koka Lova"],
    "koka lova": ["Koka Lova", "Jax 02.14 Koka Lova", "Jax Koka Lova"],
    "скриптонит вечеринка": ["Скриптонит Вечеринка"],
    "скриптонит это моя вечеринка": ["Скриптонит Вечеринка", "Scriptonite Vecherinka"],
    "я теперь твоё воспоминанье": ["NYUSHA Воспоминание", "Нюша Воспоминание"],
    "104 приезжай": ["M()eSTRo Приезжай"],
    "дай нам мам кокаина": ["Alesya Anis Кокаина", "HOMIE Кокаин"],
    "хоми кокаин": ["Alesya Anis Кокаина"],
    "матранг рука": ["MATRANG Руки на руке"],
    "матранг и муся тогибадзе": ["MATRANG Musia Totibadze Мимо ветра"],
    "мимо ветра": ["MATRANG Мимо ветра"],
    "асха принц су": ["V $ X V PRiNCE Су"],
    "асха принц голодная собака": ["V $ X V PRiNCE Голодная собака"],
    "асха принц гододная собака": ["V $ X V PRiNCE Голодная собака"],
    "леонид партной": ["Леонид Портной"],
    "доедешь пиши каспийский груз": ["Каспийский Груз Доедешь пиши"],
    "улукманапо кроко": ["Ulukmanapo Crocko Laco"],
    "давай мы прилетаем": ["HammAli Navai Прятки"],
    "давай мы полетаем": ["HammAli Navai Прятки"],
    "клава кока niletto краш": ["Клава Кока NILETTO Краш"],
    "lucaveros алмата": ["LUCAVEROS Almaty"],
    "lucaveros almatinka": ["LUCAVEROS Almaty"],
    "лукаверос алматы": ["LUCAVEROS Almaty"],
    "любит небо": ["Loc-Dog OG Buda Любит Небо"],
    "кружки мне пожалуйста": ["The Пауки Кружки наливай"],
    "гонк конг": ["UNIK Гонк-Конг"],
    "бурито ветром стать": ["Burito NAiTA Ветром стать"],
    "гайтана шоколад": ["Gaitana Кто я для тебя"],
    "макан порусан": ["MACAN L"],
    "линда мара кара": ["Линда Цепи и кольца"],
    "neleto все решено": ["Elvira T Все решено"],
    "фогель": ["ODURACHEN ФОГЕЛЬ Виноват"],
    "vairo nightmer": ["Vairo Nightmare"],
    "vairo nightmare": ["Vairo Nightmare"],
    "vairo scrab": ["Vairo Scarab"],
    "vairo": ["Vairo Nubxs"],
    "кайфуем каспийский груз": ["Sh4dowVlad Каспийский груз"],
}

def _track(vid: int, title: str, uploader: str) -> dict:
    return {
        "video_id": f"ym_{vid}",
        "ym_track_id": vid,
        "title": title,
        "uploader": uploader,
        "source": "yandex",
    }


CURATED_YM_TRACKS: dict[int, dict] = {
    48592103: _track(48592103, "Вечеринка", "Скриптонит"),
    114644167: _track(114644167, "Koka Lova", "Jax (02.14), Nel (02.14)"),
    78269648: _track(78269648, "Руки на руке", "MATRANG"),
    28098264: _track(28098264, "Воспоминание", "NYUSHA"),
    53357548: _track(53357548, "Приезжай", "M()eSTRo"),
    72966742: _track(72966742, "Кокаина", "Alesya Anis, LEO.K"),
    106155632: _track(106155632, "Су", "V $ X V PRiNCE, De Lacure"),
    113906634: _track(113906634, "Голодная собака", "V $ X V PRiNCE"),
    32882081: _track(32882081, "Кто тебя создал такую", "Леонид Портной"),
    75060625: _track(75060625, "Доедешь — пиши", "Каспийский Груз"),
    60086085: _track(60086085, "Crocko Laco", "Ulukmanapo"),
    89970732: _track(89970732, "Мимо ветра", "MATRANG, Musia Totibadze"),
    66869588: _track(66869588, "Краш", "Клава Кока, NILETTO"),
    148853444: _track(148853444, "Almaty", "LUCAVEROS"),
    144984783: _track(144984783, "Любит Небо", "Loc-Dog, OG Buda"),
    94826569: _track(94826569, "Кружки наливай", "The Пауки"),
    94531291: _track(94531291, "Гонк-Конг", "UNIK"),
    78598888: _track(78598888, "Ветром стать", "Burito, NAiTA"),
    145724696: _track(145724696, "Кто я для тебя", "Gaitana"),
    138207754: _track(138207754, "L", "MACAN"),
    54798445: _track(54798445, "Прятки", "HammAli & Navai"),
    50226457: _track(50226457, "Цепи и кольца", "Линда"),
    113353811: _track(113353811, "Мерседес", "KIRLIR"),
    141752393: _track(141752393, "Ворон", "Wicsur"),
    51325167: _track(51325167, "Nightmare", "Vairo"),
    136820137: _track(136820137, "Виноват", "ODURACHEN, ФОГЕЛЬ"),
    117268328: _track(117268328, "Аккула", "Ulukmanapo"),
    3250228: _track(3250228, "Всё решено", "Elvira T"),
    147769932: _track(147769932, "Nubxs", "Vairo"),
    132167879: _track(132167879, "Каспийский груз", "Sh4dowVlad"),
    46371870: _track(46371870, "Scarab", "Vairo"),
}

CURATED_QUERY_PINS: dict[str, int] = {
    "кока лова": 114644167,
    "лова кока": 114644167,
    "koka lova": 114644167,
    "матранг рука": 78269648,
    "скриптонит это моя вечеринка": 48592103,
    "скриптонит вечеринка": 48592103,
    "я теперь твоё воспоминанье": 28098264,
    "104 приезжай": 53357548,
    "дай нам мам кокаина": 72966742,
    "хоми кокаин": 72966742,
    "асха принц су": 106155632,
    "асха принц голодная собака": 113906634,
    "асха принц гододная собака": 113906634,
    "леонид партной": 32882081,
    "доедешь пиши каспийский груз": 75060625,
    "улукманапо кроко": 60086085,
    "улукманapo": 117268328,
    "давай мы прилетаем": 54798445,
    "давай мы полетаем": 54798445,
    "матранг и муся тогибадзе": 89970732,
    "мimo vetра": 89970732,
    "мимо ветра": 89970732,
    "клава кока niletto краш": 66869588,
    "lucaveros алмата": 148853444,
    "lucaveros almatinka": 148853444,
    "лукаверос алматы": 148853444,
    "любит небо": 144984783,
    "кружки мне пожалуйста": 94826569,
    "гонк конг": 94531291,
    "бурито ветром стать": 78598888,
    "гайтана шоколад": 145724696,
    "макан порусан": 138207754,
    "макан порусan": 138207754,
    "макан l": 138207754,
    "линда мара кара": 50226457,
    "neleto все решено": 3250228,
    "фогель": 136820137,
    "vairo nightmer": 51325167,
    "vairo nightmare": 51325167,
    "vairo scrab": 46371870,
    "vairo": 147769932,
    "кайфуем каспийский груз": 132167879,
    "мерседес": 113353811,
    "ворон": 141752393,
}


def _normalize_query_key(query: str) -> str:
    from bot.services.search_engine import normalize_query

    norm = normalize_query(query)
    norm = re.sub(r"[\u2013\u2014\u2212\-–—]+", " ", norm)
    norm = re.sub(r"[&+]", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def _query_norm_variants(query: str) -> list[str]:
    norm = _normalize_query_key(query)
    if not norm:
        return []
    variants = [norm]
    fixed = " ".join(_QUERY_WORD_TYPOS.get(w, w) for w in norm.split())
    if fixed != norm:
        variants.append(fixed)
    return variants


def query_search_aliases(query: str) -> list[str]:
    out: list[str] = []
    for norm in _query_norm_variants(query):
        for alias in QUERY_SEARCH_ALIASES.get(norm, []):
            if alias not in out:
                out.append(alias)
    return out


def curated_track_for_query(query: str) -> dict | None:
    for norm in _query_norm_variants(query):
        ym_id = CURATED_QUERY_PINS.get(norm)
        if ym_id:
            base = CURATED_YM_TRACKS.get(ym_id)
            if base:
                return dict(base)
    return None


def inject_curated_track(results: list[dict], query: str) -> list[dict]:
    curated = curated_track_for_query(query)
    if not curated:
        return results
    curated = dict(curated)
    curated["_provider_pos"] = 0
    curated["_curated"] = True
    curated["_hint_bonus"] = 3.0
    vid = curated.get("video_id")
    if vid:
        results = [r for r in results if r.get("video_id") != vid]
    return [curated] + results


def is_junk_search_query(query: str) -> bool:
    from bot.services.search_engine import normalize_query

    raw = (query or "").strip()
    # Music links (often long with utm/ref params) are valid search input
    if raw.startswith("http://") or raw.startswith("https://"):
        low = raw.lower()
        if any(
            marker in low
            for marker in (
                "music.yandex.",
                "open.spotify.com",
                "spotify.link",
                "youtube.com",
                "youtu.be",
                "soundcloud.com",
            )
        ):
            return False
    if raw.startswith("@") and " " not in raw:
        return True
    norm = normalize_query(query)
    if not norm or len(norm) < 2:
        return True
    if len(norm.split()) == 1 and ("bot" in norm or norm.endswith("_bot")):
        return True
    if len(norm) > 90:
        return True
    return False
