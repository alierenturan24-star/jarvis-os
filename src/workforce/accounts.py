from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.control_center.store import utc_now
from src.workforce.vault import WindowsCredentialVault


YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPES = (YOUTUBE_READ_SCOPE, YOUTUBE_UPLOAD_SCOPE, YOUTUBE_ANALYTICS_SCOPE)


@dataclass
class OAuthSession:
    state: str
    worker_id: str
    channel_id: str
    verifier: str
    redirect_uri: str
    created_at: str


class GoogleYouTubeProvider:
    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
    VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
    ANALYTICS_ENDPOINT = "https://youtubeanalytics.googleapis.com/v2/reports"
    STATE_TTL_SECONDS = 600

    def __init__(self, vault: WindowsCredentialVault | None = None) -> None:
        self.vault = vault or WindowsCredentialVault(); self._sessions: dict[str, OAuthSession] = {}

    def begin(self, *, worker_id: str, channel_id: str, redirect_uri: str) -> dict[str, Any]:
        config = self._load_config()
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        self._sessions[state] = OAuthSession(state, worker_id, channel_id, verifier, redirect_uri, utc_now())
        query = urllib.parse.urlencode({"client_id": config["client_id"], "redirect_uri": redirect_uri,
            "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline",
            "prompt": "consent", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
        return {"authorization_url": f"{self.AUTH_ENDPOINT}?{query}", "state": state,
                "expires_in_seconds": self.STATE_TTL_SECONDS, "secrets_exposed": False}

    def complete(self, *, state: str, code: str) -> dict[str, Any]:
        # Pop unconditionally (even on later failure) so a state value is never reusable — replay protection.
        session = self._sessions.pop(state, None)
        if session is None or not code: raise ValueError("Invalid or expired OAuth result")
        issued_at = datetime.fromisoformat(session.created_at.replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - issued_at).total_seconds() > self.STATE_TTL_SECONDS:
            raise ValueError("Invalid or expired OAuth result")
        config = self._load_config()
        form = {"client_id": config["client_id"], "code": code, "code_verifier": session.verifier,
                "redirect_uri": session.redirect_uri, "grant_type": "authorization_code"}
        if config.get("client_secret"): form["client_secret"] = config["client_secret"]
        token = self._request_json(self.TOKEN_ENDPOINT, form=form)
        token["obtained_at"] = utc_now()
        credential_ref = f"JARVIS/YOUTUBE/{session.channel_id}/{uuid.uuid4().hex}"
        self.vault.store(credential_ref, json.dumps(token).encode("utf-8"))
        try: channel = self._authorized_channel(token["access_token"])
        except Exception:
            self.vault.delete(credential_ref)
            raise
        return {"worker_id": session.worker_id, "channel_id": session.channel_id,
                "remote_channel_id": channel["id"], "channel_title": channel.get("snippet", {}).get("title", ""),
                "granted_scopes": tuple(str(token.get("scope", "")).split()) or SCOPES,
                "credential_ref": credential_ref, "connected_at": utc_now()}

    def verify(self, credential_ref: str) -> dict[str, Any]:
        token = self._token(credential_ref)
        try: channel = self._authorized_channel(token["access_token"])
        except Exception as error:
            if "401" in str(error): return {"status": "ACCOUNT_REAUTH_REQUIRED", "verified": False}
            raise
        return {"status": "CONNECTED", "verified": True, "remote_channel_id": channel["id"],
                "channel_title": channel.get("snippet", {}).get("title", ""), "last_verified_at": utc_now()}

    def verify_video(self, credential_ref: str, remote_video_id: str) -> dict[str, Any]:
        token = self._token(credential_ref)
        value = self._request_json(self.VIDEOS_ENDPOINT + "?" + urllib.parse.urlencode(
            {"part": "id,status,snippet", "id": remote_video_id}), bearer=token["access_token"])
        items = value.get("items", [])
        return {"verified": bool(items and items[0].get("id") == remote_video_id),
                "publication_status": "PUBLISHED_VERIFIED" if items else "REMOTE_NOT_FOUND"}

    def upload_video(self, credential_ref: str, *, artifact: str, metadata: dict) -> dict[str, Any]:
        """Official YouTube Data API multipart upload; called only after bound human approval."""
        token = self._token(credential_ref)
        boundary = "jarvis-" + secrets.token_hex(16)
        video = open(artifact, "rb").read()
        resource = {"snippet": {"title": metadata["title"], "description": metadata.get("description", ""),
                    "defaultLanguage": metadata.get("language")},
                    "status": {"privacyStatus": metadata.get("privacy_status", "private")}}
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                + json.dumps(resource, ensure_ascii=False) + f"\r\n--{boundary}\r\nContent-Type: video/mp4\r\n\r\n").encode()
        body += video + f"\r\n--{boundary}--\r\n".encode()
        url = "https://www.googleapis.com/upload/youtube/v3/videos?" + urllib.parse.urlencode(
            {"part": "snippet,status", "uploadType": "multipart"})
        request = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token['access_token']}",
            "Content-Type": f"multipart/related; boundary={boundary}", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))

    def analytics(self, credential_ref: str, *, start_date: str, end_date: str) -> dict[str, Any]:
        token = self._token(credential_ref)
        query = urllib.parse.urlencode({"ids": "channel==MINE", "startDate": start_date, "endDate": end_date,
            "metrics": "views,comments,likes,estimatedMinutesWatched,averageViewDuration,subscribersGained",
            "dimensions": "day"})
        raw = self._request_json(self.ANALYTICS_ENDPOINT + "?" + query, bearer=token["access_token"])
        headers = [item["name"] for item in raw.get("columnHeaders", [])]
        rows = [dict(zip(headers, row)) for row in raw.get("rows", [])]
        return {"source": "YOUTUBE_ANALYTICS_API", "rows": rows, "metrics_returned": headers,
                "status": "CONNECTED" if rows else "ANALYTICS INSUFFICIENT", "fetched_at": utc_now()}

    def disconnect(self, credential_ref: str) -> None:
        self.vault.delete(credential_ref)

    def _load_config(self) -> dict:
        try: raw = self.vault.resolve_for_publisher("JARVIS/YOUTUBE/OAUTH_CLIENT")
        except Exception as error: raise RuntimeError("YOUTUBE_OAUTH_NOT_CONFIGURED") from error
        value = json.loads(raw.decode("utf-8"))
        if not value.get("client_id"): raise RuntimeError("YOUTUBE_OAUTH_NOT_CONFIGURED")
        return value

    def _token(self, credential_ref: str) -> dict:
        token = json.loads(self.vault.resolve_for_publisher(credential_ref).decode("utf-8"))
        obtained = token.get("obtained_at")
        expired = False
        if obtained and token.get("expires_in"):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(obtained).replace("Z", "+00:00"))).total_seconds()
            expired = age >= max(0, int(token["expires_in"]) - 120)
        if expired and token.get("refresh_token"):
            config = self._load_config()
            form = {"client_id": config["client_id"], "refresh_token": token["refresh_token"],
                    "grant_type": "refresh_token"}
            if config.get("client_secret"): form["client_secret"] = config["client_secret"]
            refreshed = self._request_json(self.TOKEN_ENDPOINT, form=form)
            refreshed["refresh_token"] = token["refresh_token"]; refreshed["obtained_at"] = utc_now()
            self.vault.store(credential_ref, json.dumps(refreshed).encode("utf-8")); token = refreshed
        return token

    def _authorized_channel(self, access_token: str) -> dict:
        query = urllib.parse.urlencode({"part": "id,snippet,statistics,contentDetails", "mine": "true"})
        value = self._request_json(self.CHANNELS_ENDPOINT + "?" + query, bearer=access_token)
        items = value.get("items", [])
        if len(items) != 1: raise RuntimeError("AUTHORIZED_CHANNEL_NOT_UNIQUE")
        return items[0]

    @staticmethod
    def _request_json(url: str, *, form: dict | None = None, bearer: str | None = None) -> dict:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        headers = {"Accept": "application/json"}
        if form is not None: headers["Content-Type"] = "application/x-www-form-urlencoded"
        if bearer: headers["Authorization"] = f"Bearer {bearer}"
        request = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))


