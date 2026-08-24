from __future__ import annotations

from src.mission.department_orchestrator import DepartmentOrchestrator
from src.providers.cost_optimizer import CostOptimizer
from src.providers.provider_manager import ProviderManager
from src.strategy.models import (
    TIER_CLOUD,
    TIER_FREE_SERVICE,
    TIER_LOCAL_FREE,
    TIER_OPEN_SOURCE,
    TIER_PAID,
    AIStrategyPlan,
    TaskCategory,
)
from src.strategy.strategy_engine import (
    AIStrategyEngine,
    _tier_for,
    classify_task_category,
)

# Sprint 34 örnek görevleri (canlı test bunlarla yapılır -- bkz. rapor).
YOUTUBE_REPO_TASK = "YouTube için en iyi otomasyon reposunu bul."
SHORTS_IDEAS_TASK = "100 Shorts fikri üret."
FINANCE_TASK = "Bitcoin neden düştü?"
PDF_TASK = "Bu PDF'yi özetle."
CODE_TASK = "Bu Python hatasını çöz."

ALL_PROVIDERS = ("ollama", "aiml", "openai", "anthropic", "gemini", "deepseek", "groq", "openrouter")


class _FakeProvider:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


class _FakeProviderManager:
    """Sprint 34: ``CostOptimizer``'ın gerçek sağlayıcı kullanılabilirlik
    kontrollerini (ağ/anahtar bağımlı) DETERMİNİSTİK hale getirmek için --
    testler gerçek Ollama/API anahtarı varlığına BAĞIMLI olmasın diye."""

    def __init__(self, available: set[str]) -> None:
        self._available = available

    def get(self, name: str):
        normalized = ProviderManager.normalize(name)
        if normalized not in ALL_PROVIDERS:
            return None
        return _FakeProvider(normalized in self._available)

    def available_names(self) -> list[str]:
        return [name for name in ALL_PROVIDERS if name in self._available]


def _engine(available: set[str]) -> AIStrategyEngine:
    cost_optimizer = CostOptimizer(provider_manager=_FakeProviderManager(available))
    return AIStrategyEngine(cost_optimizer=cost_optimizer)


# --- Soru 1: kategori sınıflandırması -------------------------------------------


class TestClassifyTaskCategory:
    def test_youtube_repo_task_is_youtube(self):
        category, reason = classify_task_category(YOUTUBE_REPO_TASK)
        assert category == TaskCategory.YOUTUBE
        assert reason

    def test_shorts_ideas_task_is_youtube(self):
        # Mission'ın KENDİ "youtube" anahtar kelime listesi bunu YAKALAMAZ
        # (metinde "youtube" geçmiyor) -- AI Strategy'nin kendi ek
        # "shorts" sinyali bunu yakalar (Department seçimini DEĞİŞTİRMEZ).
        category, reason = classify_task_category(SHORTS_IDEAS_TASK)
        assert category == TaskCategory.YOUTUBE
        assert "shorts" in reason.lower() or "youtube" in reason.lower()

    def test_finance_task_is_finance(self):
        category, _ = classify_task_category(FINANCE_TASK)
        assert category == TaskCategory.FINANCE

    def test_pdf_task_is_pdf(self):
        category, reason = classify_task_category(PDF_TASK)
        assert category == TaskCategory.PDF
        assert "pdf" in reason.lower()

    def test_code_task_is_code(self):
        category, _ = classify_task_category(CODE_TASK)
        assert category == TaskCategory.CODE

    def test_vision_cue_detected(self):
        category, reason = classify_task_category("Bu görseldeki metni oku.")
        assert category == TaskCategory.VISION
        assert "görsel" in reason.lower() or "vision" in reason.lower()

    def test_no_signal_falls_back_to_other(self):
        category, reason = classify_task_category("Merhaba, nasılsın?")
        assert category == TaskCategory.OTHER
        assert reason

    def test_pdf_takes_priority_over_research_keywords(self):
        # "incele" RESEARCH sinyali de taşır ama PDF sinyali (Mission
        # sisteminde karşılığı olmayan) ÖNCELİKLİDİR.
        category, _ = classify_task_category("Bu PDF dosyasını incele.")
        assert category == TaskCategory.PDF


# --- Soru 2: Department seçimi GERÇEK sistemle AYNI olmalı -----------------------


