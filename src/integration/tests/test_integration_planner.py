from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.evaluation.evaluation_engine import EvaluationEngine
from src.evaluation.models import RepoEvaluation
from src.evaluation.module_map import CATEGORY_TARGET_MODULE
from src.github.github_intelligence import GitHubIntelligence
from src.integration.integration_planner import IntegrationPlanner
from src.integration.models import Conflict, IntegrationPlan
from src.sandbox.models import SandboxMode, SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager


def _evaluation(**overrides) -> RepoEvaluation:
    base = dict(
        name="octocat/sample-repo",
        url="https://github.com/octocat/sample-repo",
        overall_score=85.0,
        architecture_score=80.0,
        activity_score=80.0,
        community_score=90.0,
        license_score=100.0,
        security_score=90.0,
        compatibility_score=100.0,
        maintenance_score=80.0,
        relevance_score=85.0,
        recommendation="ÖNERİLİR",
        suitable_for_jarvis=True,
        target_module="src/agents/browser_agent.py",
        integration_difficulty="Düşük",
        risk_level="LOW",
    )
    base.update(overrides)
    return RepoEvaluation(**base)


def _sandbox_result(**overrides) -> SandboxResult:
    base = dict(
        repository_name="octocat/sample-repo",
        repository_url="https://github.com/octocat/sample-repo",
        sandbox_path=None,
        status=SandboxStatus.READY_FOR_REVIEW,
        mode=SandboxMode.STATIC_ANALYSIS,
        files_scanned=10,
        total_size_mb=0.5,
        detected_language="Python",
        detected_manifests=["requirements.txt"],
        detected_install_commands=["pip install -r requirements.txt"],
        detected_test_commands=["pytest"],
        suspicious_files=[],
        suspicious_patterns=[],
        network_risk="LOW",
        execution_risk="LOW",
        dependency_risk="LOW",
        license_detected="MIT License",
        findings=[],
        recommended_action="STATIC_ANALYSIS tamamlandı.",
        error=None,
    )
    base.update(overrides)
    return SandboxResult(**base)


def _fixture_repo(tmp_path: Path, **files: str) -> str:
    for relative_path, content in files.items():
        full_path = tmp_path / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    return str(tmp_path)


# --- 1 & 2) Gerçek repolar üzerinden uçtan uca plan üretimi -------------------