class AccountConnectionManager:
    def __init__(self, store, provider: GoogleYouTubeProvider | None = None) -> None:
        self.store, self.provider = store, provider or GoogleYouTubeProvider()

    def redacted_accounts(self) -> list[dict]:
        return [self._redact(item) for item in self.store.snapshot().get("account_assignments", [])]

    def account_for_channel(self, channel_id: str) -> dict | None:
        item = next((x for x in self.store.snapshot().get("account_assignments", [])
                     if x.get("channel_id") == channel_id and x.get("connection_status") == "CONNECTED"), None)
        return self._redact(item) if item else None

    def begin(self, worker: dict, redirect_uri: str) -> dict:
        if worker.get("division") != "YOUTUBE": raise ValueError("Only YouTube workers can connect YouTube accounts")
        return self.provider.begin(worker_id=worker["worker_id"], channel_id=worker["channel_id"], redirect_uri=redirect_uri)

    def complete(self, result: dict, *, market: str, language: str) -> dict:
        item = {"account_id": uuid.uuid4().hex, "provider": "GOOGLE_YOUTUBE_OAUTH",
            "assigned_worker_id": result["worker_id"], "channel_id": result["channel_id"],
            "remote_channel_id": result["remote_channel_id"], "channel_title": result["channel_title"],
            "market": market, "language": language, "connection_status": "CONNECTED",
            "granted_scopes": list(result["granted_scopes"]), "connected_at": result["connected_at"],
            "last_verified_at": result["connected_at"], "credential_ref": result["credential_ref"]}
        def mutate(state):
            rows = state.setdefault("account_assignments", [])
            rows[:] = [x for x in rows if x.get("channel_id") != item["channel_id"]]
            rows.append(item)
            channel = state["channels"][item["channel_id"]]
            channel["identity"].update(status="CONNECTED", remote_channel_id=item["remote_channel_id"],
                                       channel_title=item["channel_title"])
            channel["onboarding_status"] = "NEW CHANNEL" if not channel["youtube_learning"].get("publication_history") else "ACTIVE CHANNEL"
            channel["youtube_learning"]["analytics"].update(source="NOT_CONNECTED", status="ANALYTICS INSUFFICIENT")
        self.store.update(mutate); return self._redact(item)

    def verify(self, account_id: str) -> dict:
        raw = self._raw(account_id); result = self.provider.verify(raw["credential_ref"])
        def mutate(state):
            item = next(x for x in state["account_assignments"] if x["account_id"] == account_id)
            item.update(connection_status=result["status"], last_verified_at=result.get("last_verified_at"))
            state["channels"][item["channel_id"]]["identity"]["status"] = result["status"]
            if result.get("remote_channel_id") != item["remote_channel_id"]:
                item["connection_status"] = "BLOCKED_SCOPE_MISMATCH"
        self.store.update(mutate); return self._redact(self._raw(account_id))

    def disconnect(self, account_id: str) -> dict:
        raw = self._raw(account_id); self.provider.disconnect(raw["credential_ref"])
        def mutate(state):
            item = next(x for x in state["account_assignments"] if x["account_id"] == account_id)
            item.update(connection_status="NOT_CONNECTED", credential_ref="", last_verified_at=utc_now())
            state["channels"][item["channel_id"]]["identity"].update(status="NOT_CONNECTED")
        self.store.update(mutate); return self._redact(self._raw(account_id))

    def ingest_analytics(self, account_id: str, *, start_date: str, end_date: str) -> dict:
        raw = self._raw(account_id)
        if raw.get("connection_status") != "CONNECTED": raise RuntimeError("ACCOUNT_REAUTH_REQUIRED")
        result = self.provider.analytics(raw["credential_ref"], start_date=start_date, end_date=end_date)
        def mutate(state):
            analytics = state["channels"][raw["channel_id"]]["youtube_learning"]["analytics"]
            analytics.update(source=result["source"], status=result["status"],
                             metrics_returned=result.get("metrics_returned", []), fetched_at=result.get("fetched_at"))
            analytics.setdefault("records", []).extend(result.get("rows", []))
        self.store.update(mutate); return result

    def assert_scope(self, *, worker_id: str, channel_id: str, account_id: str,
                     artifact_channel_id: str, authorized_remote_channel: str | None = None) -> dict:
        account = self._raw(account_id)
        values_match = (account["assigned_worker_id"] == worker_id and account["channel_id"] == channel_id
                        and artifact_channel_id == channel_id and account["connection_status"] == "CONNECTED")
        if authorized_remote_channel is not None:
            values_match = values_match and account["remote_channel_id"] == authorized_remote_channel
        if not values_match: raise RuntimeError("BLOCKED — ACCOUNT/CHANNEL SCOPE MISMATCH")
        return account

    def _raw(self, account_id: str) -> dict:
        item = next((x for x in self.store.snapshot().get("account_assignments", []) if x.get("account_id") == account_id), None)
        if item is None: raise KeyError("Account not found")
        return item

    @staticmethod
    def _redact(item: dict | None) -> dict | None:
        if item is None: return None
        safe = {k: v for k, v in item.items() if k != "credential_ref"}
        safe["credential_status"] = "STORED_SECURELY" if item.get("credential_ref") else "NOT_STORED"
        return safe
