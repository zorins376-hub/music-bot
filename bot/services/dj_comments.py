"""
dj_comments.py — Voice AI DJ comment templates.

Generates human-like DJ phrases between tracks in Daily Mix.
"""
import random
import logging

logger = logging.getLogger(__name__)

# ── Comment templates per language ─────────────────────────────────────────
_TEMPLATES = {
    "ru": {
        "intro": [
            "Привет! Это BLACK ROOM Radio. У меня для тебя отличный микс.",
            "На связи BLACK ROOM. Сегодняшний микс подобран специально для тебя.",
            "Добро пожаловать в BLACK ROOM. Устраивайся поудобнее, погнали!",
        ],
        "transition": [
            "А сейчас — {artist}, трек {title}.",
            "Продолжаем! {artist} с треком {title}.",
            "Следующий трек — {title} от {artist}. Слушай!",
            "Что-то особенное — {artist}, {title}.",
            "Не переключайся! {artist} — {title}.",
            "Летим дальше. {title}, {artist}.",
        ],
        "energy": [
            "Огонь! Слушай дальше.",
            "Вау, какой трек! Продолжаем.",
            "Это было круто. Следующий будет не хуже!",
        ],
        "outro": [
            "Это был твой Daily Mix в BLACK ROOM. До завтра!",
            "Микс закончился. Понравилось? Сохрани в плейлист!",
            "BLACK ROOM Radio. Слушай больше — рекомендации становятся лучше.",
        ],
    },
    "en": {
        "intro": [
            "Hey! This is BLACK ROOM Radio. I've got a great mix for you.",
            "BLACK ROOM here. Today's mix is picked just for you.",
            "Welcome to BLACK ROOM. Get comfortable, let's go!",
        ],
        "transition": [
            "Up next — {artist} with {title}.",
            "Let's keep going! {artist}, {title}.",
            "Next track — {title} by {artist}. Enjoy!",
            "Something special — {artist}, {title}.",
            "Don't go anywhere! {artist} — {title}.",
            "Moving on. {title}, {artist}.",
        ],
        "energy": [
            "Fire! Keep listening.",
            "Wow, what a track! Let's continue.",
            "That was amazing. The next one is even better!",
        ],
        "outro": [
            "That was your Daily Mix on BLACK ROOM. See you tomorrow!",
            "Mix complete. Liked it? Save it to a playlist!",
            "BLACK ROOM Radio. Listen more — recommendations get better.",
        ],
    },
}


def get_intro(lang: str = "ru") -> str:
    """Get a random intro DJ comment."""
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return random.choice(templates["intro"])


def get_transition(artist: str, title: str, lang: str = "ru") -> str:
    """Get a random transition comment for next track."""
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    template = random.choice(templates["transition"])
    return template.format(artist=artist, title=title)


def get_energy(lang: str = "ru") -> str:
    """Get a random energy/hype comment."""
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return random.choice(templates["energy"])


def get_outro(lang: str = "ru") -> str:
    """Get a random outro DJ comment."""
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return random.choice(templates["outro"])


async def generate_dj_voice(text: str, lang: str = "ru") -> bytes | None:
    """Generate a DJ voice clip for the given text."""
    from bot.services.tts_engine import synthesize
    return await synthesize(text, lang)
