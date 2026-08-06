from __future__ import annotations

import time

import pytest
import requests

from src.github.categories import SUPPORTED_CATEGORIES
from src.github.client import GitHubClient
from src.github.errors import GitHubIntelligenceError, GitHubRateLimitError
from src.github.github_intelligence import MAX_DESCRIPTION_LENGTH, GitHubIntelligence
from src.github.models import RepoData
from src.github.scoring import build_reason, quality_score, risk_score


def _repo(**overrides) -> RepoData:
    base = dict(
        name="sample-toolkit",
        full_name="octocat/sample-toolkit",
        url="https://github.com/octocat/sample-toolkit",
        description="A well documented AI agent framework for browser automation.",
        stars=5000,
        forks=300,
        license="mit",
        last_update="2026-07-20T10:00:00Z",
        language="Python",
        category="ai agent",
        open_issues=10,
        archived=False,
        contributors_count=25,
    )
    base.update(overrides)
    return RepoData(**base)


# --- Puanlama --------------------------------------------------------------


class TestScoring:
    def test_high_quality_repo_scores_high(self):
        assert quality_score(_repo()) >= 70

    def test_stale_unlicensed_repo_scores_low_quality(self):
        repo = _repo(license="", last_update="2020-01-01T00:00:00Z", description="")
        assert quality_score(repo) < 40

    def test_stale_unlicensed_repo_has_high_risk(self):
        repo = _repo(last_update="2019-01-01T00:00:00Z", license="", contributors_count=1)
        assert risk_score(repo) >= 60

    def test_active_well_licensed_repo_has_low_risk(self):
        assert risk_score(_repo()) <= 20

    def test_archived_repo_penalized_in_both_scores(self):
        active = _repo()
        archived = _repo(archived=True)
        assert quality_score(archived) < quality_score(active)
        assert risk_score(archived) > risk_score(active)

    def test_experimental_keyword_raises_risk(self):
        normal = _repo()
        experimental = _repo(name="experimental-agent", description="An experimental proof of concept.")
        assert risk_score(experimental) > risk_score(normal)

    def test_build_reason_mentions_scores(self):
        reason = build_reason(_repo(), 80.0, 10.0)
        assert "80" in reason
        assert "10" in reason


# --- Filtreleme --------------------------------------------------------------


class TestFilter:
    def setup_method(self):
        self.gi = GitHubIntelligence(fetch_contributors=False)

    def test_filters_by_min_stars(self):
        repos = [_repo(stars=10), _repo(stars=10000)]
        filtered = self.gi.filter(repos, min_stars=1000)
        assert len(filtered) == 1
        assert filtered[0].stars == 10000

    def test_excludes_archived_by_default(self):
        repos = [_repo(archived=True), _repo(archived=False)]
        filtered = self.gi.filter(repos)
        assert len(filtered) == 1
        assert filtered[0].archived is False

    def test_requires_license_when_asked(self):
        repos = [_repo(license=""), _repo(license="mit")]
        filtered = self.gi.filter(repos, require_license=True)
        assert len(filtered) == 1
        assert filtered[0].license == "mit"


# --- Kategori doğrulama ------------------------------------------------------


class TestSearchValidation:
    def test_unsupported_category_raises(self):
        gi = GitHubIntelligence(fetch_contributors=False)
        with pytest.raises(GitHubIntelligenceError):
            gi.search("not a real category")

    def test_all_ten_categories_supported(self):
        expected = {
            "youtube automation", "browser agent", "ai agent", "finance ai",
            "trading bot", "voice ai", "video generation", "image generation",
            "llm", "mcp server",
        }
        assert expected == set(SUPPORTED_CATEGORIES)
        assert len(SUPPORTED_CATEGORIES) == 10


# --- GitHubClient: rate limit / hata yönetimi (sahte session ile) ------------


class _FakeResponse:
    def __init__(self, status_code, headers=None, json_data=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data if json_data is not None else {}
        self.text = text or str(self._json_data)

    def json(self):
        return self._json_data


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


class TestClientRateLimitHandling:
    def test_waits_then_retries_on_primary_rate_limit(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("src.github.client.time.sleep", lambda s: sleeps.append(s))

        rate_limited = _FakeResponse(
            403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + 2),
            },
            json_data={"message": "API rate limit exceeded"},
        )
        ok = _FakeResponse(200, json_data={"items": []})
        session = _FakeSession([rate_limited, ok])

        client = GitHubClient(session=session)
        result = client.get("/search/repositories", params={"q": "llm"})

        assert result == {"items": []}
        assert session.calls == 2
        assert sleeps

    def test_raises_rate_limit_error_when_wait_too_long(self, monkeypatch):
        monkeypatch.setattr("src.github.client.time.sleep", lambda s: None)

        far_future = _FakeResponse(
            403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + 100_000),
            },
            json_data={"message": "API rate limit exceeded"},
        )
        client = GitHubClient(session=_FakeSession([far_future]))

        with pytest.raises(GitHubRateLimitError):
            client.get("/search/repositories", params={"q": "llm"})

    def test_retries_on_transient_network_error_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("src.github.client.time.sleep", lambda s: None)

        class FlakySession:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise requests.exceptions.ConnectionError("boom")
                return _FakeResponse(200, json_data={"ok": True})

        session = FlakySession()
        client = GitHubClient(session=session)

        assert client.get("/rate_limit") == {"ok": True}
        assert session.calls == 2

    def test_404_raises_clear_error_without_infinite_retry(self, monkeypatch):
        monkeypatch.setattr("src.github.client.time.sleep", lambda s: None)
        session = _FakeSession([_FakeResponse(404, json_data={"message": "Not Found"})])
        client = GitHubClient(session=session)

        with pytest.raises(GitHubIntelligenceError):
            client.get("/repos/does/not-exist")

        assert session.calls == 1  # 404 hemen fırlatılır, tekrar denenmez


