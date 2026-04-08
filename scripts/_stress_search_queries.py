#!/usr/bin/env python3
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

try:
    from rapidfuzz import fuzz as rf_fuzz
except Exception:
    rf_fuzz = None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.db import search_local_tracks
from bot.services.downloader import search_tracks
from bot.services.http_session import close_session
from bot.services.lyrics_provider import search_by_lyrics
from bot.services.search_engine import (
    _relevance_score,
    deduplicate_results,
    detect_script,
    normalize_query,
    parse_query,
    transliterate_cyr_to_lat,
    transliterate_lat_to_cyr,
)
from bot.services.speller import correct_query
from bot.services.yandex_provider import search_yandex


CONCURRENCY = int(os.getenv("STRESS_CONCURRENCY", "8"))
QUERY_LIMIT = int(os.getenv("STRESS_LIMIT", "1500"))
SEARCH_TIMEOUT = float(os.getenv("STRESS_TIMEOUT", "5"))
REPORT_PATH = ROOT / "logs" / "search_stress_report.json"
PROVIDER_LIMIT = 5
YOUTUBE_LIMIT = 5

RU_PREFIXES = ["", "найди ", "песня ", "включи ", "слушать ", "скачать "]
EN_PREFIXES = ["", "play ", "song ", "music ", "listen ", "find "]
MIXED_PREFIXES = ["", "найди ", "включи ", "песня ", "play ", "song "]

RU_SUFFIXES = ["", " пожалуйста", " щас"]
EN_SUFFIXES = ["", " please", " now"]
MIXED_SUFFIXES = ["", " пожалуйста", " please"]