class TestRealRepositoryPlans:
    """GitHubIntelligence → EvaluationEngine → SandboxManager →
    IntegrationPlanner zincirini deterministic API/clone fixtures ile çalıştırır."""

    def _first_suitable(self, query: str, monkeypatch):
        slug = "browser-fixture" if "browser" in query else "trading-fixture"
        deterministic = {"items": [{"name": slug, "full_name": f"fixture/{slug}",
            "html_url": f"https://github.com/fixture/{slug}",
            "description": f"Python {query} API framework with browser automation trading strategy tools",
            "stargazers_count": 10000, "forks_count": 1000, "license": {"spdx_id": "MIT"},
            "pushed_at": "2026-08-19T00:00:00Z", "language": "Python", "open_issues_count": 1,
            "archived": False, "topics": query.split()}]}
        monkeypatch.setattr("src.github.client.GitHubClient.get", lambda self, path, params=None: deterministic)
        gi = GitHubIntelligence(fetch_contributors=False)
        engine = EvaluationEngine()
        payload = gi.client.get(
            "/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 10},
        )

        items = payload.get("items", [])
        repos = [GitHubIntelligence._to_repo_data(item, category=query) for item in items[:10]]
        evaluations = engine.evaluate_many(repos)

        candidates = sorted(
            [(r, e) for r, e in zip(repos, evaluations) if e.suitable_for_jarvis],
            key=lambda pair: pair[0].stars,
        )
        assert candidates, f"deterministic fixture for {query!r} must be suitable"
        return candidates[0]

    def _plan_for_query(self, query: str, tmp_path: Path, monkeypatch) -> IntegrationPlan:
        repo, evaluation = self._first_suitable(query, monkeypatch)
        source = tmp_path / ("fixture-" + query.split()[0])
        _fixture_repo(source, **{"README.md": f"# {query}\n", "requirements.txt": "requests==2.32.0\n",
                                 "LICENSE": "MIT License\n", "src/tool.py": "def run():\n    return True\n"})
        clone_calls = []

        def fake_git_clone(command, **kwargs):
            assert command[0] == "git" and "clone" in command and command[-2] == repo.url
            clone_calls.append(list(command))
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("src.sandbox.sandbox_manager.subprocess.run", fake_git_clone)
        monkeypatch.setattr("socket.create_connection", lambda *a, **k: pytest.fail("network access attempted"))
        manager = SandboxManager(max_repo_size_mb=20.0, max_files=3000, clone_timeout_seconds=60)
        sandbox_result = manager.run_pipeline(repo.url, evaluation, repo=repo)
        assert len(clone_calls) == 1

        assert sandbox_result.status == SandboxStatus.READY_FOR_REVIEW, sandbox_result.error

        try:
            planner = IntegrationPlanner()
            plan = planner.analyze(sandbox_result, evaluation)
        finally:
            cleaned = manager.cleanup(sandbox_result)
            assert cleaned.status == SandboxStatus.CLEANED
            assert not Path(sandbox_result.sandbox_path).exists()

        return plan

    def test_real_browser_repo_produces_plan(self, tmp_path, monkeypatch):
        plan = self._plan_for_query("browser agent python", tmp_path, monkeypatch)
        assert isinstance(plan, IntegrationPlan)
        assert plan.repository_name
        assert plan.target_module
        assert plan.target_package
        assert plan.estimated_risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert plan.summary
        assert plan.migration_steps
        assert plan.rollback_plan

    def test_real_trading_repo_produces_plan(self, tmp_path, monkeypatch):
        plan = self._plan_for_query("crypto trading bot python", tmp_path, monkeypatch)
        assert isinstance(plan, IntegrationPlan)
        assert plan.repository_name
        assert plan.target_module
        assert plan.estimated_risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert plan.summary


# --- 3) Provider repo → Provider klasörünü hedef göster -----------------------


class TestProviderTargetDetection:
    def test_llm_category_targets_providers_package(self):
        planner = IntegrationPlanner()
        evaluation = _evaluation(target_module=CATEGORY_TARGET_MODULE["llm"])

        target_module, target_package, strategy, exists = planner.detect_target(evaluation)

        assert target_package == "src/providers"
        assert exists is True  # src/providers/ gerçekten var
        assert "src/providers" in strategy

    def test_full_pipeline_shows_providers_as_target(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation(target_module=CATEGORY_TARGET_MODULE["llm"])
        sandbox = _sandbox_result(sandbox_path=_fixture_repo(tmp_path, **{"client.py": "class MyLLMClient:\n    pass\n"}))

        plan = planner.analyze(sandbox, evaluation)
        assert plan.target_package == "src/providers"


# --- 4) Duplicate tool → Conflict üret -----------------------------------------


class TestDuplicateToolConflict:
    def test_browser_tool_class_produces_tool_conflict(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation(target_module="src/agents/browser_agent.py")
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{
                "tool.py": "class BrowserTool:\n    def run(self):\n        pass\n",
            })
        )

        plan = planner.analyze(sandbox, evaluation)

        types = {c.type for c in plan.conflicts}
        assert "tool_conflict" in types
        assert "same_class_name" in types
        assert any("BrowserTool" in c.description for c in plan.conflicts)


# --- 5) Aynı sınıf adı → Conflict üret ------------------------------------------


