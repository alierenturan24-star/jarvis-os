from __future__ import annotations

from pathlib import Path

from src.media.manager import MediaManager
from src.media.production import GeneralProductionBuilder, PackageBuildResult
from src.providers.provider_manager import ProviderManager, RouteResult

# Sprint: capability-gate audit (mission 4a50230ffad2400bbb2aff173bd2a797).
# These exercise MediaManager.plan()'s CAPABILITY_GAP propagation in
# isolation (fake route_and_generate/build, no real ffmpeg/TTS) -- the real
# end-to-end GeneralProductionBuilder behavior is already covered by
# src/media/tests/test_general_production.py.


def _complete_plan_text(title: str = "Hibrit Calisma Modeli") -> str:
    return (
        "SENARYO\nIsvicre'de hibrit calisma modeli yukseliyor...\n\n"
        "SAHNELER\nSahne 1 (~10 sn): Anlatım: ... | Görsel: ... | Ekran yazısı: ...\n\n"
        "SESLENDİRME PLANI\nYerel TTS önerisi...\n\n"
        "GÖRSEL/VİDEO PLANI\nBasit metin kartları...\n\n"
        "ALTYAZI PLANI\n0-10sn: ...\n\n"
        "THUMBNAIL FİKRİ\nOfis ve ev simgeleri...\n\n"
        f"BAŞLIK\n{title}\n\n"
        "AÇIKLAMA\nKısa açıklama metni burada.\n\n"
        "ETİKETLER\nisvicre, is, verimlilik"
    )


def _route_result(output: str) -> RouteResult:
    return RouteResult(output=output, chosen_provider="ollama", provider_used="ollama",
                        reason="test", fallback_used=False, duration_seconds=0.1, success=True)


def _manager(tmp_path, monkeypatch, *, build_result: PackageBuildResult):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ProviderManager, "route_and_generate",
                         lambda self, prompt, task_type, **kw: _route_result(_complete_plan_text()))
    monkeypatch.setattr("src.media.manager.find_goal_production_package", lambda topic: None)
    monkeypatch.setattr(GeneralProductionBuilder, "build", lambda self, **kw: build_result)
    return MediaManager()


_GAP_RESULT = PackageBuildResult(
    False, error="CAPABILITY_GAP: no genuine image/video-generation capability available for this goal",
    required_capabilities=("story_generation", "scene_generation", "character_visual_generation",
                            "motion_generation", "narration_generation", "thumbnail_generation",
                            "video_render", "technical_validation", "semantic_validation"),
    available_capabilities=("story_generation", "narration_generation", "video_render",
                             "technical_validation", "semantic_validation"),
    missing_capabilities=("scene_generation", "character_visual_generation", "motion_generation",
                           "thumbnail_generation"),
)


# A: no real visual provider available -> CAPABILITY_GAP before any render is attempted.
def test_missing_visual_capability_returns_capability_gap_before_render(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, build_result=_GAP_RESULT)

    result = manager.plan(topic="Swiss Insider hibrit calisma", produce_artifact=True)

    assert "VIDEO RENDER: BLOCKED" in result
    assert "CAPABILITY_GAP" in result


# C: missing visual capability -> no final MP4 falsely reported as newly generated.
def test_missing_visual_capability_leaves_no_artifact_path(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, build_result=_GAP_RESULT)

    manager.plan(topic="Swiss Insider hibrit calisma", produce_artifact=True)

    assert manager.last_artifact_path == ""
    assert manager.last_production_record is None


# E: the recorded capability gap must separate required/available/missing and
# must never claim the missing visual capabilities as available/used.
def test_capability_gap_accounting_is_truthful(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, build_result=_GAP_RESULT)

    manager.plan(topic="Swiss Insider hibrit calisma", produce_artifact=True)

    gap = manager.last_capability_gap
    assert gap is not None
    assert "character_visual_generation" in gap["missing_capabilities"]
    assert "motion_generation" in gap["missing_capabilities"]
    assert "character_visual_generation" not in gap["available_capabilities"]
    assert set(gap["required_capabilities"]) >= set(gap["missing_capabilities"])
    assert isinstance(gap["report_path"], str) and gap["report_path"]


# G: research/script evidence already generated before the visual gap is
# discovered must be preserved (the report is written before build() is ever
# attempted, unconditionally) -- and it must contain the REAL generated
# script, not a placeholder.
def test_research_and_script_report_preserved_when_capability_gap_occurs(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, build_result=_GAP_RESULT)

    manager.plan(topic="Swiss Insider hibrit calisma", produce_artifact=True)

    report_path = Path(manager.last_capability_gap["report_path"])
    assert report_path.is_file()
    content = report_path.read_text(encoding="utf-8")
    assert "Hibrit Calisma Modeli" in content
    assert "hibrit calisma modeli yukseliyor" in content


# No production report_builder failure should ever be mistaken for a
# capability gap: a build failure with no missing_capabilities (e.g. a plain
# script-parsing failure) must not populate last_capability_gap.
def test_non_capability_build_failure_does_not_set_capability_gap(tmp_path, monkeypatch):
    parse_failure = PackageBuildResult(False, error="CAPABILITY_GAP: script parsing failed")
    manager = _manager(tmp_path, monkeypatch, build_result=parse_failure)

    manager.plan(topic="Swiss Insider hibrit calisma", produce_artifact=True)

    assert manager.last_capability_gap is None
