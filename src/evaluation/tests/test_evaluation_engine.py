from __future__ import annotations

import pytest

from src.evaluation.criteria import (
    activity_score,
    architecture_score,
    community_score,
    compatibility_score,
    license_score,
    maintenance_score,
    security_score,
)
from src.evaluation.evaluation_engine import WEIGHTS, EvaluationEngine
from src.evaluation.models import RepoEvaluation
from src.evaluation.relevance import is_generic_repo, relevance_score
from src.github.errors import GitHubIntelligenceError
from src.github.github_intelligence import GitHubIntelligence
from src.github.models import RepoData


def _repo(**overrides) -> RepoData:
    base = dict(
        name="sample-toolkit",
        full_name="octocat/sample-toolkit",
        url="https://github.com/octocat/sample-toolkit",
        description=(
            "An open-source AI agent framework and SDK with a clean API and "
            "CLI for building autonomous multi-agent workflows."
        ),
        stars=5000,
        forks=300,
        license="mit",
        last_update="2026-08-01T10:00:00Z",
        language="Python",
        category="ai agent",
        open_issues=10,
        archived=False,
        contributors_count=25,
        topics=["agent", "ai", "framework"],
    )
    base.update(overrides)
    return RepoData(**base)


ALL_CRITERIA = [
    architecture_score, activity_score, community_score, license_score,
    security_score, compatibility_score, maintenance_score, relevance_score,
]


# --- Kriter fonksiyonları: sınır ve yön testleri ------------------------------


class TestCriteriaBounds:
    @pytest.mark.parametrize("criterion", ALL_CRITERIA)
    def test_score_within_0_100_for_strong_repo(self, criterion):
        assert 0.0 <= criterion(_repo()) <= 100.0

    @pytest.mark.parametrize("criterion", ALL_CRITERIA)
    def test_score_within_0_100_for_weak_repo(self, criterion):
        weak = _repo(
            stars=0, forks=0, license="", description="", language="",
            last_update="2015-01-01T00:00:00Z", contributors_count=0,
            archived=True, open_issues=500,
        )
        assert 0.0 <= criterion(weak) <= 100.0

    def test_python_scores_higher_compatibility_than_unknown_language(self):
        python_repo = _repo(language="Python")
        unknown_repo = _repo(language="COBOL")
        assert compatibility_score(python_repo) > compatibility_score(unknown_repo)

    def test_archived_repo_has_capped_low_maintenance(self):
        archived = _repo(archived=True, contributors_count=50)
        assert maintenance_score(archived) == 15.0

    def test_permissive_license_beats_unclear_license(self):
        assert license_score(_repo(license="mit")) > license_score(_repo(license=""))

    def test_stale_repo_has_lower_activity_than_fresh_repo(self):
        fresh = _repo(last_update="2026-08-03T00:00:00Z")
        stale = _repo(last_update="2018-01-01T00:00:00Z")
        assert activity_score(fresh) > activity_score(stale)


# --- EvaluationEngine.evaluate() ----------------------------------------------


class TestEvaluate:
    def setup_method(self):
        self.engine = EvaluationEngine()

    def test_returns_repo_evaluation_with_all_fields(self):
        result = self.engine.evaluate(_repo())
        assert isinstance(result, RepoEvaluation)
        assert result.name == "sample-toolkit"
        assert result.url.startswith("https://github.com/")
        for score in (
            result.overall_score, result.architecture_score, result.activity_score,
            result.community_score, result.license_score, result.security_score,
            result.compatibility_score, result.maintenance_score, result.relevance_score,
        ):
            assert 0.0 <= score <= 100.0

    def test_strong_repo_is_low_risk_and_suitable(self):
        result = self.engine.evaluate(_repo())
        assert result.risk_level == "LOW"
        assert result.suitable_for_jarvis is True
        assert "ÖNERİLİR" in result.recommendation

    def test_archived_repo_is_high_risk_and_unsuitable(self):
        result = self.engine.evaluate(_repo(archived=True))
        assert result.risk_level == "HIGH"
        assert result.suitable_for_jarvis is False

    def test_unclear_license_is_high_risk(self):
        result = self.engine.evaluate(_repo(license=""))
        assert result.risk_level == "HIGH"

    def test_known_category_maps_to_real_module(self):
        result = self.engine.evaluate(_repo(category="browser agent"))
        assert result.target_module == "src/agents/browser_agent.py"

    def test_unknown_category_maps_to_unknown_module(self):
        result = self.engine.evaluate(_repo(category="not a real category"))
        assert "Bilinmiyor" in result.target_module

    def test_non_python_language_lowers_compatibility_and_raises_difficulty(self):
        python_eval = self.engine.evaluate(_repo(language="Python"))
        java_eval = self.engine.evaluate(_repo(language="Java", description=""))
        assert java_eval.compatibility_score < python_eval.compatibility_score
        assert java_eval.integration_difficulty in ("Orta", "Yüksek")

    def test_overall_score_is_weighted_average_of_sub_scores(self):
        repo = _repo()
        result = self.engine.evaluate(repo)
        expected = (
            WEIGHTS["relevance_score"] * relevance_score(repo)
            + WEIGHTS["architecture_score"] * architecture_score(repo)
            + WEIGHTS["activity_score"] * activity_score(repo)
            + WEIGHTS["community_score"] * community_score(repo)
            + WEIGHTS["license_score"] * license_score(repo)
            + WEIGHTS["security_score"] * security_score(repo)
            + WEIGHTS["compatibility_score"] * compatibility_score(repo)
            + WEIGHTS["maintenance_score"] * maintenance_score(repo)
        )
        assert result.overall_score == round(expected, 1)


