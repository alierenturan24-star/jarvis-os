from __future__ import annotations

from src.media.manager import MediaManager
from src.media.production import GeneralProductionBuilder, PackageBuildResult
from src.media.quality import MediaArtifactQuality
from src.media.renderer import LocalVideoRenderer, RenderResult
from src.providers.provider_manager import ProviderManager, RouteResult


def _complete_plan_text() -> str:
    return (
        "SENARYO\nBitcoin son günlerde düştü çünkü...\n\n"
        "SAHNELER\nSahne 1 (~10 sn): Anlatım: ... | Görsel: ... | Ekran yazısı: ...\n\n"
        "SESLENDİRME PLANI\nYerel TTS önerisi...\n\n"
        "GÖRSEL/VİDEO PLANI\nBasit metin kartları...\n\n"
        "ALTYAZI PLANI\n0-10sn: ...\n\n"
        "THUMBNAIL FİKRİ\nKırmızı ok, büyük yazı...\n\n"
        "BAŞLIK\nBitcoin Neden Düştü?\n\n"
        "AÇIKLAMA\nKısa açıklama metni burada.\n\n"
        "ETİKETLER\nbitcoin, kripto, finans"
    )


def _route_result(output: str, *, provider: str = "ollama", fallback_used: bool = False, success: bool = True) -> RouteResult:
    return RouteResult(
        output=output, chosen_provider=provider, provider_used=provider, reason="test",
        fallback_used=fallback_used, duration_seconds=0.1, success=success,
    )


class TestMediaManagerPlan:
    def test_empty_topic_returns_early_without_calling_llm(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        calls = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: calls.append(prompt) or _route_result("x"),
        )

        manager = MediaManager()
        result = manager.plan(topic="   ")

        assert "konu belirtilmedi" in result
        assert calls == []

    def test_successful_plan_includes_quality_check_and_environment_note(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result(_complete_plan_text()),
        )

        manager = MediaManager()
        result = manager.plan(topic="Bitcoin neden düştü", duration_seconds=60)

        assert "SENARYO" in result
        assert "KALİTE KONTROL" in result
        assert "Tüm beklenen bölümler mevcut" in result
        assert "ORTAM DURUMU" in result
        assert "FFmpeg" in result
        assert "YouTube'a yüklenmedi" in result
        assert "Rapor kaydedildi" in result

    def test_llm_failure_is_reported_honestly_not_faked(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result(
                "Ollama zaman aşımına uğradı.", success=False,
            ),
        )

        manager = MediaManager()
        result = manager.plan(topic="Bitcoin neden düştü")

        assert "üretilemedi" in result
        assert "uydurulmadı" in result

    def test_fallback_used_is_surfaced_in_output(self, tmp_path, monkeypatch):
        # Sprint 40: route_and_generate fallback'e düştüğünde (bkz.
        # RouteResult.fallback_used), bu CEO/kullanıcı raporunda
        # GÖRÜNMELİ -- self_check'e dokunmadan, düz metne eklenerek.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result(
                _complete_plan_text(), provider="ollama", fallback_used=True,
            ),
        )

        manager = MediaManager()
        result = manager.plan(topic="Bitcoin neden düştü")

        assert "otomatik olarak" in result

    def test_prior_knowledge_is_included_in_prompt_context(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        captured_prompts = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_prompts.append(prompt) or _route_result(_complete_plan_text()),
        )

        manager = MediaManager()
        manager.knowledge.remember_research(
            topic="Bitcoin neden düştü", summary="Bitcoin faiz kararları nedeniyle düştü.",
            report_path="x.md", source_count=3,
        )

        manager.plan(topic="Bitcoin neden düştü")

        assert len(captured_prompts) == 1
        assert "Bitcoin faiz kararları nedeniyle düştü." in captured_prompts[0]

    def test_no_prior_knowledge_tells_model_not_to_fabricate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        captured_prompts = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_prompts.append(prompt) or _route_result(_complete_plan_text()),
        )

        manager = MediaManager()
        manager.plan(topic="Daha önce hiç araştırılmamış çok özel bir konu")

        assert "uydurma istatistik" in captured_prompts[0]

    def test_unavailable_preferred_provider_falls_back_to_ollama(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        captured_preferred = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_preferred.append(kw.get("preferred_provider")) or _route_result(_complete_plan_text()),
        )

        manager = MediaManager()
        manager.plan(topic="Bitcoin neden düştü", preferred_provider="anthropic")

        assert captured_preferred == ["ollama"]

    def test_task_type_identifies_media_planning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        captured_task_types = []
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: captured_task_types.append(task_type) or _route_result(_complete_plan_text()),
        )

        manager = MediaManager()
        manager.plan(topic="Bitcoin neden düştü")

        # Sprint 42: "media_planning" ad-hoc etiketi yerine CostOptimizer'ın
        # ZATEN kullandığı kanonik "planning" sınıfı (bkz. provider_manager.py
        # TASK_PLANNING, strategy_engine.py _TASK_TYPE_FOR_DEPARTMENT["media"]).
        assert captured_task_types == ["planning"]