class TestPlanDepartmentsMatchRealOrchestrator:
    def test_departments_match_real_select_departments_for_all_sample_tasks(self):
        engine = _engine(available={"ollama"})
        orchestrator = DepartmentOrchestrator()

        for request in (YOUTUBE_REPO_TASK, SHORTS_IDEAS_TASK, FINANCE_TASK, PDF_TASK, CODE_TASK):
            plan = engine.plan(request)
            expected = set(orchestrator.select_departments(request))
            actual = {choice.name for choice in plan.departments}
            assert actual == expected, f"{request!r}: {actual} != {expected}"

    def test_youtube_repo_selection_intent_includes_validation_pipeline(self):
        # Sprint 33B'nin "en uygun/en iyi ... bul/seç" zenginleştirmesi
        # burada da (DepartmentOrchestrator ÜZERİNDEN) devreye girmeli.
        engine = _engine(available={"ollama"})
        plan = engine.plan(YOUTUBE_REPO_TASK)
        names = {choice.name for choice in plan.departments}
        assert {"evaluation", "sandbox", "integration"}.issubset(names)

    def test_department_reasons_are_non_empty_and_reuse_department_description(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(CODE_TASK)
        github_choice = next(c for c in plan.departments if c.name == "github")
        assert "GitHub" in github_choice.reason


# --- Soru 3: Tool seçimi -------------------------------------------------------------


class TestToolSelection:
    def test_github_department_maps_to_github_intelligence_tool(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(CODE_TASK)
        tool_names = [t.name for t in plan.tools]
        assert any("GitHubIntelligence" in name for name in tool_names)

    def test_pdf_task_falls_back_to_research_department_and_tool(self):
        # PDF, AI Strategy'nin KENDİ kategorisinde ayrı bir sınıf olsa da
        # (bkz. TestClassifyTaskCategory), Mission sisteminde PDF'ye özel
        # bir department YOK -- classify_mission_type varsayılan olarak
        # research'e düşer, bu yüzden gerçek Tool de research'ün
        # (ResearchManager/Summarizer) tool'udur. Bu, AI Strategy'nin
        # GERÇEK sistemle TUTARLI kalmasının bir sonucudur.
        engine = _engine(available={"ollama"})
        plan = engine.plan(PDF_TASK)
        names = {c.name for c in plan.departments}
        assert names == {"research"}
        assert any("ResearchManager" in t.name for t in plan.tools)

    def test_department_without_real_tool_honestly_disclosed(self):
        # Sprint 39: media/automation artık GERÇEK modüllere bağlı (bkz.
        # src.media/src.automation) -- "social_media" gibi hâlâ
        # bağlanmamış departmanlar için (Department.maturity düşük) Tool
        # eksikliği SESSİZCE atlanmaz, dürüstçe belirtilir.
        engine = _engine(available={"ollama"})
        plan = engine.plan("Sosyal medyada paylaş.")
        names = {c.name for c in plan.departments}
        assert "social_media" in names
        assert any("henüz gerçek bir tool" in t.reason.lower() for t in plan.tools)

    def test_media_and_automation_now_have_real_tools_disclosed(self):
        # Sprint 39: eskiden "henüz bağlı değil" olan media/automation,
        # artık ZATEN VAR OLAN gerçek modüllere (src.media/src.automation)
        # bağlı -- bu, yeni bir puanlama/tool sistemi İCAT ETMEDEN, tek
        # kaynak olan ``_TOOLS_FOR_DEPARTMENT``'a eklenen iki satırla
        # yansıtılır.
        engine = _engine(available={"ollama"})
        plan = engine.plan("Bir video üret.")
        tool_names = {t.name for t in plan.tools}
        assert any("MediaManager" in name for name in tool_names)
        assert any("AutomationManager" in name for name in tool_names)


# --- Soru 4-7: AI seçimi + katman -----------------------------------------------


class TestAITierMapping:
    def test_ollama_is_local_free(self):
        assert _tier_for("ollama", 0.0) == TIER_LOCAL_FREE

    def test_groq_and_openrouter_are_open_source(self):
        assert _tier_for("groq", 0.0) == TIER_OPEN_SOURCE
        assert _tier_for("openrouter", 0.0) == TIER_OPEN_SOURCE

    def test_gemini_is_free_service(self):
        assert _tier_for("gemini", 0.0) == TIER_FREE_SERVICE

    def test_cheap_paid_is_cloud_tier(self):
        assert _tier_for("deepseek", 0.002) == TIER_CLOUD

    def test_expensive_paid_is_paid_tier(self):
        assert _tier_for("anthropic", 0.006) == TIER_PAID
        assert _tier_for("openai", 0.005) == TIER_PAID


class TestPlanAIChoiceEndToEnd:
    def test_only_ollama_available_picks_local_free(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(SHORTS_IDEAS_TASK)  # CostOptimizer.classify -> chat (basit)

        assert plan.ai_choice.provider == "ollama"
        assert plan.ai_choice.tier == TIER_LOCAL_FREE
        assert plan.local_sufficient is True
        assert plan.free_sufficient is True
        assert plan.paid_required is False
        assert plan.ai_choice.reason  # gerekçe boş değil

    def test_complex_task_prefers_free_cloud_openrouter_when_ollama_unavailable(self):
        engine = _engine(available={"openrouter"})
        plan = engine.plan("Bu konuyu araştır ve kaynakları karşılaştır.")  # -> research, karmaşık

        assert plan.ai_choice.provider == "openrouter"
        assert plan.ai_choice.tier == TIER_OPEN_SOURCE
        assert plan.free_sufficient is True
        assert plan.local_sufficient is False
        assert plan.paid_required is False

    def test_complex_task_prefers_free_cloud_gemini_when_only_gemini_available(self):
        engine = _engine(available={"gemini"})
        plan = engine.plan("Bu konuyu araştır ve kaynakları karşılaştır.")

        assert plan.ai_choice.provider == "gemini"
        assert plan.ai_choice.tier == TIER_FREE_SERVICE
        assert plan.free_sufficient is True
        assert plan.paid_required is False

    def test_cheap_paid_provider_used_when_nothing_free_available(self):
        engine = _engine(available={"deepseek"})
        plan = engine.plan("Borsa yatırımı hakkında görüş ver.")  # -> finance, karmaşık

        assert plan.ai_choice.provider == "deepseek"
        assert plan.ai_choice.tier == TIER_CLOUD
        assert plan.free_sufficient is False
        assert plan.paid_required is True

    def test_expensive_paid_provider_used_as_last_resort(self):
        engine = _engine(available={"anthropic"})
        plan = engine.plan(CODE_TASK)  # -> coding, karmaşık; deepseek/anthropic profildeki adaylar

        assert plan.ai_choice.provider == "anthropic"
        assert plan.ai_choice.tier == TIER_PAID
        assert plan.free_sufficient is False
        assert plan.local_sufficient is False
        assert plan.paid_required is True
        assert "anthropic" in plan.ai_choice.reason.lower() or "ücretli" in plan.ai_choice.reason.lower()


# --- KURAL: plan() hiçbir görevi ÇALIŞTIRMAZ -------------------------------------


class TestPlanNeverExecutesAnything:
    def test_plan_returns_pure_dataclass_without_side_effects(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(YOUTUBE_REPO_TASK)

        assert isinstance(plan, AIStrategyPlan)
        # Mission/Task nesnesi ÜRETİLMEDİ -- yalnızca bir plan.
        assert not hasattr(plan, "tasks")
        assert not hasattr(plan, "status")

    def test_engine_has_no_dispatch_or_execute_method(self):
        engine = _engine(available={"ollama"})
        assert not hasattr(engine, "dispatch")
        assert not hasattr(engine, "execute")
        assert not hasattr(engine, "run")


# --- SELF IMPROVEMENT -----------------------------------------------------------


class TestSelfImprovementReview:
    def test_local_free_choice_has_no_cheaper_alternative(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(SHORTS_IDEAS_TASK)
        review = engine.review(plan)

        assert review.cheaper_ai_possible is False
        assert review.faster_ai_possible is False

    def test_paid_choice_with_ollama_available_flags_cheaper_alternative(self):
        # Ollama kullanılabilirdi ama görev karmaşık olduğu için (deepseek
        # profildeki tek "ücretsiz" aday değil, hem deepseek hem ollama
        # kullanılamaz senaryosunu test etmek yerine burada Ollama'yı
        # KASITLI olarak kullanılabilir bırakıp yine de paid'e düşecek
        # bir profil kurmuyoruz -- CostOptimizer zaten Ollama varsa adım 3'te
        # ona döner. Bu yüzden burada Ollama YOK ama sonradan (review
        # zamanında) kullanılabilir hale geldiği senaryoyu simüle ediyoruz.
        planning_manager = _FakeProviderManager(available={"anthropic"})
        engine = AIStrategyEngine(cost_optimizer=CostOptimizer(provider_manager=planning_manager))
        plan = engine.plan(CODE_TASK)
        assert plan.ai_choice.tier == TIER_PAID

        # Review zamanında Ollama artık kullanılabilir (görev bitti, sistem
        # değişti) -- self-improvement bunu YAKALAMALI.
        review_manager = _FakeProviderManager(available={"anthropic", "ollama"})
        engine.cost_optimizer.provider_manager = review_manager
        review = engine.review(plan)

        assert review.cheaper_ai_possible is True
        assert review.faster_ai_possible is True

    def test_review_without_ai_discovery_reports_veri_yok(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(SHORTS_IDEAS_TASK)
        review = engine.review(plan, ai_discovery_report=None)

        assert review.new_free_model_available is False
        assert "veri yok" in review.new_free_model_note.lower()

    def test_review_with_ai_discovery_report_surfaces_free_candidates(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(SHORTS_IDEAS_TASK)
        report = {
            "total_found": 3,
            "top": [
                {"title": "FreeLLM Toolkit", "cost_advantage": 95},
                {"title": "PaidTool", "cost_advantage": 10},
            ],
        }
        review = engine.review(plan, ai_discovery_report=report)

        assert review.new_free_model_available is True
        assert "1" in review.new_free_model_note


# --- CEO raporuna hazır metin ----------------------------------------------------


class TestFormatReport:
    def test_format_report_contains_all_sections(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(YOUTUBE_REPO_TASK)
        review = engine.review(plan)

        text = engine.format_report(plan, review)

        assert "AI STRATEGY" in text
        assert "Departmanlar:" in text
        assert "Tool'lar:" in text
        assert "AI seçimi:" in text
        assert "Self-improvement:" in text

    def test_format_report_without_review_omits_self_improvement(self):
        engine = _engine(available={"ollama"})
        plan = engine.plan(YOUTUBE_REPO_TASK)

        text = engine.format_report(plan)

        assert "Self-improvement:" not in text


# --- Sprint 40: TASK-LEVEL ROUTING (tek mission = tek provider KALDIRILDI) ------


class TestDepartmentAiChoices:
    def test_llm_departments_each_get_their_own_choice(self):
        # research/finance/media hepsi LLM çağırıyor -- üçü de AYRI birer
        # AIChoice almalı (yeni bir karar mantığı İCAT EDİLMEDİ, sadece
        # CostOptimizer.decide() departman başına tekrar çağrıldı).
        engine = _engine(available={"ollama"})
        plan = engine.plan("Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla.")

        names = {c.name for c in plan.departments}
        assert {"research", "finance", "media"}.issubset(names)
        assert set(plan.department_ai_choices.keys()) >= {"research", "finance", "media"}
        for choice in plan.department_ai_choices.values():
            assert choice.provider == "ollama"

    def test_non_llm_departments_have_no_entry(self):
        # github/browser/evaluation/sandbox/integration/automation/
        # ai_discovery LLM çağırmaz -- onlar için provider kararı hiç
        # HESAPLANMAZ (tool-first, gereksiz karar üretilmez).
        engine = _engine(available={"ollama"})
        plan = engine.plan("YouTube otomasyonu kur.")

        assert "github" not in plan.department_ai_choices
        assert "browser" not in plan.department_ai_choices
        assert "automation" not in plan.department_ai_choices

    def test_flat_ai_choice_field_is_unchanged_backward_compatible(self):
        # Mevcut ``plan.ai_choice`` (mission özeti) hâlâ ZATEN VAR OLAN
        # davranışıyla dolu olmalı -- Sprint 40 bunu BOZMAZ, yalnızca EK
        # bir alan getirir.
        engine = _engine(available={"ollama"})
        plan = engine.plan(YOUTUBE_REPO_TASK)

        assert plan.ai_choice.provider == "ollama"

    def test_different_departments_can_choose_different_providers(self):
        # research -> gemini (ücretsiz servis) kullanılabilirken finance ->
        # yalnızca ollama kullanılabilir senaryosunda, İKİSİ AYRI provider
        # seçebilmeli (aynı mission içinde).
        engine = _engine(available={"ollama", "gemini"})
        plan = engine.plan("Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla.")

        research_choice = plan.department_ai_choices.get("research")
        finance_choice = plan.department_ai_choices.get("finance")
        assert research_choice is not None and finance_choice is not None
        # research karmaşık + gemini ücretsiz kotalı kullanılabilir -> gemini.
        assert research_choice.provider == "gemini"
        # finance de karmaşık ve fallback_provider'ı (openai) kullanılamaz,
        # ama TASK_FINANCE'ın öncelikli/yedek adayları arasında ücretsiz
        # kotalı bir sağlayıcı YOK -- ollama'ya düşer.
        assert finance_choice.provider == "ollama"

    def test_empty_department_map_when_ai_strategy_engine_has_no_llm_departments(self):
        # GITHUB mission türü -> (github, evaluation, sandbox, integration)
        # -- hiçbiri LLM çağırmaz. ("bul"/"araştır" gibi research-tetikleyici
        # kelimelerden KAÇINILDI -- aksi halde enrichment taraması research'ü
        # de ekler, bu testin amacını bozar.)
        engine = _engine(available={"ollama"})
        plan = engine.plan("github açık kaynak proje")

        assert not (set(plan.department_ai_choices) & {"research", "finance", "media"})
