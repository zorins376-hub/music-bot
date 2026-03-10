"""
dj_comments.py — Voice AI DJ comment templates.

Generates human-like DJ phrases between tracks in Daily Mix.
50+ templates per language with personalization ({name}, time-of-day).
"""
import random
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _time_of_day(lang: str = "ru") -> str:
    """Return a time-of-day greeting based on UTC hour."""
    h = datetime.now(timezone.utc).hour
    if lang == "en":
        if 5 <= h < 12:
            return "morning"
        elif 12 <= h < 18:
            return "afternoon"
        elif 18 <= h < 23:
            return "evening"
        return "night"
    # ru / kg
    if 5 <= h < 12:
        return "утро"
    elif 12 <= h < 18:
        return "день"
    elif 18 <= h < 23:
        return "вечер"
    return "ночь"


def _time_greeting(lang: str = "ru") -> str:
    """Full greeting phrase based on time of day."""
    tod = _time_of_day(lang)
    if lang == "en":
        return {"morning": "Good morning", "afternoon": "Good afternoon",
                "evening": "Good evening", "night": "Late night vibes"}[tod]
    return {"утро": "Доброе утро", "день": "Добрый день",
            "вечер": "Добрый вечер", "ночь": "Ночной вайб"}[tod]


# ── Comment templates per language (50+ total) ────────────────────────────
_TEMPLATES = {
    "ru": {
        "intro": [
            "Привет! Это BLACK ROOM Radio. У меня для тебя отличный микс.",
            "На связи BLACK ROOM. Сегодняшний микс подобран специально для тебя.",
            "Добро пожаловать в BLACK ROOM. Устраивайся поудобнее, погнали!",
            "{greeting}! Это BLACK ROOM Radio, и у нас потрясающий сет.",
            "{greeting}, {name}! Твой персональный микс уже готов.",
            "Эй, {name}! BLACK ROOM на связи. Поехали!",
            "Запускаю твой Daily Mix, {name}. Приятного прослушивания!",
            "{greeting}! Включаю лучшую музыку для тебя.",
        ],
        "transition": [
            "А сейчас — {artist}, трек {title}.",
            "Продолжаем! {artist} с треком {title}.",
            "Следующий трек — {title} от {artist}. Слушай!",
            "Что-то особенное — {artist}, {title}.",
            "Не переключайся! {artist} — {title}.",
            "Летим дальше. {title}, {artist}.",
            "Держи! {artist} — {title}. Огонь!",
            "Переключаемся на {artist}. Трек — {title}.",
            "Без остановки. {title} от {artist}.",
            "Давай ещё! {artist}, {title} — для тебя.",
            "Сейчас будет жарко. {artist} — {title}!",
            "Топ трек! {title}, {artist}. Наслаждайся.",
            "А вот и {artist}! Слушаем {title}.",
            "Ловите вайб! {artist} — {title}.",
        ],
        "energy": [
            "Огонь! Слушай дальше.",
            "Вау, какой трек! Продолжаем.",
            "Это было круто. Следующий будет не хуже!",
            "Мощно! Не останавливаемся.",
            "Кайф! Микс разогревается.",
            "Ну как тебе? Дальше будет ещё лучше!",
            "Ты чувствуешь этот вайб? Продолжаем!",
            "Атмосфера на максимуме!",
        ],
        "outro": [
            "Это был твой Daily Mix в BLACK ROOM. До завтра!",
            "Микс закончился. Понравилось? Сохрани в плейлист!",
            "BLACK ROOM Radio. Слушай больше — рекомендации становятся лучше.",
            "Микс окончен, {name}! Увидимся завтра с новой подборкой.",
            "Спасибо за прослушивание, {name}. Ставь ❤️ любимым трекам!",
            "BLACK ROOM прощается! До скорого, {name}.",
            "Конец микса. Заходи завтра — будет свежая музыка!",
        ],
        "personal": [
            "{name}, этот трек специально для тебя!",
            "Думаю, тебе зайдёт, {name}.",
            "{name}, послушай — мне кажется, это твоё!",
        ],
    },
    "en": {
        "intro": [
            "Hey! This is BLACK ROOM Radio. I've got a great mix for you.",
            "BLACK ROOM here. Today's mix is picked just for you.",
            "Welcome to BLACK ROOM. Get comfortable, let's go!",
            "{greeting}! BLACK ROOM Radio bringing you the best vibes.",
            "{greeting}, {name}! Your personal mix is ready.",
            "Hey {name}! BLACK ROOM is on. Let's roll!",
            "Starting your Daily Mix, {name}. Enjoy the ride!",
            "{greeting}! Time for some amazing music.",
        ],
        "transition": [
            "Up next — {artist} with {title}.",
            "Let's keep going! {artist}, {title}.",
            "Next track — {title} by {artist}. Enjoy!",
            "Something special — {artist}, {title}.",
            "Don't go anywhere! {artist} — {title}.",
            "Moving on. {title}, {artist}.",
            "Here we go! {artist} — {title}. Fire!",
            "Switching to {artist}. Track — {title}.",
            "Non stop. {title} by {artist}.",
            "More vibes! {artist}, {title} — for you.",
            "Things are heating up. {artist} — {title}!",
            "Top track alert! {title}, {artist}. Enjoy.",
            "And here's {artist}! Listen to {title}.",
            "Catch the vibe! {artist} — {title}.",
        ],
        "energy": [
            "Fire! Keep listening.",
            "Wow, what a track! Let's continue.",
            "That was amazing. The next one is even better!",
            "Powerful! Don't stop now.",
            "Vibe check! The mix is heating up.",
            "How was that? It only gets better from here!",
            "Can you feel the vibe? Let's go!",
            "Atmosphere at maximum!",
        ],
        "outro": [
            "That was your Daily Mix on BLACK ROOM. See you tomorrow!",
            "Mix complete. Liked it? Save it to a playlist!",
            "BLACK ROOM Radio. Listen more — recommendations get better.",
            "Mix is over, {name}! See you tomorrow with a fresh selection.",
            "Thanks for listening, {name}. Don't forget to ❤️ your favorites!",
            "BLACK ROOM signing off! See you soon, {name}.",
            "That's a wrap. Come back tomorrow for fresh tunes!",
        ],
        "personal": [
            "{name}, this track is specially for you!",
            "I think you'll love this one, {name}.",
            "{name}, listen — I feel like this is your vibe!",
        ],
    },
}


