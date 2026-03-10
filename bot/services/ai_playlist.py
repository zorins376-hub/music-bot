"""
ai_playlist.py — Prompt-to-Playlist: генерация плейлиста по текстовому описанию.

Два режима:
1. С OpenAI: GPT разбирает запрос → поисковые запросы → search_tracks
2. Без OpenAI: keyword extraction + умные запросы (fallback)
"""
import json
import logging
import re
from typing import Optional

from bot.config import settings
from bot.services.downloader import search_tracks

logger = logging.getLogger(__name__)

# Маппинг настроений → поисковые суффиксы
_MOOD_MAP = {
    "грустн": "sad slow",
    "весел": "happy upbeat",
    "энерги": "energetic workout",
    "спокойн": "calm chill",
    "романти": "romantic love",
    "ночн": "night deep",
    "утренн": "morning feel good",
    "летн": "summer vibes",
    "зимн": "winter cozy",
    "тренировк": "workout gym motivation",
    "дорог": "road trip driving",
    "вечеринк": "party dance",
    "relax": "relax ambient",
    "chill": "chill lofi",
    "party": "party dance club",
    "sad": "sad emotional",
    "happy": "happy upbeat",
    "workout": "workout motivation",
    "drive": "driving road trip",
    "sleep": "sleep ambient calm",
    "focus": "focus concentration study",
    "study": "study lofi focus",
}

# Жанровые ключевые слова
_GENRE_KEYWORDS = {
    "рок": "rock", "rock": "rock",
    "поп": "pop", "pop": "pop",
    "хип-хоп": "hip hop", "хипхоп": "hip hop", "hip hop": "hip hop", "rap": "rap", "рэп": "rap",
    "электро": "electronic", "electronic": "electronic", "edm": "edm",
    "джаз": "jazz", "jazz": "jazz",
    "классик": "classical", "classical": "classical",
    "r&b": "r&b", "rnb": "r&b", "рнб": "r&b",
    "lofi": "lofi", "lo-fi": "lofi", "лофи": "lofi",
    "металл": "metal", "metal": "metal",
    "панк": "punk", "punk": "punk",
    "регги": "reggae", "reggae": "reggae",
    "соул": "soul", "soul": "soul",
    "блюз": "blues", "blues": "blues",
    "кантри": "country", "country": "country",
    "латин": "latin", "latin": "latin",
    "техно": "techno", "techno": "techno",
    "хаус": "house", "house": "house",
    "транс": "trance", "trance": "trance",
    "drum and bass": "drum and bass", "dnb": "drum and bass",
    "инди": "indie", "indie": "indie",
}


async def _generate_queries_openai(prompt: str) -> list[str]:
    """Use OpenAI to extract search queries from natural language prompt."""
    try:
        from bot.services.http_session import get_session
        session = await get_session()

        system_msg = (
            "You are a music expert. The user describes what kind of playlist they want. "
            "Return a JSON array of 5-8 YouTube search queries that would find matching tracks. "
            "Each query should be 'artist - song' or 'genre mood keyword'. "
            "Return ONLY the JSON array, no other text."
        )

        async with session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.8,
                "max_tokens": 300,
            },
            timeout=15,
        ) as resp:
            if resp.status != 200:
                logger.warning("OpenAI API error: %d", resp.status)
                return []
            data = await resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Parse JSON array from response
            # Handle cases where GPT wraps in ```json ... ```
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*$", "", content)
            queries = json.loads(content)
            if isinstance(queries, list):
                return [str(q) for q in queries[:8]]
            return []
    except Exception as e:
        logger.warning("OpenAI query generation failed: %s", e)
        return []


def _generate_queries_fallback(prompt: str) -> list[str]:
    """Extract search queries from prompt using keyword matching (no LLM needed)."""
    prompt_lower = prompt.lower()
    queries: list[str] = []

    # Detect genre
    detected_genre: Optional[str] = None
    for keyword, genre_en in _GENRE_KEYWORDS.items():
        if keyword in prompt_lower:
            detected_genre = genre_en
            break

    # Detect mood
    detected_mood: Optional[str] = None
    for keyword, mood_suffix in _MOOD_MAP.items():
        if keyword in prompt_lower:
            detected_mood = mood_suffix
            break

    # Extract artist names (words after "как", "типа", "похож", "like", "similar")
    artist_patterns = [
        r"(?:как|типа|похож\w* на|в стиле|like|similar to)\s+([A-Za-zА-Яа-яёЁ0-9\s,&]+?)(?:\.|,\s*(?:но|и)|$)",
    ]
    mentioned_artists: list[str] = []
    for pattern in artist_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            raw = match.group(1).strip()
            # Split from commas or "и"/"and"
            parts = re.split(r",|\s+и\s+|\s+and\s+", raw)
            mentioned_artists.extend(p.strip() for p in parts if p.strip())

    # Build queries
    if mentioned_artists:
        for artist in mentioned_artists[:3]:
            q = f"{artist} best songs"
            if detected_mood:
                q = f"{artist} {detected_mood}"
            queries.append(q)

    if detected_genre and detected_mood:
        queries.append(f"{detected_genre} {detected_mood} mix")
        queries.append(f"best {detected_genre} {detected_mood}")
    elif detected_genre:
        queries.append(f"{detected_genre} top songs")
        queries.append(f"best {detected_genre} mix 2025")
        queries.append(f"{detected_genre} playlist")
    elif detected_mood:
        queries.append(f"{detected_mood} music mix")
        queries.append(f"{detected_mood} playlist 2025")

    # If nothing detected, use the raw prompt as search
    if not queries:
        # Clean up common filler words
        cleaned = re.sub(
            r"\b(сделай|собери|создай|плейлист|playlist|для|на|с|и|a|the|make|create|me|with)\b",
            " ", prompt_lower,
        )
        cleaned = " ".join(cleaned.split())
        if cleaned:
            queries.append(f"{cleaned} music")
            queries.append(f"{cleaned} playlist")

    return queries[:6]


async def generate_ai_playlist(
    prompt: str, max_tracks: int = 10
) -> list[dict]:
    """Generate a playlist from a natural language prompt.

    Returns list of track dicts compatible with search_tracks output.
    """
    # Try OpenAI first if key is configured
    queries: list[str] = []
    if settings.OPENAI_API_KEY:
        queries = await _generate_queries_openai(prompt)

    # Fallback to keyword extraction
    if not queries:
        queries = _generate_queries_fallback(prompt)

    if not queries:
        return []

    # Search for tracks using generated queries
    seen_ids: set[str] = set()
    tracks: list[dict] = []

    for query in queries:
        if len(tracks) >= max_tracks:
            break
        try:
            results = await search_tracks(query, max_results=3, source="youtube")
            for tr in results:
                vid = tr.get("video_id", "")
                if vid and vid not in seen_ids:
                    seen_ids.add(vid)
                    tracks.append(tr)
                    if len(tracks) >= max_tracks:
                        break
        except Exception as e:
            logger.debug("Search failed for query '%s': %s", query, e)
            continue

    return tracks
