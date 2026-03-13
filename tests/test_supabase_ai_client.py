import pytest


class _FakeResponse:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status = status
        self._payload = payload if payload is not None else {}
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class _FakeRequestCtx:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self):
        self.last_get = None

    def get(self, url, headers=None, params=None):
        self.last_get = {"url": url, "headers": headers, "params": params}
        if url.endswith("/rest/v1/tracks?select=id&limit=1"):
            return _FakeRequestCtx(_FakeResponse(200, payload=[{"id": 1}]))
        if url.endswith("/functions/v1/recommend"):
            return _FakeRequestCtx(
                _FakeResponse(
                    200,
                    payload={
                        "recommendations": [
                            {"track_id": 10, "title": "Test Track", "artist": "Test Artist"}
                        ]
                    },
                )
            )
        return _FakeRequestCtx(_FakeResponse(404, payload={}, text="not found"))


class _ErrorRecommendSession:
    def get(self, url, headers=None, params=None):
        if url.endswith("/functions/v1/recommend"):
            return _FakeRequestCtx(_FakeResponse(500, payload={}, text="internal error"))
        return _FakeRequestCtx(_FakeResponse(200, payload=[]))


@pytest.mark.asyncio
async def test_supabase_ai_health_check_ok(monkeypatch):
    from bot.services import supabase_ai as mod

    fake_session = _FakeSession()

    async def _fake_get_session():
        return fake_session

    monkeypatch.setattr(mod, "_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(mod, "_SUPABASE_KEY", "service-role-key")
    monkeypatch.setattr(mod, "_get_session", _fake_get_session)

    result = await mod.supabase_ai.health_check()

    assert result["ok"] is True
    assert result["status"] == 200
    assert result["url"] == "https://example.supabase.co"


@pytest.mark.asyncio
async def test_supabase_ai_get_recommendations_ok(monkeypatch):
    from bot.services import supabase_ai as mod

    fake_session = _FakeSession()

    async def _fake_get_session():
        return fake_session

    monkeypatch.setattr(mod, "_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(mod, "_SUPABASE_KEY", "service-role-key")
    monkeypatch.setattr(mod, "_get_session", _fake_get_session)

    recs = await mod.supabase_ai.get_recommendations(user_id=123, limit=5, log_ab=True)

    assert len(recs) == 1
    assert recs[0]["track_id"] == 10
    assert fake_session.last_get["params"]["user_id"] == "123"
    assert fake_session.last_get["params"]["limit"] == "5"
    assert fake_session.last_get["params"]["log_ab"] == "1"


@pytest.mark.asyncio
async def test_supabase_ai_get_recommendations_api_error_returns_empty(monkeypatch):
    from bot.services import supabase_ai as mod

    error_session = _ErrorRecommendSession()

    async def _fake_get_session():
        return error_session

    monkeypatch.setattr(mod, "_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(mod, "_SUPABASE_KEY", "service-role-key")
    monkeypatch.setattr(mod, "_get_session", _fake_get_session)

    recs = await mod.supabase_ai.get_recommendations(user_id=123, limit=5)
    assert recs == []


@pytest.mark.asyncio
async def test_supabase_ai_health_check_not_configured(monkeypatch):
    from bot.services import supabase_ai as mod

    monkeypatch.setattr(mod, "_SUPABASE_URL", "")
    monkeypatch.setattr(mod, "_SUPABASE_KEY", "")

    result = await mod.supabase_ai.health_check()
    assert result["ok"] is False
    assert result["error"] == "Not configured"