def _quality(passed: bool, critical_failures: tuple = ()) -> MediaArtifactQuality:
    gates = {name: {"passed": name not in critical_failures} for name in critical_failures}
    return MediaArtifactQuality(passed, True, passed, (), gates=gates, critical_failures=critical_failures)


# Sprint: research/production pipeline audit -- Phase 8 bounded repair loop.
# These exercise MediaManager._produce_with_bounded_repair's control flow in
# isolation (fake render/build/quality-check) rather than real ffmpeg/TTS,
# which src/media/tests/test_general_production.py already covers end to end.
class TestBoundedRepairLoop:
    def _manager(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            ProviderManager, "route_and_generate",
            lambda self, prompt, task_type, **kw: _route_result(_complete_plan_text()),
        )
        monkeypatch.setattr("src.media.manager.find_goal_production_package", lambda topic: None)
        build_calls: list[int] = []
        monkeypatch.setattr(
            GeneralProductionBuilder, "build",
            lambda self, **kw: (build_calls.append(1), PackageBuildResult(True, "x.json", production_id="p1"))[1],
        )
        return MediaManager(), build_calls

    def test_repairable_failure_triggers_bounded_retry_then_succeeds(self, tmp_path, monkeypatch):
        manager, build_calls = self._manager(tmp_path, monkeypatch)
        render_calls: list[int] = []
        monkeypatch.setattr(
            LocalVideoRenderer, "render",
            lambda self, topic, narration, duration_seconds, **kw: (render_calls.append(1),
                RenderResult(True, str(tmp_path / f"artifact-{len(render_calls)}.mp4"),
                             audio_used=True, production_ready=True))[1],
        )
        checks = [_quality(False, ("audio_completeness",)), _quality(True)]
        monkeypatch.setattr("src.media.manager.validate_media_goal_artifact",
                             lambda path, goal, **kw: checks.pop(0))

        result = manager.plan(topic="Bitcoin neden düştü", produce_artifact=True)

        assert len(render_calls) == 2
        assert len(build_calls) == 2  # initial build + one bounded rebuild
        assert "GERÇEK VIDEO ARTIFACT" in result
        assert "REPAIR LOG" in result
        assert "attempt 1: regenerated due to audio_completeness" in result

    def test_repair_exhaustion_ends_truthfully_without_publication(self, tmp_path, monkeypatch):
        manager, build_calls = self._manager(tmp_path, monkeypatch)
        render_calls: list[int] = []
        monkeypatch.setattr(
            LocalVideoRenderer, "render",
            lambda self, topic, narration, duration_seconds, **kw: (render_calls.append(1),
                RenderResult(True, str(tmp_path / f"artifact-{len(render_calls)}.mp4"),
                             audio_used=True, production_ready=True))[1],
        )
        monkeypatch.setattr("src.media.manager.validate_media_goal_artifact",
                             lambda path, goal, **kw: _quality(False, ("audio_completeness",)))

        result = manager.plan(topic="Bitcoin neden düştü", produce_artifact=True)

        # initial render + _MAX_REPAIR_ATTEMPTS(2) retries = 3 renders, 3 builds
        assert len(render_calls) == 3
        assert len(build_calls) == 3
        assert "QUALITY: NOT READY FOR PUBLICATION" in result
        assert "repair attempts exhausted" in result
        assert "GERÇEK VIDEO ARTIFACT" not in result

    def test_non_repairable_failure_stops_immediately_without_retry(self, tmp_path, monkeypatch):
        manager, build_calls = self._manager(tmp_path, monkeypatch)
        render_calls: list[int] = []
        monkeypatch.setattr(
            LocalVideoRenderer, "render",
            lambda self, topic, narration, duration_seconds, **kw: (render_calls.append(1),
                RenderResult(True, str(tmp_path / "artifact.mp4"), audio_used=True, production_ready=True))[1],
        )
        monkeypatch.setattr("src.media.manager.validate_media_goal_artifact",
                             lambda path, goal, **kw: _quality(False, ("visual_relevance",)))

        result = manager.plan(topic="Bitcoin neden düştü", produce_artifact=True)

        assert len(render_calls) == 1  # no retry -- research/opportunity mismatch, not fixable by re-rendering
        assert len(build_calls) == 1
        assert "QUALITY: NOT READY FOR PUBLICATION" in result
        assert "non-repairable quality gate failure(s): visual_relevance" in result
