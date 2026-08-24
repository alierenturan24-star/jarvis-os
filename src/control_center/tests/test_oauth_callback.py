from __future__ import annotations

import http.client
import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.control_center.server import ControlCenterServer
from src.workforce.accounts import AccountConnectionManager, GoogleYouTubeProvider


TOKEN = "test-bootstrap-token-that-is-long-enough"


class MemoryVault:
    def __init__(self): self.values = {}
    def store(self, ref, value): self.values[ref] = value
    def delete(self, ref): self.values.pop(ref, None)
    def resolve_for_publisher(self, ref): return self.values[ref]


class FakeStore:
    """Minimal store double with just the shape complete_account_connection touches."""

    def __init__(self):
        self._state = {
            "channels": {"youtube-de": {"market": "Germany", "language": "de-DE", "identity": {},
                "youtube_learning": {"analytics": {}, "publication_history": []}}},
            "account_assignments": [],
        }

    def snapshot(self): return self._state
    def update(self, mutate): mutate(self._state)


class FakeService:
    """Mirrors ControlCenterService.complete_account_connection using the real
    GoogleYouTubeProvider/AccountConnectionManager state-validation path, with no network I/O."""

    def __init__(self, provider):
        self.store = FakeStore()
        self.accounts = AccountConnectionManager(self.store, provider)

    def complete_account_connection(self, state, code):
        result = self.accounts.provider.complete(state=state, code=code)
        channel = self.store.snapshot()["channels"][result["channel_id"]]
        return self.accounts.complete(result, market=channel["market"], language=channel["language"])


def make_provider(monkeypatch):
    vault = MemoryVault()
    vault.store("JARVIS/YOUTUBE/OAUTH_CLIENT", b'{"client_id": "synthetic-client"}')
    provider = GoogleYouTubeProvider(vault)
    monkeypatch.setattr(provider, "_request_json",
        lambda url, **kw: {"access_token": "synthetic-access-token", "obtained_at": "2026-08-21T00:00:00+00:00"})
    monkeypatch.setattr(provider, "_authorized_channel",
        lambda token: {"id": "remote-de", "snippet": {"title": "DE"}})
    return provider


@pytest.fixture
def oauth_server(monkeypatch):
    provider = make_provider(monkeypatch)
    service = FakeService(provider)
    server = ControlCenterServer(("127.0.0.1", 0), service, TOKEN, frozenset())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, provider
    finally:
        server.shutdown(); server.server_close(); thread.join(2)


def request(server, path, headers=None, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    connection.request(method, path, body=b"{}" if method == "POST" else None, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def begin_session(provider, *, worker_id="deniz", channel_id="youtube-de"):
    result = provider.begin(worker_id=worker_id, channel_id=channel_id,
        redirect_uri="http://127.0.0.1/api/oauth/google/callback")
    return result["state"]


def host_header(server):
    return {"Host": f"127.0.0.1:{server.server_port}"}


def test_oauth_callback_reaches_completion_without_session_cookie(oauth_server):
    server, provider = oauth_server
    state = begin_session(provider)

    status, _, body = request(server, f"/api/oauth/google/callback?state={state}&code=synthetic-code",
        host_header(server))

    assert status == 200
    assert b"Authorization completed" in body
    assert provider.vault.values


def test_ordinary_protected_get_endpoints_still_require_session(oauth_server):
    server, _ = oauth_server
    status, _, body = request(server, "/api/status", host_header(server))
    assert status == 401
    assert body == b'{"error": "Unauthorized"}'


def test_missing_state_is_rejected(oauth_server):
    server, _ = oauth_server
    status, _, body = request(server, "/api/oauth/google/callback?code=synthetic-code", host_header(server))
    assert status == 400
    assert TOKEN.encode() not in body


def test_invalid_state_is_rejected(oauth_server):
    server, _ = oauth_server
    status, _, _ = request(server, "/api/oauth/google/callback?state=not-a-real-state&code=synthetic-code",
        host_header(server))
    assert status == 400


def test_expired_state_is_rejected(oauth_server):
    server, provider = oauth_server
    state = begin_session(provider)
    provider._sessions[state].created_at = (
        datetime.now(timezone.utc) - timedelta(seconds=provider.STATE_TTL_SECONDS + 1)
    ).isoformat()

    status, _, _ = request(server, f"/api/oauth/google/callback?state={state}&code=synthetic-code",
        host_header(server))

    assert status == 400


def test_replayed_state_is_rejected(oauth_server):
    server, provider = oauth_server
    state = begin_session(provider)
    path = f"/api/oauth/google/callback?state={state}&code=synthetic-code"

    status1, _, _ = request(server, path, host_header(server))
    assert status1 == 200

    status2, _, body2 = request(server, path, host_header(server))
    assert status2 == 400
    assert state.encode() not in body2


def test_missing_code_is_rejected(oauth_server):
    server, provider = oauth_server
    state = begin_session(provider)
    status, _, _ = request(server, f"/api/oauth/google/callback?state={state}", host_header(server))
    assert status == 400


def test_callback_error_response_never_leaks_secrets(oauth_server):
    server, provider = oauth_server
    status, _, body = request(server, "/api/oauth/google/callback?state=bogus&code=synthetic-code",
        host_header(server))

    assert status == 400
    assert b"synthetic-access-token" not in body
    assert b"synthetic-client" not in body
    assert TOKEN.encode() not in body
    assert b"client_secret" not in body
    for secret in provider.vault.values.values():
        assert secret not in body


def test_authenticated_normal_get_behavior_is_unchanged(oauth_server):
    server, _ = oauth_server
    headers = {**host_header(server), "Cookie": f"jarvis_session={TOKEN}"}
    status, _, body = request(server, "/api/accounts", headers)
    assert status == 200
    assert body == b"[]"