# --- Sprint 10.1: açıklama sınırlama, topics, README özeti -------------------


class TestRepoDataHygiene:
    def _item(self, **overrides) -> dict:
        base = dict(
            name="sample",
            full_name="octocat/sample",
            html_url="https://github.com/octocat/sample",
            description="A normal description.",
            stargazers_count=10,
            forks_count=1,
            license={"spdx_id": "MIT"},
            pushed_at="2026-08-01T00:00:00Z",
            language="Python",
            open_issues_count=0,
            archived=False,
            topics=["mcp", "python", "server"],
        )
        base.update(overrides)
        return base

    def test_topics_are_captured(self):
        repo = GitHubIntelligence._to_repo_data(self._item(), category="mcp server")
        assert repo.topics == ["mcp", "python", "server"]

    def test_missing_topics_defaults_to_empty_list(self):
        item = self._item()
        item.pop("topics")
        repo = GitHubIntelligence._to_repo_data(item, category="mcp server")
        assert repo.topics == []

    def test_abnormally_long_description_is_truncated(self):
        huge = "Skip to content github / docs Code Issues " * 500  # ~21.000 karakter
        repo = GitHubIntelligence._to_repo_data(
            self._item(description=huge), category="mcp server"
        )
        assert len(repo.description) <= MAX_DESCRIPTION_LENGTH + 1  # + "…"
        assert repo.description.endswith("…")

    def test_normal_description_is_untouched(self):
        repo = GitHubIntelligence._to_repo_data(self._item(), category="mcp server")
        assert repo.description == "A normal description."

    def test_readme_excerpt_defaults_to_none(self):
        repo = GitHubIntelligence._to_repo_data(self._item(), category="mcp server")
        assert repo.readme_excerpt is None


class TestGetReadmeExcerpt:
    def test_decodes_base64_content_and_truncates(self, monkeypatch):
        import base64

        raw_markdown = "# Sample\n\nThis project supports MCP servers and clients." + ("x" * 2000)
        encoded = base64.b64encode(raw_markdown.encode("utf-8")).decode("ascii")
        session = _FakeSession([_FakeResponse(200, json_data={"content": encoded, "encoding": "base64"})])
        client = GitHubClient(session=session)

        excerpt = client.get_readme_excerpt("octocat/sample", max_chars=50)

        assert excerpt is not None
        assert len(excerpt) == 50
        assert excerpt.startswith("# Sample")

    def test_missing_readme_returns_none_without_raising(self, monkeypatch):
        monkeypatch.setattr("src.github.client.time.sleep", lambda s: None)
        session = _FakeSession([_FakeResponse(404, json_data={"message": "Not Found"})])
        client = GitHubClient(session=session)

        assert client.get_readme_excerpt("octocat/does-not-exist") is None

    def test_empty_full_name_returns_none(self):
        client = GitHubClient(session=_FakeSession([]))
        assert client.get_readme_excerpt("") is None


# --- Uçtan uca (gerçek GitHub API'ye karşı) -----------------------------------


class TestRecommendIntegration:
    """Gerçek GitHub API'ye karşı çalışan entegrasyon testi. Amaç mock
    değil, gerçek API sözleşmesini doğrulamaktır; ağ erişimi yoksa veya
    geçici bir hata olursa test atlanır (skip), başarısız SAYILMAZ."""

    def test_recommend_returns_ranked_recommendations(self):
        gi = GitHubIntelligence(fetch_contributors=False)

        try:
            recommendations = gi.recommend("llm", max_results=5)
        except GitHubIntelligenceError as error:
            pytest.skip(f"GitHub API'ye ulaşılamadı: {error}")

        if not recommendations:
            pytest.skip("GitHub araması boş sonuç döndürdü (geçici olabilir).")

        assert len(recommendations) <= 5
        scores = [rec.quality_score for rec in recommendations]
        assert scores == sorted(scores, reverse=True)

        for rec in recommendations:
            assert rec.url.startswith("https://github.com/")
            assert 0 <= rec.quality_score <= 100
            assert 0 <= rec.risk_score <= 100
