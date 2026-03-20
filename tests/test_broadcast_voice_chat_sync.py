import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock

import pytest


class _DummyFilter:
    def __and__(self, other):
        return self


class _FakeFilters:
    @staticmethod
    def chat(_group_id):
        return _DummyFilter()

    @staticmethod
    def command(_commands):
        return _DummyFilter()


class _FakeAudioPiped:
    def __init__(self, file_id, audio_parameters=None):
        self.file_id = file_id
        self.audio_parameters = audio_parameters


class _FakeAudioQuality:
    HIGH = "high"


class _FakeApp:
    def on_message(self, _filter):
        def decorator(func):
            return func

        return decorator


class _FakeTgCalls:
    def __init__(self):
        self.play_calls: list[tuple[int, str]] = []
        self.stream_end_handler = None

    def on_stream_end(self):
        def decorator(func):
            self.stream_end_handler = func
            return func

        return decorator

    async def play(self, group_id, audio):
        self.play_calls.append((group_id, audio.file_id))


class _FailingFirstPlayTgCalls(_FakeTgCalls):
    def __init__(self):
        super().__init__()
        self._failed_once = False

    async def play(self, group_id, audio):
        self.play_calls.append((group_id, audio.file_id))
        if not self._failed_once:
            self._failed_once = True
            raise RuntimeError("broken stream")


class _BlockingSecondPlayTgCalls(_FakeTgCalls):
    def __init__(self):
        super().__init__()
        self._play_count = 0
        self.release_second_play = asyncio.Event()

    async def play(self, group_id, audio):
        self.play_calls.append((group_id, audio.file_id))
        self._play_count += 1
        if self._play_count == 2:
            await self.release_second_play.wait()


class _FakeCache:
    def __init__(self, redis):
        self.redis = redis


class _JsonRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _record_background_tasks(tasks):
    def runner(coro):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    return runner


@pytest.mark.asyncio
async def test_stop_broadcast_cleans_only_active_channel(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    fake_redis.publish = AsyncMock(return_value=1)
    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={"channel": "fullmoon"})
    await fake_redis.rpush("radio:queue:fullmoon", json.dumps({"video_id": "fm-1"}))
    await fake_redis.set("radio:current:fullmoon", json.dumps({"video_id": "fm-1"}))
    await fake_redis.rpush("radio:queue:tequila", json.dumps({"video_id": "teq-1"}))
    await fake_redis.set("radio:current:tequila", json.dumps({"video_id": "teq-1"}))

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_broadcast_notify_chat", AsyncMock())
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    result = await api.stop_broadcast(user={"id": 1})
    await asyncio.gather(*tasks)

    assert result == {"ok": True}
    assert await fake_redis.exists("radio:queue:fullmoon") == 0
    assert await fake_redis.exists("radio:current:fullmoon") == 0
    assert await fake_redis.get("radio:current:tequila") is not None
    assert await fake_redis.llen("radio:queue:tequila") == 1
    fake_redis.publish.assert_awaited_once_with("radio:cmd", "stop")


@pytest.mark.asyncio
async def test_broadcast_add_track_appends_to_voice_chat_queue(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    fake_redis.publish = AsyncMock(return_value=1)
    await fake_redis.set(api._BCAST_LIVE_KEY, "1")
    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={"channel": "sunset", "current_idx": "0"})

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    request = _JsonRequest({
        "video_id": "track-1",
        "title": "Track 1",
        "artist": "Artist 1",
        "duration": 120,
        "duration_fmt": "2:00",
        "source": "channel",
    })

    result = await api.broadcast_add_track(request, user={"id": 1})
    await asyncio.gather(*tasks)

    assert result == {"ok": True}
    assert await fake_redis.llen(api._BCAST_QUEUE_KEY) == 1
    assert await fake_redis.llen("radio:queue:sunset") == 1

    raw = await fake_redis.lindex("radio:queue:sunset", 0)
    track = json.loads(raw)
    assert track["video_id"] == "track-1"
    assert track["channel"] == "sunset"
    fake_redis.publish.assert_awaited_once_with("radio:cmd", "skip")