class TestSameClassNameConflict:
    def test_agent_manager_class_produces_same_class_name_conflict(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation(target_module="src/agents/agent_manager.py")
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{
                "manager.py": "class AgentManager:\n    def dispatch(self):\n        pass\n",
            })
        )

        plan = planner.analyze(sandbox, evaluation)

        same_class_conflicts = [c for c in plan.conflicts if c.type == "same_class_name"]
        assert same_class_conflicts
        assert any("AgentManager" in c.description for c in same_class_conflicts)
        # src/agents 'src/core' degil, bu yuzden HIGH degil MEDIUM olmali
        assert same_class_conflicts[0].severity == "MEDIUM"

    def test_core_module_class_conflict_is_high_severity(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation(target_module="Bilinmiyor (tanınmayan kategori)")
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{
                "engine.py": "class TaskManager:\n    pass\n",
            })
        )

        plan = planner.analyze(sandbox, evaluation)
        matching = [c for c in plan.conflicts if c.type == "same_class_name" and "TaskManager" in c.description]
        assert matching
        assert matching[0].severity == "HIGH"


# --- 6) Belirsiz lisans → merge_ready=False ------------------------------------


class TestUnclearLicenseBlocksMerge:
    def test_empty_license_blocks_merge(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation()
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"}),
            license_detected="",
        )

        plan = planner.analyze(sandbox, evaluation)

        assert plan.merge_ready is False
        assert any(c.type == "license_problem" for c in plan.conflicts)
        assert "belirsiz" in plan.license_notes.lower() or "tespit edilemedi" in plan.license_notes.lower()

    def test_copyleft_license_alone_also_blocks_merge(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation()
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"}),
            license_detected="GNU GENERAL PUBLIC LICENSE",
        )
        plan = planner.analyze(sandbox, evaluation)
        assert plan.merge_ready is False  # izinli lisans kumesinde degil


# --- 7) HIGH risk Evaluation → merge_ready=False -------------------------------


class TestHighRiskBlocksMerge:
    def test_high_evaluation_risk_blocks_merge(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation(risk_level="HIGH")
        sandbox = _sandbox_result(sandbox_path=_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"}))

        plan = planner.analyze(sandbox, evaluation)

        assert plan.estimated_risk in ("HIGH", "CRITICAL")
        assert plan.merge_ready is False

    def test_clean_low_risk_repo_can_be_merge_ready(self, tmp_path):
        # Pozitif kontrol: cakisma yok, lisans izinli, risk dusuk, suitable=True
        # -> merge_ready=True olabilmeli (negatif testlerin anlamli oldugunu kanitlar).
        planner = IntegrationPlanner()
        evaluation = _evaluation(target_module="Bilinmiyor (tanınmayan kategori)")  # hedef yok -> duplicate_functionality yok
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{"totally_unique_module_xyz.py": "class TotallyUniqueClassXyz:\n    pass\n"}),
            license_detected="MIT License",
        )

        plan = planner.analyze(sandbox, evaluation)

        assert plan.estimated_risk == "LOW"
        assert plan.merge_ready is True


# --- 8) Sandbox sonucu okunuyor mu -----------------------------------------------


