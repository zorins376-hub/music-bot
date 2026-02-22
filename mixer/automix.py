"""
automix.py — AUTO MIX: crossfade миксинг треков из TEQUILA + FULLMOON (v1.3).

Алгоритм:
  1. Берёт 3 трека из TEQUILA + 3 из FULLMOON (по очереди)
  2. Анализирует BPM через librosa
  3. Сортирует по BPM для плавного перехода
  4. Делает crossfade 5-10 сек через pydub
  5. Нормализует громкость (-14 LUFS)
  6. Отдаёт готовый MP3 файл
"""
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def create_mix(
    track_paths: list[Path],
    output_path: Path,
    crossfade_ms: int = 7000,
) -> Path:
    """
    Создаёт микс из списка MP3 файлов с crossfade.
    Запускает тяжёлую обработку в executor.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _create_mix_sync, track_paths, output_path, crossfade_ms
    )


def _create_mix_sync(
    track_paths: list[Path],
    output_path: Path,
    crossfade_ms: int,
) -> Path:
    try:
        from pydub import AudioSegment
    except ImportError:
        raise RuntimeError("pydub не установлен")

    if not track_paths:
        raise ValueError("Нет треков для микса")

    segments = [AudioSegment.from_mp3(str(p)) for p in track_paths]

    # Сортировка по BPM (если доступна librosa)
    segments = _sort_by_bpm(segments, track_paths)

    # Нормализация громкости
    segments = [_normalize(s) for s in segments]

    # Crossfade склейка
    result = segments[0]
    for seg in segments[1:]:
        result = result.append(seg, crossfade=crossfade_ms)

    result.export(str(output_path), format="mp3", bitrate="192k")
    logger.info("Mix created: %s (%.1f min)", output_path, len(result) / 60000)
    return output_path


def _sort_by_bpm(segments, paths: list[Path]):
    """Сортирует треки по BPM для плавного перехода. Требует librosa."""
    try:
        import librosa
        import numpy as np

        bpms = []
        for p in paths:
            y, sr = librosa.load(str(p), sr=22050, mono=True, duration=30)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpms.append(float(tempo))

        paired = sorted(zip(bpms, segments), key=lambda x: x[0])
        return [s for _, s in paired]
    except Exception as e:
        logger.warning("BPM sort skipped: %s", e)
        return segments


def _normalize(segment, target_dbfs: float = -14.0):
    """Нормализация громкости до target_dbfs."""
    diff = target_dbfs - segment.dBFS
    return segment.apply_gain(diff)