SEEDS = [
    {
        "category": "ru_lyrics",
        "artist": "Кипелов",
        "title": "Я свободен",
        "phrase": "я свободен словно птица в небесах",
    },
    {
        "category": "ru_lyrics",
        "artist": "МакSим",
        "title": "Знаешь ли ты",
        "phrase": "вдоль ночных дорог шла босиком не жалея ног",
    },
    {
        "category": "ru_lyrics",
        "artist": "Ленинград",
        "title": "В Питере пить",
        "phrase": "в питере пить в питере пить",
    },
    {
        "category": "ru_lyrics",
        "artist": "Потап и Настя",
        "title": "Чумачечая весна",
        "phrase": "пришла и оторвала голову нам чумачечая весна",
    },
    {
        "category": "ru_lyrics",
        "artist": "Максим Фадеев",
        "title": "Нас бьют, мы летаем",
        "phrase": "нас бьют мы летаем от боли все выше",
    },
    {
        "category": "ru_lyrics",
        "artist": "Руки Вверх",
        "title": "18 мне уже",
        "phrase": "ты целуй меня везде восемнадцать мне уже",
    },
    {
        "category": "ru_lyrics",
        "artist": "Пропаганда",
        "title": "Яблоки ела",
        "phrase": "яй я яблоки ела",
    },
    {
        "category": "ru_lyrics",
        "artist": "Леонид Агутин",
        "title": "На сиреневой луне",
        "phrase": "на сиреневой луне там где тихо",
    },
    {
        "category": "ru_lyrics",
        "artist": "Звери",
        "title": "Районы-кварталы",
        "phrase": "районы кварталы жилые массивы",
    },
    {
        "category": "ru_lyrics",
        "artist": "Кино",
        "title": "Группа крови",
        "phrase": "группа крови на рукаве",
    },
    {
        "category": "ru_lyrics",
        "artist": "Иванушки International",
        "title": "Тополиный пух",
        "phrase": "тополиный пух жара июль",
    },
    {
        "category": "ru_lyrics",
        "artist": "ДДТ",
        "title": "Что такое осень",
        "phrase": "что такое осень это небо",
    },
    {
        "category": "en_lyrics",
        "artist": "Pink Floyd",
        "title": "Another Brick in the Wall",
        "phrase": "we dont need no education",
    },
    {
        "category": "en_lyrics",
        "artist": "Simon and Garfunkel",
        "title": "The Sound of Silence",
        "phrase": "hello darkness my old friend",
    },
    {
        "category": "en_lyrics",
        "artist": "Queen",
        "title": "Bohemian Rhapsody",
        "phrase": "mama just killed a man",
    },
    {
        "category": "en_lyrics",
        "artist": "Queen",
        "title": "Bohemian Rhapsody",
        "phrase": "is this the real life is this just fantasy",
    },
    {
        "category": "en_lyrics",
        "artist": "Whitney Houston",
        "title": "I Will Always Love You",
        "phrase": "and i will always love you",
    },
    {
        "category": "en_lyrics",
        "artist": "The Beatles",
        "title": "Let It Be",
        "phrase": "let it be whisper words of wisdom",
    },
    {
        "category": "en_lyrics",
        "artist": "Nirvana",
        "title": "Smells Like Teen Spirit",
        "phrase": "here we are now entertain us",
    },
    {
        "category": "en_lyrics",
        "artist": "Baha Men",
        "title": "Who Let the Dogs Out",
        "phrase": "who let the dogs out",
    },
    {
        "category": "en_lyrics",
        "artist": "Toto",
        "title": "Africa",
        "phrase": "i bless the rains down in africa",
    },
    {
        "category": "en_lyrics",
        "artist": "Adele",
        "title": "Hello",
        "phrase": "hello from the other side",
    },
    {
        "category": "en_lyrics",
        "artist": "Linkin Park",
        "title": "Numb",
        "phrase": "ive become so numb i cant feel you there",
    },
    {
        "category": "en_lyrics",
        "artist": "Michael Jackson",
        "title": "Billie Jean",
        "phrase": "billie jean is not my lover",
    },
    {
        "category": "en_lyrics",
        "artist": "Eagles",
        "title": "Hotel California",
        "phrase": "welcome to the hotel california",
    },
    {
        "category": "en_lyrics",
        "artist": "Europe",
        "title": "The Final Countdown",
        "phrase": "its the final countdown",
    },
    {
        "category": "translit_lyrics",
        "artist": "Eiffel 65",
        "title": "Blue",
        "phrase": "айм блю дабуди дабудай",
        "aliases": ["eiffel 65 blue", "blue da ba dee"],
    },
    {
        "category": "translit_lyrics",
        "artist": "Nirvana",
        "title": "Smells Like Teen Spirit",
        "phrase": "смэлс лайк тин спирит",
    },
    {
        "category": "translit_lyrics",
        "artist": "Michael Jackson",
        "title": "Billie Jean",
        "phrase": "билли джин из нот май лавер",
    },
    {
        "category": "translit_lyrics",
        "artist": "Queen",
        "title": "The Show Must Go On",
        "phrase": "шоу маст гоу он",
    },
    {
        "category": "translit_lyrics",
        "artist": "Whitney Houston",
        "title": "I Will Always Love You",
        "phrase": "ай вил олвейс лав ю",
    },
    {
        "category": "translit_lyrics",
        "artist": "The Beatles",
        "title": "Let It Be",
        "phrase": "лет ит би",
    },
    {
        "category": "translit_lyrics",
        "artist": "Baha Men",
        "title": "Who Let the Dogs Out",
        "phrase": "ху лет зе догс аут",
    },
    {
        "category": "translit_lyrics",
        "artist": "Toto",
        "title": "Africa",
        "phrase": "ай блесс зе рейнс даун ин африка",
    },
    {
        "category": "translit_lyrics",
        "artist": "Adele",
        "title": "Hello",
        "phrase": "хелло фром зе азер сайд",
    },
    {
        "category": "translit_lyrics",
        "artist": "Linkin Park",
        "title": "Numb",
        "phrase": "айв биком со намб",
    },
    {
        "category": "translit_lyrics",
        "artist": "Metallica",
        "title": "Nothing Else Matters",
        "phrase": "насинг элс мэттерс",
    },
    {
        "category": "translit_lyrics",
        "artist": "Scorpions",
        "title": "Wind of Change",
        "phrase": "винд оф чейндж",
    },
]


def tokenize(text: str) -> list[str]:
    return [token for token in normalize_query(text).split() if token]