# --- Sprint 10.1: relevance_score / "genel repo" reddi -------------------------


class TestRelevanceGating:
    def setup_method(self):
        self.engine = EvaluationEngine()

    def test_weights_sum_to_one(self):
        assert round(sum(WEIGHTS.values()), 6) == 1.0

    def test_relevance_score_is_the_single_highest_weight(self):
        assert WEIGHTS["relevance_score"] == max(WEIGHTS.values())

    def test_awesome_python_capped_low_relevance_regardless_of_category(self):
        # Bilinen hata: awesome-python, browser/video/finance modülü için
        # önerilmemeli — hangi kategoride arandığı önemli değil, "awesome"
        # isim deseni tek başına yeterli.
        for category in ("browser agent", "video generation", "finance ai"):
            repo = _repo(
                name="awesome-python",
                description="A curated list of awesome Python frameworks, libraries and resources.",
                category=category,
                stars=250000,
                license="",
            )
            assert is_generic_repo(repo) is True
            result = self.engine.evaluate(repo)
            assert result.relevance_score <= 15.0
            assert result.suitable_for_jarvis is False
            assert "REDDET" in result.recommendation

    def test_developer_roadmap_is_rejected(self):
        repo = _repo(
            name="developer-roadmap",
            description="Interactive roadmaps, guides and other educational content to help developers grow.",
            category="ai agent",
            stars=300000,
        )
        assert is_generic_repo(repo) is True
        result = self.engine.evaluate(repo)
        assert result.suitable_for_jarvis is False
        assert "REDDET" in result.recommendation

    def test_irrelevant_mcp_result_does_not_score_high(self):
        # xberg benzeri: farklı bir alanda (belge zekası), "mcp server"
        # sorgusuyla gerçekte ilgisiz bir repo.
        unrelated = _repo(
            name="xberg",
            description=(
                "A polyglot document intelligence framework with a Rust core. "
                "Extract text, metadata, images and structured data from 101 formats."
            ),
            topics=["document-intelligence", "pdf-extraction", "metadata-extraction"],
            category="mcp server",
            language="Rust",
            stars=8896,
            license="mit",
        )
        result = self.engine.evaluate(unrelated)
        assert result.relevance_score < 60.0
        assert result.suitable_for_jarvis is False

    def test_genuinely_relevant_mcp_repo_scores_high_relevance(self):
        fastmcp = _repo(
            name="fastmcp",
            description="The fast, Pythonic way to build MCP servers and clients.",
            topics=["mcp", "mcp-server", "mcp-client", "model-context-protocol", "python"],
            category="mcp server",
            language="Python",
            license="apache-2.0",
            stars=27000,
        )
        result = self.engine.evaluate(fastmcp)
        assert result.relevance_score >= 60.0
        assert result.suitable_for_jarvis is True

    def test_low_relevance_excluded_from_top_candidates_even_with_high_overall(self):
        irrelevant_but_popular = _repo(
            name="public-apis",
            description="A collective list of free APIs for use in software and web development.",
            category="mcp server",
            stars=300000,
            license="mit",
            contributors_count=500,
        )
        relevant_but_smaller = _repo(
            name="fastmcp",
            description="The fast, Pythonic way to build MCP servers and clients.",
            topics=["mcp", "mcp-server", "mcp-client", "model-context-protocol"],
            category="mcp server",
            stars=5000,
            license="apache-2.0",
            contributors_count=20,
        )
        evaluations = self.engine.evaluate_many([irrelevant_but_popular, relevant_but_smaller])

        # public-apis muhtemelen ham kriterlerde (topluluk, lisans, aktiflik)
        # daha yüksek puan alır ama alakasız olduğu için elenmeli.
        top = self.engine.top_candidates(evaluations, limit=5)
        assert "public-apis" not in [e.name for e in top]
        assert "fastmcp" in [e.name for e in top]

    def test_relevance_score_uses_topics_signal(self):
        no_topics = _repo(
            name="ambiguous",
            description="A general purpose tool.",
            topics=[],
            category="mcp server",
        )
        with_matching_topics = _repo(
            name="ambiguous",
            description="A general purpose tool.",
            topics=["mcp", "mcp-server", "model-context-protocol"],
            category="mcp server",
        )
        assert relevance_score(with_matching_topics) > relevance_score(no_topics)

    def test_relevance_score_uses_readme_when_available(self):
        without_readme = _repo(category="mcp server", description="", topics=[], name="thing")
        with_readme = _repo(
            category="mcp server", description="", topics=[], name="thing",
            readme_excerpt="This project supports MCP servers and provides a client for tool context.",
        )
        assert relevance_score(with_readme) > relevance_score(without_readme)