@pytest.mark.asyncio
async def test_broadcast_load_channel_wakes_voice_chat_when_queue_was_empty(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    fake_redis.publish = AsyncMock(return_value=1)
    added_tracks = [json.dumps({
        "video_id": "track-1",
        "title": "Track 1",
        "artist": "Artist 1",
        "duration": 120,
        "duration_fmt": "2:00",
        "source": "channel",
        "file_id": "file-1",
        "channel": "sunset",
    })]

    await fake_redis.set(api._BCAST_LIVE_KEY, "1")
    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={"channel": "sunset", "current_idx": "0"})

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_load_channel_to_broadcast", AsyncMock(return_value=added_tracks))
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    request = _JsonRequest({"channel": "sunset", "limit": 10})
    result = await api.broadcast_load_channel(request, user={"id": 1})
    await asyncio.gather(*tasks)

    assert result == {"ok": True}
    fake_redis.publish.assert_awaited_once_with("radio:cmd", "skip")


@pytest.mark.asyncio
async def test_broadcast_advance_does_not_duplicate_voice_chat_queue(fake_redis, monkeypatch):
    from webapp import api

    queue_tracks = []
    for idx in range(8):
        raw = json.dumps({
            "video_id": f"track-{idx}",
            "title": f"Track {idx}",
            "artist": "Artist",
            "duration": 100,
            "duration_fmt": "1:40",
            "source": "channel",
            "file_id": f"file-{idx}",
            "channel": "sunset",
        })
        queue_tracks.append(raw)
        await fake_redis.rpush(api._BCAST_QUEUE_KEY, raw)
        await fake_redis.rpush("radio:queue:sunset", raw)

    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={
        "channel": "sunset",
        "current_idx": "1",
        "seek_pos": "0",
        "action": "play",
    })

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())

    await api.broadcast_advance(user={"id": 1})

    assert await fake_redis.llen("radio:queue:sunset") == len(queue_tracks)
    assert await fake_redis.lrange("radio:queue:sunset", 0, -1) == queue_tracks


@pytest.mark.asyncio
async def test_broadcast_remove_track_rebuilds_pending_voice_chat_queue(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    queue_tracks = []
    for idx in range(4):
        raw = json.dumps({
            "video_id": f"track-{idx}",
            "title": f"Track {idx}",
            "artist": "Artist",
            "duration": 100,
            "duration_fmt": "1:40",
            "source": "channel",
            "file_id": f"file-{idx}",
            "channel": "sunset",
        })
        queue_tracks.append(raw)
        await fake_redis.rpush(api._BCAST_QUEUE_KEY, raw)

    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={
        "channel": "sunset",
        "current_idx": "0",
        "seek_pos": "0",
        "action": "play",
    })
    await fake_redis.rpush("radio:queue:sunset", *queue_tracks[1:])

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    await api.broadcast_remove_track("track-1", user={"id": 1})
    await asyncio.gather(*tasks)

    assert await fake_redis.lrange("radio:queue:sunset", 0, -1) == [queue_tracks[2], queue_tracks[3]]


@pytest.mark.asyncio
async def test_broadcast_reorder_rebuilds_pending_voice_chat_queue(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    queue_tracks = []
    for idx in range(4):
        raw = json.dumps({
            "video_id": f"track-{idx}",
            "title": f"Track {idx}",
            "artist": "Artist",
            "duration": 100,
            "duration_fmt": "1:40",
            "source": "channel",
            "file_id": f"file-{idx}",
            "channel": "sunset",
        })
        queue_tracks.append(raw)
        await fake_redis.rpush(api._BCAST_QUEUE_KEY, raw)

    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={
        "channel": "sunset",
        "current_idx": "0",
        "seek_pos": "0",
        "action": "play",
    })
    await fake_redis.rpush("radio:queue:sunset", *queue_tracks[1:])

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    request = _JsonRequest({"from_position": 3, "to_position": 1})
    await api.broadcast_reorder(request, user={"id": 1})
    await asyncio.gather(*tasks)

    assert await fake_redis.lrange("radio:queue:sunset", 0, -1) == [queue_tracks[3], queue_tracks[1], queue_tracks[2]]