def make_windows(phrase: str, min_size: int = 3, max_size: int = 5) -> list[str]:
    words = tokenize(phrase)
    if not words:
        return []
    windows: list[str] = []
    upper = min(len(words), max_size)
    for size in range(min_size, upper + 1):
        for start in range(0, len(words) - size + 1):
            windows.append(" ".join(words[start:start + size]))
    windows.append(" ".join(words))
    seen: set[str] = set()
    unique: list[str] = []
    for item in windows:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def make_typo(text: str) -> str:
    words = text.split()
    if not words:
        return text
    longest_idx = max(range(len(words)), key=lambda idx: len(words[idx]))
    word = words[longest_idx]
    if len(word) < 5:
        return text
    cut = len(word) // 2
    mutated = word[:cut] + word[cut + 1:]
    words[longest_idx] = mutated
    return " ".join(words)


def choose_wrappers(category: str) -> tuple[list[str], list[str]]:
    if category == "ru_lyrics":
        return RU_PREFIXES, RU_SUFFIXES
    if category == "en_lyrics":
        return EN_PREFIXES, EN_SUFFIXES
    return MIXED_PREFIXES, MIXED_SUFFIXES


def build_seed_queries(seed: dict) -> list[dict]:
    generated: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    min_window = 3 if seed["category"] == "translit_lyrics" else 4
    fragments = make_windows(seed["phrase"], min_size=min_window)
    prefixes, suffixes = choose_wrappers(seed["category"])
    aliases = [f"{seed['artist']} {seed['title']}", seed["title"]] + seed.get("aliases", [])

    for fragment in fragments:
        for prefix in prefixes:
            for suffix in suffixes:
                query = f"{prefix}{fragment}{suffix}".strip()
                key = (query, seed["artist"], seed["title"])
                if key in seen:
                    continue
                seen.add(key)
                generated.append(
                    {
                        "query": query,
                        "category": seed["category"],
                        "expected_artist": seed["artist"],
                        "expected_title": seed["title"],
                        "expected_aliases": aliases,
                        "expected_phrase": seed["phrase"],
                        "query_word_count": len(tokenize(query)),
                        "variant": "window",
                    }
                )

        typo = make_typo(fragment)
        if typo != fragment:
            typo_query = f"{prefixes[min(1, len(prefixes) - 1)]}{typo}{suffixes[min(1, len(suffixes) - 1)]}".strip()
            key = (typo_query, seed["artist"], seed["title"])
            if key not in seen:
                seen.add(key)
                generated.append(
                    {
                        "query": typo_query,
                        "category": seed["category"],
                        "expected_artist": seed["artist"],
                        "expected_title": seed["title"],
                        "expected_aliases": aliases,
                        "expected_phrase": seed["phrase"],
                        "query_word_count": len(tokenize(typo_query)),
                        "variant": "typo",
                    }
                )

    artist_title_query = f"{seed['artist']} {seed['title']}"
    key = (artist_title_query, seed["artist"], seed["title"])
    if key not in seen:
        seen.add(key)
        generated.append(
            {
                "query": artist_title_query,
                "category": seed["category"],
                "expected_artist": seed["artist"],
                "expected_title": seed["title"],
                "expected_aliases": aliases,
                "expected_phrase": seed["phrase"],
                "query_word_count": len(tokenize(artist_title_query)),
                "variant": "artist_title",
            }
        )

    return generated


def build_queries() -> list[dict]:
    per_seed = [build_seed_queries(seed) for seed in SEEDS]
    generated: list[dict] = []
    index = 0
    while len(generated) < QUERY_LIMIT:
        progressed = False
        for bucket in per_seed:
            if index < len(bucket):
                generated.append(bucket[index])
                progressed = True
                if len(generated) >= QUERY_LIMIT:
                    break
        if not progressed:
            break
        index += 1
    return generated