# --- summary() / top_candidates() ---------------------------------------------


class TestSummaryAndTopCandidates:
    def setup_method(self):
        self.engine = EvaluationEngine()
        self.repos = [
            _repo(
                name="strong", category="browser agent", stars=50000, contributors_count=40,
                description="An open-source browser automation agent using Playwright to navigate and scrape the web.",
                topics=["browser-automation", "playwright", "agent"],
            ),
            _repo(
                name="mediocre", category="llm", stars=200, license="gpl-3.0", contributors_count=2,
                description="A small experimental language model inference library for local LLM serving.",
                topics=["llm", "inference"],
            ),
            _repo(
                name="archived-one", category="mcp server", archived=True,
                description="An MCP server implementation exposing tools and context to language model clients.",
                topics=["mcp", "mcp-server"],
            ),
        ]
        self.evaluations = self.engine.evaluate_many(self.repos)

    def test_evaluate_many_returns_one_per_repo(self):
        assert len(self.evaluations) == 3

    def test_summary_empty_list(self):
        summary = self.engine.summary([])
        assert summary["count"] == 0
        assert summary["risk_distribution"] == {"LOW": 0, "MEDIUM": 0, "HIGH": 0}

    def test_summary_counts_match(self):
        summary = self.engine.summary(self.evaluations)
        assert summary["count"] == 3
        assert sum(summary["risk_distribution"].values()) == 3
        assert summary["suitable_count"] == sum(1 for e in self.evaluations if e.suitable_for_jarvis)

    def test_top_candidates_sorted_by_overall_score_desc(self):
        top = self.engine.top_candidates(self.evaluations, limit=10, only_suitable=False)
        scores = [e.overall_score for e in top]
        assert scores == sorted(scores, reverse=True)

    def test_top_candidates_respects_limit(self):
        top = self.engine.top_candidates(self.evaluations, limit=1, only_suitable=False)
        assert len(top) == 1

    def test_top_candidates_excludes_unsuitable_by_default(self):
        top = self.engine.top_candidates(self.evaluations)
        assert all(e.suitable_for_jarvis for e in top)
        assert "archived-one" not in [e.name for e in top]


# --- Gerçek GitHubIntelligence ile birlikte çalışma (entegrasyon) ------------


class TestWorksWithRealGitHubIntelligence:
    """GitHubIntelligence'ın KODUNU DEĞİŞTİRMEDEN, gerçek çıktısıyla
    EvaluationEngine'in sorunsuz çalıştığını doğrular. Ağ erişimi yoksa
    test atlanır (skip), başarısız SAYILMAZ."""

    def test_evaluate_many_on_real_search_results(self):
        gi = GitHubIntelligence(fetch_contributors=False)
        engine = EvaluationEngine()

        try:
            repos = gi.search("mcp server", max_results=5)
        except GitHubIntelligenceError as error:
            pytest.skip(f"GitHub API'ye ulaşılamadı: {error}")

        if not repos:
            pytest.skip("GitHub araması boş sonuç döndürdü (geçici olabilir).")

        evaluations = engine.evaluate_many(repos)
        assert len(evaluations) == len(repos)

        for evaluation in evaluations:
            assert 0.0 <= evaluation.overall_score <= 100.0
            assert evaluation.risk_level in ("LOW", "MEDIUM", "HIGH")
            assert evaluation.target_module  # boş olmamalı

        summary = engine.summary(evaluations)
        assert summary["count"] == len(repos)

        top = engine.top_candidates(evaluations, limit=3, only_suitable=False)
        assert len(top) <= 3