@pytest.mark.asyncio
async def test_broadcast_skip_rebuilds_voice_chat_queue_with_new_current(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    fake_redis.publish = AsyncMock(return_value=1)
    queue_tracks = []
    for idx in range(4):
        raw = json.dumps({
            "video_id": f"track-{idx}",
            "title": f"Track {idx}",
            "artist": "Artist",
            "duration": 100,
            "duration_fmt": "1:40",
            "source": "channel",
            "file_id": f"file-{idx}",
            "channel": "sunset",
        })
        queue_tracks.append(raw)
        await fake_redis.rpush(api._BCAST_QUEUE_KEY, raw)

    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={
        "channel": "sunset",
        "current_idx": "0",
        "seek_pos": "0",
        "action": "play",
    })
    await fake_redis.rpush("radio:queue:sunset", *queue_tracks[1:])

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    await api.broadcast_skip(user={"id": 1})
    await asyncio.gather(*tasks)

    assert await fake_redis.lrange("radio:queue:sunset", 0, -1) == [queue_tracks[1], queue_tracks[2], queue_tracks[3]]
    fake_redis.publish.assert_awaited_once_with("radio:cmd", "skip")


@pytest.mark.asyncio
async def test_broadcast_playback_current_idx_rebuilds_voice_chat_queue(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    fake_redis.publish = AsyncMock(return_value=1)
    queue_tracks = []
    for idx in range(4):
        raw = json.dumps({
            "video_id": f"track-{idx}",
            "title": f"Track {idx}",
            "artist": "Artist",
            "duration": 100,
            "duration_fmt": "1:40",
            "source": "channel",
            "file_id": f"file-{idx}",
            "channel": "sunset",
        })
        queue_tracks.append(raw)
        await fake_redis.rpush(api._BCAST_QUEUE_KEY, raw)

    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={
        "channel": "sunset",
        "current_idx": "0",
        "seek_pos": "0",
        "action": "play",
    })
    await fake_redis.rpush("radio:queue:sunset", *queue_tracks[1:])

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    request = _JsonRequest({"action": "play", "seek_pos": 0, "current_idx": 2})
    await api.broadcast_playback(request, user={"id": 1})
    await asyncio.gather(*tasks)

    assert await fake_redis.lrange("radio:queue:sunset", 0, -1) == [queue_tracks[2], queue_tracks[3]]
    fake_redis.publish.assert_awaited_once_with("radio:cmd", "skip")


