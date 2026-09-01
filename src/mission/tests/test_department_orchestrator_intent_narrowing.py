from __future__ import annotations

from src.mission.department_orchestrator import DepartmentOrchestrator

# Sprint 41 bölüm 3/8 (SIMPLE TASK OVER-ROUTING) -- kabul testi C/D/E.


class TestSimpleGenerationTaskIsNarrowed:
    """TEST C: "10 YouTube Shorts başlığı üret." gereksiz research/github/
    browser zincirini AÇMAMALI."""

    def test_shorts_title_generation_only_needs_media_and_automation(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments("Jarvis, 10 YouTube Shorts başlığı üret.")

        assert set(departments) == {"media", "automation"}
        assert "research" not in departments
        assert "github" not in departments
        assert "browser" not in departments

    def test_shorts_ideas_generation_is_also_narrowed(self):
        # Sprint 34/35'ten kalma örnek istem -- artık saf üretim olarak
        # tanınmalı (davranış KASITLI olarak DEĞİŞTİ, bkz. Sprint 41).
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments("100 Shorts fikri üret.")
        assert set(departments) == {"media", "automation"}

    def test_video_ideas_generation_is_narrowed(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments("Video fikirleri üret.")
        assert set(departments) == {"media", "automation"}


class TestCurrentInfoYoutubeTaskIsPreserved:
    """TEST D: "Bitcoin neden düştü konusunda 60 saniyelik Shorts
    hazırla." -- research/browser/finance + media KORUNMALI."""

    def test_bitcoin_shorts_keeps_investigative_departments(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments(
            "Bitcoin neden düştü konusunda 60 saniyelik Shorts hazırla."
        )

        assert "research" in departments
        assert "browser" not in departments
        assert "finance" in departments
        assert "media" in departments
        assert "automation" not in departments

    def test_existing_youtube_setup_request_is_unaffected(self):
        # Regresyon: mevcut testin ("YouTube otomasyonu kur.") tam
        # bundle beklentisi Sprint 41'den ÖNCE de vardı -- narrowing bunu
        # BOZMAMALI (ne bir üretim sinyali VAR ne de "kur" bir sinyal).
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments("YouTube otomasyonu kur.")
        assert set(departments) == {"research", "github", "browser", "media", "automation"}


class TestRepoResearchTaskIsPreserved:
    """TEST E: "JARVIS için YouTube automation reposu bul ve değerlendir."
    -- GitHub/Evaluation/Sandbox/Integration yolu KORUNMALI."""

    def test_repo_selection_request_keeps_validation_pipeline(self):
        orchestrator = DepartmentOrchestrator()
        departments = orchestrator.select_departments(
            "JARVIS için en iyi YouTube automation reposu bul ve değerlendir."
        )

        assert "github" in departments
        for name in ("evaluation", "sandbox", "integration"):
            assert name in departments, f"{name} narrowing tarafından yanlışlıkla çıkarıldı"