def token_set_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if rf_fuzz is not None:
        return float(rf_fuzz.token_set_ratio(a, b)) / 100.0
    left = set(a.split())
    right = set(b.split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def text_variants(text: str) -> list[str]:
    norm = normalize_query(text)
    variants = [norm]
    try:
        variants.append(normalize_query(transliterate_cyr_to_lat(norm)))
        variants.append(normalize_query(transliterate_lat_to_cyr(norm)))
    except Exception:
        pass
    seen: set[str] = set()
    unique: list[str] = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def grade_result(expected_aliases: list[str], expected_phrase: str, artist: str, title: str) -> tuple[str, float, float, float]:
    actual_variants = text_variants(f"{artist} {title}")
    title_variants = text_variants(title)
    full_best = 0.0
    title_best = 0.0
    phrase_best = 0.0

    for expected in expected_aliases:
        for candidate in text_variants(expected):
            for actual in actual_variants:
                full_best = max(full_best, token_set_similarity(candidate, actual))
            for actual_title in title_variants:
                title_best = max(title_best, token_set_similarity(candidate, actual_title))

    for candidate in text_variants(expected_phrase):
        for actual in actual_variants:
            phrase_best = max(phrase_best, token_set_similarity(candidate, actual))

    if full_best >= 0.72:
        return "strong", full_best, title_best, phrase_best
    if full_best >= 0.58 or title_best >= 0.88 or phrase_best >= 0.72:
        return "related", full_best, title_best, phrase_best
    return "miss", full_best, title_best, phrase_best


def clone_tracks(items: list[dict]) -> list[dict]:
    return [dict(item) for item in items]


class SearchHarness:
    def __init__(self) -> None:
        self.provider_cache: dict[tuple[str, str, int], list[dict]] = {}
        self.local_cache: dict[tuple[str, int], list[dict]] = {}
        self.speller_cache: dict[str, str | None] = {}
        self.sem = asyncio.Semaphore(CONCURRENCY)

    async def local_search(self, query: str, limit: int) -> list[dict]:
        key = (query, limit)
        if key in self.local_cache:
            return clone_tracks(self.local_cache[key])

        tracks = await search_local_tracks(query, limit=limit)
        mapped = [
            {
                "video_id": track.source_id,
                "title": track.title or "Unknown",
                "uploader": track.artist or "Unknown",
                "duration": track.duration or 0,
                "source": track.source or "channel",
                "file_id": track.file_id,
                "_provider_pos": idx,
            }
            for idx, track in enumerate(tracks or [])
        ]
        self.local_cache[key] = clone_tracks(mapped)
        return clone_tracks(mapped)

    async def provider_search(self, source: str, query: str, limit: int) -> list[dict]:
        key = (source, query, limit)
        if key in self.provider_cache:
            return clone_tracks(self.provider_cache[key])

        async with self.sem:
            try:
                if source == "yandex":
                    result = await asyncio.wait_for(search_yandex(query, limit=limit), timeout=SEARCH_TIMEOUT)
                elif source == "youtube":
                    result = await asyncio.wait_for(
                        search_tracks(query, max_results=limit, source="youtube"),
                        timeout=SEARCH_TIMEOUT,
                    )
                else:
                    result = []
            except Exception:
                result = []

        prepared = clone_tracks(result or [])
        self.provider_cache[key] = prepared
        return clone_tracks(prepared)

    async def get_correction(self, query: str) -> str | None:
        if query in self.speller_cache:
            return self.speller_cache[query]
        try:
            corrected = await correct_query(query)
        except Exception:
            corrected = None
        self.speller_cache[query] = corrected
        return corrected

    @staticmethod
    def stamp_positions(items: list[dict]) -> list[dict]:
        stamped = clone_tracks(items)
        for idx, item in enumerate(stamped):
            item["_provider_pos"] = idx
        return stamped

    async def run_query(self, raw_query: str) -> dict:
        started = time.perf_counter()
        parsed = parse_query(raw_query)
        query = parsed["clean"] or parsed["original"] or raw_query
        translit_used = False
        lyrics_used = False
        speller_used = False
        corrected_to = None

        local_results = await self.local_search(query, PROVIDER_LIMIT)
        yandex_results, youtube_results = await asyncio.gather(
            self.provider_search("yandex", query, PROVIDER_LIMIT),
            self.provider_search("youtube", query, YOUTUBE_LIMIT),
        )

        provider_results = self.stamp_positions(yandex_results) + self.stamp_positions(youtube_results)

        if len(provider_results) < 3:
            script = detect_script(query)
            alt_query = None
            if script == "cyrillic":
                alt_query = transliterate_cyr_to_lat(query)
            elif script == "latin":
                alt_query = transliterate_lat_to_cyr(query)
            if alt_query and alt_query != query:
                alt_yandex, alt_youtube = await asyncio.gather(
                    self.provider_search("yandex", alt_query, PROVIDER_LIMIT),
                    self.provider_search("youtube", alt_query, PROVIDER_LIMIT),
                )
                alt_results = self.stamp_positions(alt_yandex) + self.stamp_positions(alt_youtube)
                if alt_results:
                    translit_used = True
                    provider_results.extend(alt_results)

        all_results = clone_tracks(local_results) + clone_tracks(provider_results)
        script = detect_script(query)
        deduped = deduplicate_results(all_results, lang_hint=script, query=query) if all_results else []
        results = deduped[:1]

        if len(query.split()) >= 4:
            best_score = _relevance_score(
                normalize_query(query),
                results[0].get("uploader", ""),
                results[0].get("title", ""),
                position=results[0].get("_provider_pos", 5),
            ) if results else 0.0
            if not results or best_score < 0.85:
                lyric_hints = await search_by_lyrics(query, limit=2)
                hint_tracks: list[dict] = []
                seen_hint_queries: set[str] = set()
                for hint in lyric_hints:
                    artist_hint = hint.get("artist", "").strip()
                    title_hint = hint.get("title", "").strip()
                    if not artist_hint or not title_hint:
                        continue
                    hint_query = f"{artist_hint} {title_hint}".strip()
                    if hint_query in seen_hint_queries:
                        continue
                    seen_hint_queries.add(hint_query)
                    hint_yandex, hint_youtube = await asyncio.gather(
                        self.provider_search("yandex", hint_query, 2),
                        self.provider_search("youtube", hint_query, 2),
                    )
                    for idx, track in enumerate(self.stamp_positions(hint_yandex) + self.stamp_positions(hint_youtube)):
                        track["_hint_bonus"] = 0.85 if idx == 0 else 0.65
                        hint_tracks.append(track)
                if hint_tracks:
                    all_results.extend(hint_tracks)
                    results = deduplicate_results(all_results, lang_hint=script, query=query)[:1]
                    lyrics_used = True

        if not results:
            corrected = await self.get_correction(query)
            if corrected and corrected != query:
                speller_used = True
                corrected_to = corrected
                local_retry = await self.local_search(corrected, PROVIDER_LIMIT)
                yandex_retry, youtube_retry = await asyncio.gather(
                    self.provider_search("yandex", corrected, PROVIDER_LIMIT),
                    self.provider_search("youtube", corrected, PROVIDER_LIMIT),
                )
                retry_results = clone_tracks(local_retry)
                retry_results.extend(self.stamp_positions(yandex_retry))
                retry_results.extend(self.stamp_positions(youtube_retry))
                retry_script = detect_script(corrected)
                retry_deduped = deduplicate_results(retry_results, lang_hint=retry_script, query=corrected) if retry_results else []
                results = retry_deduped[:1]
                query = corrected

        elapsed = time.perf_counter() - started
        best = results[0] if results else None
        if best:
            relevance = _relevance_score(
                normalize_query(query),
                best.get("uploader", ""),
                best.get("title", ""),
                position=best.get("_provider_pos", 5),
            )
        else:
            relevance = 0.0

        return {
            "query": raw_query,
            "clean_query": query,
            "translit_used": translit_used,
            "lyrics_used": lyrics_used,
            "speller_used": speller_used,
            "corrected_to": corrected_to,
            "elapsed": round(elapsed, 4),
            "found": bool(best),
            "relevance": round(relevance, 4),
            "artist": best.get("uploader", "") if best else "",
            "title": best.get("title", "") if best else "",
            "source": best.get("source", "") if best else "",
        }


def summarize(results: list[dict]) -> dict:
    totals = len(results)
    found = [item for item in results if item["found"]]
    strong = [item for item in results if item["match_grade"] == "strong"]
    related = [item for item in results if item["match_grade"] == "related"]
    misses = [item for item in results if item["match_grade"] == "miss"]
    empty = [item for item in results if not item["found"]]
    times = [item["elapsed"] for item in results]
    strict_cases = [item for item in results if item["query_word_count"] >= 4]
    strict_hits = [item for item in strict_cases if item["match_grade"] in {"strong", "related"}]

    by_category: dict[str, dict] = {}
    for item in results:
        bucket = by_category.setdefault(
            item["category"],
            {"total": 0, "found": 0, "strong": 0, "related": 0, "miss": 0, "avg_time": []},
        )
        bucket["total"] += 1
        if item["found"]:
            bucket["found"] += 1
        bucket[item["match_grade"]] += 1
        bucket["avg_time"].append(item["elapsed"])

    for bucket in by_category.values():
        bucket["avg_time"] = round(sum(bucket["avg_time"]) / max(1, len(bucket["avg_time"])), 4)

    p95 = 0.0
    if len(times) >= 20:
        p95 = statistics.quantiles(times, n=20)[18]
    elif times:
        p95 = max(times)

    return {
        "total_queries": totals,
        "found": len(found),
        "strong": len(strong),
        "related": len(related),
        "miss": len(misses),
        "empty": len(empty),
        "success_rate": round((len(strong) + len(related)) / max(1, totals), 4),
        "strict_success_rate": round(len(strict_hits) / max(1, len(strict_cases)), 4),
        "found_rate": round(len(found) / max(1, totals), 4),
        "avg_time": round(sum(times) / max(1, len(times)), 4),
        "median_time": round(statistics.median(times), 4) if times else 0.0,
        "p95_time": round(p95, 4),
        "translit_used": sum(1 for item in results if item["translit_used"]),
        "lyrics_used": sum(1 for item in results if item["lyrics_used"]),
        "speller_used": sum(1 for item in results if item["speller_used"]),
        "by_category": by_category,
        "sample_failures": [
            {
                "query": item["query"],
                "expected": f"{item['expected_artist']} - {item['expected_title']}",
                "actual": f"{item['artist']} - {item['title']}".strip(" -"),
                "grade": item["match_grade"],
                "match_score": item["match_score"],
                "phrase_score": item["phrase_score"],
                "relevance": item["relevance"],
            }
            for item in results
            if item["match_grade"] != "strong"
        ][:25],
    }


async def main() -> None:
    try:
        cases = build_queries()
        harness = SearchHarness()
        started = time.perf_counter()
        print(f"Generated {len(cases)} queries. Running with concurrency={CONCURRENCY}.")

        async def evaluate_case(case: dict) -> dict:
            outcome = await harness.run_query(case["query"])
            merged = {**case, **outcome}
            if merged["found"]:
                grade, match_score, title_score, phrase_score = grade_result(
                    merged["expected_aliases"],
                    merged["expected_phrase"],
                    merged["artist"],
                    merged["title"],
                )
            else:
                grade, match_score, title_score, phrase_score = "miss", 0.0, 0.0, 0.0
            merged["match_grade"] = grade
            merged["match_score"] = round(match_score, 4)
            merged["title_score"] = round(title_score, 4)
            merged["phrase_score"] = round(phrase_score, 4)
            return merged

        case_sem = asyncio.Semaphore(CONCURRENCY)

        async def guarded_evaluate(case: dict) -> dict:
            async with case_sem:
                return await evaluate_case(case)

        tasks = [asyncio.create_task(guarded_evaluate(case)) for case in cases]
        finished: list[dict] = []
        for idx, task in enumerate(asyncio.as_completed(tasks), start=1):
            finished.append(await task)
            if idx % 100 == 0 or idx == len(tasks):
                print(f"Completed {idx}/{len(tasks)} queries...")

        summary = summarize(finished)
        summary["generated_queries"] = len(cases)
        summary["duration_total"] = round(time.perf_counter() - started, 4)

        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            json.dumps({"summary": summary, "results": finished}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("=== SUMMARY ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Report written to {REPORT_PATH}")
    finally:
        await close_session()


if __name__ == "__main__":
    asyncio.run(main())