@pytest.mark.asyncio
async def test_broadcast_remove_current_track_publishes_skip(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    fake_redis.publish = AsyncMock(return_value=1)
    queue_tracks = []
    for idx in range(3):
        raw = json.dumps({
            "video_id": f"track-{idx}",
            "title": f"Track {idx}",
            "artist": "Artist",
            "duration": 100,
            "duration_fmt": "1:40",
            "source": "channel",
            "file_id": f"file-{idx}",
            "channel": "sunset",
        })
        queue_tracks.append(raw)
        await fake_redis.rpush(api._BCAST_QUEUE_KEY, raw)

    await fake_redis.hset(api._BCAST_STATE_KEY, mapping={
        "channel": "sunset",
        "current_idx": "0",
        "seek_pos": "0",
        "action": "play",
    })

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    await api.broadcast_remove_track("track-0", user={"id": 1})
    await asyncio.gather(*tasks)

    fake_redis.publish.assert_awaited_once_with("radio:cmd", "skip")


@pytest.mark.asyncio
async def test_start_broadcast_publishes_skip_for_immediate_pickup(fake_redis, monkeypatch):
    from webapp import api

    tasks = []
    fake_redis.publish = AsyncMock(return_value=1)

    monkeypatch.setattr(api, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(api, "_require_broadcast_admin", AsyncMock())
    monkeypatch.setattr(api, "_notify_broadcast", AsyncMock())
    monkeypatch.setattr(api, "_broadcast_notify_chat", AsyncMock())
    monkeypatch.setattr(api, "_load_channel_to_broadcast", AsyncMock(return_value=[]))
    monkeypatch.setattr(api, "_get_broadcast_state", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(api, "_fire_task", _record_background_tasks(tasks))

    request = _JsonRequest({"channel": "sunset", "limit": 5})
    result = await api.start_broadcast(request, user={"id": 1, "first_name": "DJ"})
    await asyncio.gather(*tasks)

    assert result == {"ok": True}
    fake_redis.publish.assert_awaited_once_with("radio:cmd", "skip")


@pytest.mark.asyncio
async def test_streamer_prefers_active_broadcast_channel(fake_redis, monkeypatch):
    from streamer import voice_chat

    fake_pyrogram = types.ModuleType("pyrogram")
    fake_pyrogram.filters = _FakeFilters()
    fake_pytgcalls_types = types.ModuleType("pytgcalls.types")
    fake_pytgcalls_types.AudioPiped = _FakeAudioPiped
    fake_pytgcalls_types.AudioQuality = _FakeAudioQuality

    monkeypatch.setitem(sys.modules, "pyrogram", fake_pyrogram)
    monkeypatch.setitem(sys.modules, "pytgcalls.types", fake_pytgcalls_types)

    await fake_redis.set("broadcast:live", "1")
    await fake_redis.hset("broadcast:state", mapping={"channel": "sunset"})
    await fake_redis.rpush("radio:queue:sunset", json.dumps({
        "video_id": "sun-1",
        "title": "Sunset Track",
        "artist": "DJ Sunset",
        "duration": 123,
        "file_id": "file-sunset",
        "channel": "sunset",
    }))
    await fake_redis.rpush("radio:queue:tequila", json.dumps({
        "video_id": "teq-1",
        "title": "Tequila Track",
        "artist": "DJ Tequila",
        "duration": 123,
        "file_id": "file-tequila",
        "channel": "tequila",
    }))

    app = _FakeApp()
    tgcalls = _FakeTgCalls()
    cache = _FakeCache(fake_redis)

    await voice_chat._run_group(app, tgcalls, -100123, cache)

    assert tgcalls.play_calls == [(-100123, "file-sunset")]
    current = await fake_redis.get("radio:current:sunset")
    assert current is not None
    assert json.loads(current)["video_id"] == "sun-1"


@pytest.mark.asyncio
async def test_streamer_skips_broken_track_and_plays_next(fake_redis, monkeypatch):
    from streamer import voice_chat

    fake_pyrogram = types.ModuleType("pyrogram")
    fake_pyrogram.filters = _FakeFilters()
    fake_pytgcalls_types = types.ModuleType("pytgcalls.types")
    fake_pytgcalls_types.AudioPiped = _FakeAudioPiped
    fake_pytgcalls_types.AudioQuality = _FakeAudioQuality

    monkeypatch.setitem(sys.modules, "pyrogram", fake_pyrogram)
    monkeypatch.setitem(sys.modules, "pytgcalls.types", fake_pytgcalls_types)

    await fake_redis.set("broadcast:live", "1")
    await fake_redis.hset("broadcast:state", mapping={"channel": "sunset"})

    await fake_redis.rpush("radio:queue:sunset", json.dumps({
        "video_id": "broken-1",
        "title": "Broken Track",
        "artist": "DJ Sunset",
        "duration": 123,
        "file_id": "file-broken",
        "channel": "sunset",
    }))
    await fake_redis.rpush("radio:queue:sunset", json.dumps({
        "video_id": "good-2",
        "title": "Good Track",
        "artist": "DJ Sunset",
        "duration": 123,
        "file_id": "file-good",
        "channel": "sunset",
    }))

    app = _FakeApp()
    tgcalls = _FailingFirstPlayTgCalls()
    cache = _FakeCache(fake_redis)

    await voice_chat._run_group(app, tgcalls, -100123, cache)

    assert tgcalls.play_calls == [(-100123, "file-broken"), (-100123, "file-good")]
    current = await fake_redis.get("radio:current:sunset")
    assert current is not None
    assert json.loads(current)["video_id"] == "good-2"


@pytest.mark.asyncio
async def test_streamer_coalesces_duplicate_transition_triggers(fake_redis, monkeypatch):
    from streamer import voice_chat

    fake_pyrogram = types.ModuleType("pyrogram")
    fake_pyrogram.filters = _FakeFilters()
    fake_pytgcalls_types = types.ModuleType("pytgcalls.types")
    fake_pytgcalls_types.AudioPiped = _FakeAudioPiped
    fake_pytgcalls_types.AudioQuality = _FakeAudioQuality

    monkeypatch.setitem(sys.modules, "pyrogram", fake_pyrogram)
    monkeypatch.setitem(sys.modules, "pytgcalls.types", fake_pytgcalls_types)

    await fake_redis.set("broadcast:live", "1")
    await fake_redis.hset("broadcast:state", mapping={"channel": "sunset"})
    for video_id, file_id in (("track-1", "file-1"), ("track-2", "file-2"), ("track-3", "file-3")):
        await fake_redis.rpush("radio:queue:sunset", json.dumps({
            "video_id": video_id,
            "title": video_id,
            "artist": "DJ Sunset",
            "duration": 123,
            "file_id": file_id,
            "channel": "sunset",
        }))

    app = _FakeApp()
    tgcalls = _BlockingSecondPlayTgCalls()
    cache = _FakeCache(fake_redis)

    await voice_chat._run_group(app, tgcalls, -100123, cache)

    update = types.SimpleNamespace(chat_id=-100123)
    first = asyncio.create_task(tgcalls.stream_end_handler(None, update))
    second = asyncio.create_task(tgcalls.stream_end_handler(None, update))
    await asyncio.sleep(0)
    tgcalls.release_second_play.set()
    await asyncio.gather(first, second)

    assert tgcalls.play_calls == [(-100123, "file-1"), (-100123, "file-2")]
    remaining = await fake_redis.lrange("radio:queue:sunset", 0, -1)
    assert len(remaining) == 1
    assert json.loads(remaining[0])["video_id"] == "track-3"


@pytest.mark.asyncio
async def test_streamer_multigroup_plays_same_track_without_double_pop(fake_redis, monkeypatch):
    from streamer import voice_chat

    fake_pyrogram = types.ModuleType("pyrogram")
    fake_pyrogram.filters = _FakeFilters()
    fake_pytgcalls_types = types.ModuleType("pytgcalls.types")
    fake_pytgcalls_types.AudioPiped = _FakeAudioPiped
    fake_pytgcalls_types.AudioQuality = _FakeAudioQuality

    monkeypatch.setitem(sys.modules, "pyrogram", fake_pyrogram)
    monkeypatch.setitem(sys.modules, "pytgcalls.types", fake_pytgcalls_types)

    await fake_redis.set("broadcast:live", "1")
    await fake_redis.hset("broadcast:state", mapping={"channel": "sunset"})
    await fake_redis.rpush("radio:queue:sunset", json.dumps({
        "video_id": "shared-1",
        "title": "Shared Track",
        "artist": "DJ Sunset",
        "duration": 123,
        "file_id": "file-shared",
        "channel": "sunset",
    }))

    app = _FakeApp()
    tgcalls = _FakeTgCalls()
    cache = _FakeCache(fake_redis)

    await voice_chat._run_groups(app, tgcalls, [-100123, -100456], cache)

    assert tgcalls.play_calls == [(-100123, "file-shared"), (-100456, "file-shared")]
    assert await fake_redis.llen("radio:queue:sunset") == 0
    current = await fake_redis.get("radio:current:sunset")
    assert current is not None
    assert json.loads(current)["video_id"] == "shared-1"


@pytest.mark.asyncio
async def test_streamer_multigroup_resets_votes_for_all_groups_on_next_track(fake_redis, monkeypatch):
    from streamer import voice_chat

    fake_pyrogram = types.ModuleType("pyrogram")
    fake_pyrogram.filters = _FakeFilters()
    fake_pytgcalls_types = types.ModuleType("pytgcalls.types")
    fake_pytgcalls_types.AudioPiped = _FakeAudioPiped
    fake_pytgcalls_types.AudioQuality = _FakeAudioQuality

    monkeypatch.setitem(sys.modules, "pyrogram", fake_pyrogram)
    monkeypatch.setitem(sys.modules, "pytgcalls.types", fake_pytgcalls_types)

    await fake_redis.set("broadcast:live", "1")
    await fake_redis.hset("broadcast:state", mapping={"channel": "sunset"})
    await fake_redis.rpush("radio:queue:sunset", json.dumps({
        "video_id": "shared-1",
        "title": "Shared Track",
        "artist": "DJ Sunset",
        "duration": 123,
        "file_id": "file-shared",
        "channel": "sunset",
    }))

    voice_chat._votes[100123]["dislikes"].add(1)
    voice_chat._votes[100456]["dislikes"].add(2)

    app = _FakeApp()
    tgcalls = _FakeTgCalls()
    cache = _FakeCache(fake_redis)

    await voice_chat._run_groups(app, tgcalls, [100123, 100456], cache)

    assert len(voice_chat._votes[100123]["dislikes"]) == 0
    assert len(voice_chat._votes[100456]["dislikes"]) == 0