class TestSandboxResultIsActuallyConsumed:
    def test_dependencies_required_comes_from_sandbox_install_commands(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation()
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"}),
            detected_install_commands=["pip install -r requirements.txt", "docker build -t x ."],
        )
        plan = planner.analyze(sandbox, evaluation)
        assert plan.dependencies_required == ["pip install -r requirements.txt", "docker build -t x ."]

    def test_license_detected_flows_into_license_notes_and_merge_ready(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation()
        path = _fixture_repo(tmp_path, **{"main.py": "print('hi')\n"})

        with_license = planner.analyze(_sandbox_result(sandbox_path=path, license_detected="MIT License"), evaluation)
        without_license = planner.analyze(_sandbox_result(sandbox_path=path, license_detected=""), evaluation)

        assert "MIT" in with_license.license_notes
        assert without_license.merge_ready is False

    def test_high_execution_risk_from_sandbox_raises_estimated_risk(self, tmp_path):
        planner = IntegrationPlanner()
        # target_module'u kasitli olarak VAR OLMAYAN bir hedefe ayarliyoruz
        # ki duplicate_functionality catismasi izole edilmek istenen
        # execution_risk etkisini maskelemesin.
        evaluation = _evaluation(target_module="Bilinmiyor (tanınmayan kategori)")
        path = _fixture_repo(tmp_path, **{"main.py": "print('hi')\n"})

        low = planner.analyze(_sandbox_result(sandbox_path=path, execution_risk="LOW"), evaluation)
        high = planner.analyze(_sandbox_result(sandbox_path=path, execution_risk="HIGH"), evaluation)

        risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        assert risk_order[high.estimated_risk] > risk_order[low.estimated_risk]


# --- 9) Evaluation sonucu okunuyor mu --------------------------------------------


class TestEvaluationResultIsActuallyConsumed:
    def test_target_module_comes_from_evaluation(self, tmp_path):
        planner = IntegrationPlanner()
        sandbox = _sandbox_result(sandbox_path=_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"}))

        plan_a = planner.analyze(sandbox, _evaluation(target_module="src/agents/browser_agent.py"))
        plan_b = planner.analyze(sandbox, _evaluation(target_module=CATEGORY_TARGET_MODULE["llm"]))

        assert plan_a.target_module == "src/agents/browser_agent.py"
        assert plan_b.target_module == CATEGORY_TARGET_MODULE["llm"]
        assert plan_a.target_package != plan_b.target_package

    def test_suitable_for_jarvis_false_forces_merge_not_ready_even_if_everything_else_perfect(self, tmp_path):
        planner = IntegrationPlanner()
        sandbox = _sandbox_result(
            sandbox_path=_fixture_repo(tmp_path, **{"totally_unique_zzz.py": "class TotallyUniqueZzz:\n    pass\n"}),
            license_detected="MIT License",
        )
        evaluation = _evaluation(
            suitable_for_jarvis=False,
            target_module="Bilinmiyor (tanınmayan kategori)",
        )

        plan = planner.analyze(sandbox, evaluation)
        assert plan.merge_ready is False


# --- 10) Mevcut testler: regresyon olmadan geçmeli ------------------------------
# (Bu paket src/github, src/evaluation veya src/sandbox'ın mevcut hicbir
# dosyasini degistirmedi — src/sandbox/code_index.py YENI/eklemeli bir
# dosyadir. Regresyon kontrolu ayri bir pytest calistirmasiyla yapilir.)


# --- Ek: build_plan/generate_summary'nin bagimsiz cagrilabilirligi --------------


class TestIndividualPipelineSteps:
    def test_estimate_changes_counts_source_files(self, tmp_path):
        planner = IntegrationPlanner()
        path = _fixture_repo(tmp_path, **{
            "a.py": "x = 1\n", "b.py": "y = 2\n", "README.md": "# docs\n",
        })
        sandbox = _sandbox_result(sandbox_path=path)
        files, changes = planner.estimate_changes(sandbox, {})
        assert files == 2  # yalnizca .py dosyalari
        assert changes >= files

    def test_generate_summary_mentions_repository_and_decision(self, tmp_path):
        planner = IntegrationPlanner()
        evaluation = _evaluation()
        sandbox = _sandbox_result(sandbox_path=_fixture_repo(tmp_path, **{"main.py": "print(1)\n"}))
        plan = planner.build_plan(
            sandbox_result=sandbox, evaluation=evaluation,
            target_module="src/agents/browser_agent.py", target_package="src/agents",
            integration_strategy="test", target_module_exists=True,
            conflicts=[], estimated_files=1, estimated_changes=2,
        )
        summary = planner.generate_summary(plan)
        assert sandbox.repository_name in summary
        assert ("HAZIR" in summary)