def _fill(template: str, name: str = "", lang: str = "ru", **kwargs) -> str:
    """Fill template placeholders safely."""
    greeting = _time_greeting(lang)
    return template.format(
        name=name or "друг" if lang != "en" else name or "friend",
        greeting=greeting,
        **kwargs,
    )


def get_intro(lang: str = "ru", name: str = "") -> str:
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return _fill(random.choice(templates["intro"]), name=name, lang=lang)


def get_transition(artist: str, title: str, lang: str = "ru", name: str = "") -> str:
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return _fill(random.choice(templates["transition"]), name=name, lang=lang,
                 artist=artist, title=title)


def get_energy(lang: str = "ru", name: str = "") -> str:
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return _fill(random.choice(templates["energy"]), name=name, lang=lang)


def get_outro(lang: str = "ru", name: str = "") -> str:
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return _fill(random.choice(templates["outro"]), name=name, lang=lang)


def get_personal(lang: str = "ru", name: str = "") -> str:
    """Get a personalized comment mentioning the user by name."""
    templates = _TEMPLATES.get(lang, _TEMPLATES["ru"])
    return _fill(random.choice(templates["personal"]), name=name, lang=lang)


async def generate_dj_voice(text: str, lang: str = "ru") -> bytes | None:
    """Generate a DJ voice clip for the given text."""
    from bot.services.tts_engine import synthesize
    return await synthesize(text, lang)
