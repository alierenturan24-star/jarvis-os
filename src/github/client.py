from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from src.github.errors import GitHubIntelligenceError, GitHubRateLimitError

GITHUB_API_URL = "https://api.github.com"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3
MAX_RATE_LIMIT_WAIT_SECONDS = 90


class GitHubClient:
    """GitHub REST API için ince, salt-okunur (read-only) HTTP istemcisi.

    Yalnızca arama ve repo/katkıcı meta verisi çeker. Rate limit'e
    (birincil ve ikincil/"abuse") ve geçici ağ hatalarına karşı otomatik
    bekleme/yeniden deneme uygular. Klonlama/indirme İÇERMEZ.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN", "").strip()
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "jarvis-os-github-intelligence",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict:
        """GET isteği yapıp JSON gövdeyi döndürür."""

        response = self._request(path, params)
        try:
            return response.json()
        except ValueError as error:
            raise GitHubIntelligenceError(f"GitHub yanıtı çözümlenemedi: {error}") from error

    def get_contributor_count(self, full_name: str) -> Optional[int]:
        """Bir reponun (yaklaşık) katkıcı sayısını döndürür.

        GitHub'ın sayfalama (``Link``) başlığındaki son sayfa numarasından
        yararlanır (``per_page=1`` ile tek bir istek yeterli olur). Repo
        çok büyükse, erişim kısıtlıysa veya rate limit'e takılırsa akışı
        KESMEZ — ``None`` döner (risk puanlamasında opsiyonel alan).
        """

        if not full_name:
            return None

        try:
            response = self._request(
                f"/repos/{full_name}/contributors",
                params={"per_page": 1, "anon": "true"},
            )
        except GitHubIntelligenceError:
            return None

        link = response.headers.get("Link", "")
        if 'rel="last"' in link:
            for part in link.split(","):
                if 'rel="last"' in part:
                    try:
                        url_part = part.split(";")[0].strip().strip("<>")
                        page = url_part.split("page=")[-1].split("&")[0]
                        return int(page)
                    except (ValueError, IndexError):
                        return None

        try:
            data = response.json()
        except ValueError:
            return None

        return len(data) if isinstance(data, list) else None

    def get_readme_excerpt(self, full_name: str, max_chars: int = 800) -> Optional[str]:
        """Bir reponun README'sinin ilk ``max_chars`` karakterini döndürür
        (yalnızca değerlendirme/alaka analizi için okunur — klonlama/indirme
        DEĞİLDİR). README yoksa, çözümlenemezse veya rate limit/hata
        oluşursa akışı KESMEZ — ``None`` döner (opsiyonel sinyal)."""

        if not full_name:
            return None

        cache_key = full_name.casefold()
        if self._owns_session and cache_key in self._readme_cache:
            cached = self._readme_cache[cache_key]
            return cached[:max_chars] if cached else None

        try:
            payload = self.get(f"/repos/{full_name}/readme")
        except GitHubIntelligenceError:
            payload = None

        content_b64 = str(payload.get("content", "")) if isinstance(payload, dict) else ""
        if not content_b64:
            if not self._owns_session:
                return None
            # Public raw content is free and does not consume the GitHub REST
            # API quota.  Try the two conventional default branches once.
            for branch in ("main", "master"):
                try:
                    response = self.session.get(
                        f"https://raw.githubusercontent.com/{full_name}/{branch}/README.md",
                        headers={"User-Agent": "jarvis-os-public-readme"},
                        timeout=min(self.timeout, 5),
                    )
                    if 200 <= response.status_code < 300 and response.text.strip():
                        raw = response.text.strip()
                        type(self)._readme_cache[cache_key] = raw
                        return raw[:max_chars]
                except requests.exceptions.RequestException:
                    continue
            type(self)._readme_cache[cache_key] = None
            return None

        try:
            raw = base64.b64decode(content_b64, validate=False).decode("utf-8", errors="ignore")
        except (ValueError, TypeError):
            return None

        raw = raw.strip()
        if self._owns_session:
            type(self)._readme_cache[cache_key] = raw or None
        return raw[:max_chars] if raw else None

    # --- Dahili -------------------------------------------------------------

    def _request(self, path: str, params: Optional[dict[str, Any]] = None) -> requests.Response:
        """GET isteği yapar; başarılı (2xx) ham ``Response`` nesnesini
        döndürür. Rate limit'te bekleyip yeniden dener; geçici ağ/sunucu
        hatalarında üstel geri çekilmeyle (en fazla ``MAX_RETRIES`` kez)
        yeniden dener; kalıcı hatalarda ``GitHubIntelligenceError``
        fırlatır."""

        url = path if path.startswith("http") else f"{GITHUB_API_URL}{path}"
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com" or parsed.username or parsed.password or parsed.port:
            raise GitHubIntelligenceError("GitHub GET hedefi canonical API trust boundary disinda")
        if self._owns_session and time.time() < type(self)._api_rate_limited_until:
            remaining = type(self)._api_rate_limited_until - time.time()
            raise GitHubRateLimitError(
                f"GitHub API rate limit aktif; aynı çağrı tekrar denenmedi ({remaining:.0f} sn)."
            )
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                request_options = {"headers": self._headers(), "params": params, "timeout": self.timeout}
                # requests follows redirects by default. Production traffic must never
                # leave api.github.com; lightweight injected test transports predate
                # this option and do not perform redirects themselves.
                if isinstance(self.session, requests.Session):
                    request_options["allow_redirects"] = False
                response = self.session.get(url, **request_options)
            except requests.exceptions.RequestException as error:
                last_error = error
                time.sleep(min(2 ** attempt, 10))
                continue

            if 200 <= response.status_code < 300:
                return response

            if 300 <= response.status_code < 400:
                raise GitHubIntelligenceError("GitHub redirect reddedildi; untrusted hedef takip edilmedi")

            if response.status_code in (403, 429) and self._is_rate_limited(response):
                self._wait_for_rate_limit(response)
                continue

            if response.status_code == 404:
                raise GitHubIntelligenceError(f"Kaynak bulunamadı: {url}")

            if response.status_code == 401:
                raise GitHubIntelligenceError(
                    "GitHub kimlik doğrulaması başarısız (401). GITHUB_TOKEN'ı kontrol edin."
                )

            if response.status_code == 422:
                raise GitHubIntelligenceError(
                    f"Geçersiz istek (422): {self._error_message(response)}"
                )

            last_error = GitHubIntelligenceError(
                f"GitHub API hatası ({response.status_code}): {self._error_message(response)}"
            )
            time.sleep(min(2 ** attempt, 10))

        if isinstance(last_error, GitHubIntelligenceError):
            raise last_error
        raise GitHubIntelligenceError(f"GitHub API'ye ulaşılamadı: {last_error}")

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            return str(response.json().get("message", response.text))
        except ValueError:
            return response.text[:200]

    @staticmethod
    def _is_rate_limited(response: requests.Response) -> bool:
        if response.headers.get("Retry-After") is not None:
            return True

        if response.headers.get("X-RateLimit-Remaining") == "0":
            return True

        try:
            message = str(response.json().get("message", "")).lower()
        except ValueError:
            message = ""

        return "rate limit" in message or "abuse" in message

    def _wait_for_rate_limit(self, response: requests.Response) -> None:
        retry_after = response.headers.get("Retry-After")

        if retry_after is not None:
            wait_seconds = float(retry_after)
        else:
            reset_header = response.headers.get("X-RateLimit-Reset")
            if reset_header is not None:
                reset_at = datetime.fromtimestamp(int(reset_header), tz=timezone.utc)
                wait_seconds = max(0.0, (reset_at - datetime.now(timezone.utc)).total_seconds())
            else:
                wait_seconds = 5.0

        if wait_seconds > MAX_RATE_LIMIT_WAIT_SECONDS:
            if self._owns_session:
                type(self)._api_rate_limited_until = time.time() + wait_seconds
            raise GitHubRateLimitError(
                "GitHub API rate limit'e takıldı; bekleme süresi çok uzun "
                f"({wait_seconds:.0f} sn). Daha sonra tekrar deneyin veya GITHUB_TOKEN tanımlayın."
            )

        time.sleep(wait_seconds + 1)
    # One mission constructs several department clients.  Share the API
    # circuit state and public README cache so a known rate limit is not hit
    # again by every department.
    _api_rate_limited_until: float = 0.0
    _readme_cache: dict[str, Optional[str]] = {}
