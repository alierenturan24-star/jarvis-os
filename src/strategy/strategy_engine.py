from __future__ import annotations

from typing import Optional

from src.mission.department import detect_mission_type
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import MissionType
from src.providers.cost_optimizer import (
    PLAN_CLI_PROVIDERS,
    TASK_COST_PROFILES,
    TASK_FINANCE,
    TASK_PLANNING,
    TASK_RESEARCH,
    CostOptimizer,
    ModelDecision,
)
from src.providers.provider_manager import ProviderManager
from src.strategy.models import (
    TIER_CLOUD,
    TIER_FREE_SERVICE,
    TIER_LOCAL_FREE,
    TIER_OPEN_SOURCE,
    TIER_PAID,
    AIChoice,
    AIStrategyPlan,
    DepartmentChoice,
    SelfImprovementReview,
    TaskCategory,
    ToolChoice,
)

# Sprint 34: AI Strategy Engine, JARVIS'in YENİ bir karar KATMANI'dır --
# hiçbir görevi ÇALIŞTIRMAZ (bkz. dosya sonundaki ``AIStrategyEngine``
# docstring'i), yalnızca "hangi AI/Tool/Department, hangi sırayla ve
# NEDEN" sorularının cevabını üretir. Mevcut CEO/Mission/Department/
# Browser/DOM/GitHub/TargetResolver/Evidence Pipeline dosyalarının
# HİÇBİRİNE dokunmaz -- yalnızca onları (salt-okunur, yan etkisiz
# şekilde) ÇAĞIRIR:
#   * Department/AI seçimi -> ``classify_mission_type``/``detect_mission_type``
#     ve ``DepartmentOrchestrator.select_departments`` (Sprint 13-33B,
#     ZATEN VAR).
#   * AI seçimi -> ``CostOptimizer`` (Sprint 7, ZATEN VAR -- "önce yerel,
#     sonra ücretsiz kotalı bulut, en son ücretli" mantığı ve
#     ``ModelDecision.reason`` gerekçesi burada YENİDEN YAZILMAZ).
# Yeni bir puanlama/analiz sistemi İCAT ETMEZ.


# --- Soru 1: görev kategorisi -----------------------------------------------
#
# Mission sisteminin KENDİ sınıflandırması (``classify_mission_type``),
# Department seçimini SÜRDÜĞÜ için burada DEĞİŞTİRİLMEZ/YENİDEN
# YAZILMAZ -- yalnızca AI Strategy'nin PDF/VISION gibi Mission
# sisteminde (henüz) karşılığı olmayan iki ek sinyali önce kontrol eden,
# sonra ``detect_mission_type``'a DÜŞEN bir sarmalayıcıdır (Sprint 33B'de
# "en küçük zenginleştirme" ile aynı desen).
_PDF_CUES = ("pdf", ".pdf")
_VISION_CUES = (
    "görsel", "resim", "fotoğraf", "image", "picture", "ekran görüntüsü",
    "screenshot", "görüntü",
)
# Mission'ın KENDİ "youtube" anahtar kelime listesine (bkz.
# ``department.py``) ek olarak, AI Strategy'nin YouTube İÇERİK ÜRETİMİ
# (senaryo/fikir üretimi) isteklerini de tanıyabilmesi için -- Mission
# sisteminin KENDİ sınıflandırmasını DEĞİŞTİRMEZ, yalnızca AI Strategy'nin
# kendi (Department seçimini SÜRMEYEN) kategori etiketini zenginleştirir.
_YOUTUBE_EXTRA_CUES = ("shorts", "youtube")

_MISSION_TYPE_TO_CATEGORY: dict[MissionType, TaskCategory] = {
    MissionType.RESEARCH: TaskCategory.RESEARCH,
    MissionType.CODE: TaskCategory.CODE,
    MissionType.FINANCE: TaskCategory.FINANCE,
    MissionType.YOUTUBE: TaskCategory.YOUTUBE,
    MissionType.BROWSER: TaskCategory.BROWSER,
    MissionType.GITHUB: TaskCategory.GITHUB,
}


def classify_task_category(request: str) -> tuple[TaskCategory, str]:
    """Soru 1'in cevabı: bu görev araştırma mı/kod mu/.../pdf mi/vision mı?

    Öncelik: PDF/VISION sinyalleri (Mission sisteminde karşılığı YOK) ->
    YouTube-ek sinyalleri -> mevcut ``detect_mission_type`` (Department
    seçimini SÜRDÜREN, ZATEN VAR OLAN sınıflandırma) -> ``OTHER``.
    """

    lowered = (request or "").lower()

    if any(cue in lowered for cue in _PDF_CUES):
        return TaskCategory.PDF, "Metinde PDF sinyali bulundu ('pdf')."

    if any(cue in lowered for cue in _VISION_CUES):
        return TaskCategory.VISION, "Metinde görsel/vision sinyali bulundu."

    if any(cue in lowered for cue in _YOUTUBE_EXTRA_CUES):
        return (
            TaskCategory.YOUTUBE,
            "Metinde YouTube/Shorts içerik üretimi sinyali bulundu.",
        )

    mission_type = detect_mission_type(request)
    if mission_type in _MISSION_TYPE_TO_CATEGORY:
        return (
            _MISSION_TYPE_TO_CATEGORY[mission_type],
            f"Mission sınıflandırması (classify_mission_type) '{mission_type.value}' olarak işaretledi.",
        )
    if mission_type is not None:
        return (
            TaskCategory.OTHER,
            f"Mission sınıflandırması '{mission_type.value}' -- AI Strategy'nin 8 "
            "kategorisinden hiçbirine birebir karşılık gelmiyor.",
        )

    return (
        TaskCategory.OTHER,
        "Ne PDF/vision sinyali ne de bilinen bir Mission türü sinyali bulundu.",
    )


# --- Soru 3: hangi Tool'lar gerekli? -----------------------------------------
#
# department adı -> [(tool adı, neden), ...]. Departman adaptörlerinin
# (bkz. ``src.mission.department_adapters``) ZATEN kullandığı GERÇEK
# modüllerin bir listesidir -- yeni bir Tool İCAT EDİLMEZ. Karşılığı
# henüz olmayan departmanlar (``Department.maturity`` düşük -- bkz.
# ``department.py``) için de bu DÜRÜSTÇE belirtilir.
_TOOLS_FOR_DEPARTMENT: dict[str, tuple[tuple[str, str], ...]] = {
    "research": (("ResearchManager/Summarizer (src.research)", "Web araştırması ve özet üretimi için"),),
    "finance": (("FinanceManager (src.finance)", "Finansal/piyasa analizi için"),),
    "github": (("GitHubIntelligence (src.github)", "Repo arama ve puanlama için"),),
    "evaluation": (("EvaluationEngine (src.evaluation)", "Repo uygunluk/risk değerlendirmesi için"),),
    "sandbox": (("SandboxManager (src.sandbox)", "İzole statik repo analizi için"),),
    "integration": (("IntegrationPlanner (src.integration)", "Entegrasyon planı üretimi için"),),
    "browser": (("BrowserTool + DomEngine (src.tools.browser)", "Sayfa açma/DOM listeleme/tıklama için"),),
    "ai_discovery": (("EvolutionCollector/Scorer (src.evolution)", "GitHub dışı AI ekosistemi taraması için"),),
    # Sprint 39: media/automation artık GERÇEK modüllere bağlı -- ama
    # ikisi de yalnızca PLAN/ÖNERİ üretir, gerçek video/ses dosyası veya
    # gerçek kurulum/zamanlama ÜRETMEZ/YAPMAZ; bu sınırlama gerekçede
    # dürüstçe belirtilir (uydurma bir "tam otomasyon" iddiası YAZILMAZ).
    "media": (("MediaManager (src.media)", "YouTube içerik/senaryo/sahne planı üretimi için (gerçek video/ses dosyası ÜRETMEZ)"),),
    "automation": (("AutomationManager (src.automation)", "Yayın-öncesi kontrol listesi üretimi için (gerçek kurulum/zamanlama YAPMAZ)"),),
}
_NO_TOOL_NOTE = "Bağlı değil: henüz gerçek bir Tool/modül yok (bkz. Department.maturity düşük)."


def tools_for_department(department_name: str) -> tuple[str, ...]:
    """Sprint 36: bir departmanın Tool ADLARINI (gerekçesiz) döndürür --
    ``src.strategy.execution_planner``'ın departman->tool eşlemesini
    TEKRAR YAZMADAN yeniden kullanabilmesi için (tek kaynak: yukarıdaki
    ``_TOOLS_FOR_DEPARTMENT``)."""

    entries = _TOOLS_FOR_DEPARTMENT.get(department_name)
    if entries:
        return tuple(name for name, _ in entries)
    return (f"({department_name})",)


def _tools_for_departments(departments: tuple[DepartmentChoice, ...]) -> tuple[ToolChoice, ...]:
    tools: list[ToolChoice] = []
    for choice in departments:
        entries = _TOOLS_FOR_DEPARTMENT.get(choice.name)
        if entries:
            tools.extend(ToolChoice(name=name, reason=reason) for name, reason in entries)
        else:
            tools.append(ToolChoice(name=f"({choice.name})", reason=_NO_TOOL_NOTE))
    return tuple(tools)


# --- Soru 4-7: hangi AI, ücretsiz/yerel yeterli mi, ücretli gerekli mi? ------
#
# ``CostOptimizer`` (Sprint 7, ZATEN VAR) "önce yerel -> sonra ücretsiz
# kotalı bulut -> en son ücretli" sıralamasını VE gerekçesini ZATEN
# üretiyor -- burada yalnızca 5 katmanlı (Sprint 34 HEDEF) bir etikete
# eşlenir. groq/openrouter tipik olarak açık ağırlıklı (Llama/Mixtral/
# Gemma) modelleri ücretsiz kotayla sundukları için "açık kaynak"
# katmanına, gemini kapalı kaynak ama ücretsiz kotalı olduğu için
# "ücretsiz servis" katmanına yerleştirilir. Kalan ücretli sağlayıcılar
# arasındaki "bulut" / "ücretli" ayrımı, ``CostOptimizer``'ın KENDİ
# göreli maliyet tablosundan (``ModelDecision.estimated_cost``) türetilir
# -- yeni bir maliyet verisi İCAT EDİLMEZ.
_OPEN_SOURCE_PROVIDERS = {"groq", "openrouter"}
_FREE_CLOUD_PROVIDERS = {"gemini"}
_CLOUD_VS_PAID_COST_THRESHOLD = 0.004  # aiml(0.003)/deepseek(0.002) "bulut", openai(0.005)/anthropic(0.006) "ücretli"

# Sprint 40 (TASK-LEVEL ROUTING): "tek mission = tek provider" yaklaşımını
# KALDIRIR -- her GERÇEKTEN LLM çağıran departman için ``CostOptimizer.
# decide()``'in (Sprint 7, ZATEN VAR) hangi 7 görev sınıfına karşılık
# geldiğini belirtir. Departman keyword tabanlı yeni bir sınıflandırma
# İCAT ETMEZ -- yalnızca departman adını ZATEN VAR OLAN ``CostOptimizer``
# görev sınıflarından birine eşler. LLM çağırmayan departmanlar (github/
# browser/evaluation/sandbox/integration/automation/ai_discovery -- bkz.
# Sprint 34/39 araştırması) burada KASITLI OLARAK YOKTUR: onlar için
# hiçbir provider kararı hesaplanmaz (tool-first, LLM'e hiç ihtiyaç yok).
_TASK_TYPE_FOR_DEPARTMENT: dict[str, str] = {
    "research": TASK_RESEARCH,
    "finance": TASK_FINANCE,
    # Sprint 39: MediaManager senaryo/sahne/seslendirme-planı gibi
    # yapılandırılmış bir İÇERİK PLANI üretir -- CostOptimizer'ın 7
    # sınıfından en yakını "planning" (yeni bir sınıf İCAT EDİLMEDİ).
    "media": TASK_PLANNING,
}


def _tier_for(provider: str, estimated_cost: float) -> str:
    normalized = ProviderManager.normalize(provider)
    if normalized == "ollama":
        return TIER_LOCAL_FREE
    if normalized in PLAN_CLI_PROVIDERS:
        return TIER_CLOUD  # Mevcut abonelik CLI kaynağı; ücretsiz API değildir.
    if normalized in _OPEN_SOURCE_PROVIDERS:
        return TIER_OPEN_SOURCE
    if normalized in _FREE_CLOUD_PROVIDERS or estimated_cost <= 0:
        return TIER_FREE_SERVICE
    if estimated_cost < _CLOUD_VS_PAID_COST_THRESHOLD:
        return TIER_CLOUD
    return TIER_PAID


def _ai_choice_from_decision(decision: ModelDecision) -> AIChoice:
    tier = _tier_for(decision.provider, decision.estimated_cost)
    return AIChoice(
        provider=decision.provider,
        model=decision.model,
        tier=tier,
        reason=decision.reason,
        estimated_cost=decision.estimated_cost,
        confidence=decision.confidence,
        fallback_provider=decision.fallback,
    )


def _department_ai_choices(
    cost_optimizer: CostOptimizer, department_names: tuple[str, ...],
) -> dict[str, AIChoice]:
    """Sprint 40: her LLM çağıran departman için AYRI bir ``AIChoice``.

    ``CostOptimizer.decide()`` (Sprint 7, ZATEN VAR) departman başına
    yeniden çağrılır -- yeni bir karar mantığı İCAT EDİLMEZ, yalnızca
    daha önce yalnızca TEK bir kez (tüm mission metni için) çağrılan
    fonksiyon artık departman başına çağrılıyor."""

    choices: dict[str, AIChoice] = {}
    for name in department_names:
        task_type = _TASK_TYPE_FOR_DEPARTMENT.get(name)
        if task_type is None:
            continue
        decision = cost_optimizer.decide(task_type)
        choices[name] = _ai_choice_from_decision(decision)
    return choices


class AIStrategyEngine:
    """Sprint 34: her görev başlamadan önce bir ``AIStrategyPlan`` üretir.

    KURAL (Sprint 34): bu sınıf hiçbir görevi ÇALIŞTIRMAZ, hiçbir AI'ya
    gerçek bir üretim/completion isteği GÖNDERMEZ -- ``plan()`` saf bir
    fonksiyondur (yalnızca ZATEN VAR OLAN sınıflandırma/karar
    fonksiyonlarını okur). Sağlayıcı KULLANILABİLİRLİĞİ kontrolü
    (``CostOptimizer``/``BaseProvider.is_available()`` üzerinden -- API
    anahtarı var mı / yerel Ollama ayakta mı) bir üretim isteği DEĞİLDİR,
    bu yüzden "henüz AI çağırma" kısıtını İHLAL ETMEZ.

    Mevcut Department sistemi (``DepartmentOrchestrator``) bu planı
    KULLANARAK çalışır -- ama bu sprint kapsamında ``CEO``/
    ``DepartmentOrchestrator``/``MissionEngine`` dosyalarının HİÇBİRİNE
    dokunulmadı (Sprint 34 kısıtı: "mevcut mimari... bozulmayacak").
    ``format_report()`` CEO raporuna eklenmeye HAZIR, okunabilir bir
    metin üretir; gerçek CEO'ya BAĞLANMASI kasıtlı olarak sonraki bir
    sprinte BIRAKILDI.
    """

    def __init__(
        self,
        orchestrator: Optional[DepartmentOrchestrator] = None,
        cost_optimizer: Optional[CostOptimizer] = None,
    ) -> None:
        self.orchestrator = orchestrator or DepartmentOrchestrator()
        self.cost_optimizer = cost_optimizer or CostOptimizer()

    # --- Ana plan üretimi ----------------------------------------------------

    def plan(self, request: str) -> AIStrategyPlan:
        request = request or ""

        category, category_reason = classify_task_category(request)

        # Soru 2: hangi Department'lar gerekli? -- ZATEN VAR OLAN
        # ``DepartmentOrchestrator.select_departments`` (Sprint 13-33B)
        # DOĞRUDAN çağrılır; ikinci bir Department seçim mantığı İCAT
        # EDİLMEZ. Gerekçe, o departmanın ZATEN VAR OLAN kaydından
        # (``Department.description``) okunur.
        department_names = self.orchestrator.select_departments(request)
        departments = tuple(
            DepartmentChoice(name=name, reason=self._department_reason(name))
            for name in department_names
        )

        # Soru 3: hangi Tool'lar gerekli?
        tools = _tools_for_departments(departments)

        # Soru 4-7: hangi AI, ücretsiz/yerel yeterli mi, ücretli gerekli mi?
        decision = self.cost_optimizer.decide_for_message(request)
        ai_choice = _ai_choice_from_decision(decision)

        # Sprint 40: EK olarak (yukarıdaki ``ai_choice`` -- tüm mission'ın
        # ÖZET kararı -- DEĞİŞMEDEN), her LLM çağıran departman için AYRI
        # bir karar da hesaplanır (bkz. ``_department_ai_choices``).
        department_ai_choices = _department_ai_choices(self.cost_optimizer, department_names)

        plan_cli_selected = ProviderManager.normalize(ai_choice.provider) in PLAN_CLI_PROVIDERS
        free_sufficient = ai_choice.tier in (TIER_LOCAL_FREE, TIER_OPEN_SOURCE, TIER_FREE_SERVICE)
        local_sufficient = ai_choice.tier == TIER_LOCAL_FREE
        paid_required = ai_choice.tier in (TIER_CLOUD, TIER_PAID) and not plan_cli_selected

        return AIStrategyPlan(
            request=request,
            category=category,
            category_reason=category_reason,
            departments=departments,
            tools=tools,
            ai_choice=ai_choice,
            free_sufficient=free_sufficient,
            free_sufficient_reason=(
                "Seçilen kaynak mevcut CLI aboneliğini kullanır; ücretsiz API değildir, "
                "yeni API billing de başlatmaz."
                if plan_cli_selected
                else f"Seçilen katman '{ai_choice.tier}' -- {'ücretsiz' if free_sufficient else 'ücretli'} "
                "bir katman (bkz. AI seçim gerekçesi)."
            ),
            local_sufficient=local_sufficient,
            local_sufficient_reason=(
                "Yerel model (Ollama) bu görev için yeterli kabul edildi."
                if local_sufficient
                else "Yerel model (Ollama) tek başına yeterli kabul edilmedi (bkz. AI seçim gerekçesi)."
            ),
            paid_required=paid_required,
            paid_required_reason=(
                "Mevcut CLI aboneliği kullanılıyor; yeni ücretli API çağrısı/onayı gerekmiyor."
                if plan_cli_selected
                else "Ne yerel ne de ücretsiz kotalı bir seçenek yeterli/kullanılabilir değildi."
                if paid_required
                else "Ücretsiz bir katman (yerel/açık kaynak/ücretsiz servis) yeterli kabul edildi -- ücretli gerekmiyor."
            ),
            department_ai_choices=department_ai_choices,
        )

    def _department_reason(self, department_name: str) -> str:
        department = self.orchestrator.departments.get(department_name)
        if department is None:
            return "Kayıtlı olmayan departman."
        return department.description or f"{department_name} departmanı seçildi."

    # --- Self-improvement (Sprint 34 SELF IMPROVEMENT) -----------------------

    def review(
        self,
        plan: AIStrategyPlan,
        ai_discovery_report: Optional[dict] = None,
    ) -> SelfImprovementReview:
        """Görev sonunda (veya doğrudan bir plan üzerinden) değerlendirme.

        Yeni bir ölçüm İCAT ETMEZ -- yalnızca ``CostOptimizer.
        TASK_COST_PROFILES``'ın (ZATEN hesaplanmış) kalite/hız puanlarına
        ve (varsa) mission'ın ``ai_discovery`` department sonucuna
        (Sprint 17, ZATEN VAR) dayanır. ``ai_discovery_report``,
        çağıranın (mission çalıştıysa) ``task.metadata["report"]``'ini
        AYNEN geçirmesiyle doldurulur -- bu modül ``Mission``/``Task``
        tiplerine bağımlı DEĞİLDİR (gevşek bağlaşım).
        """

        task_type = self.cost_optimizer.classify(plan.request)
        profile = TASK_COST_PROFILES.get(task_type)

        if plan.ai_choice.tier == TIER_LOCAL_FREE:
            cheaper_possible = False
            cheaper_note = "Zaten en ucuz katman (yerel/ücretsiz) seçilmişti."
            faster_possible = False
            faster_note = "Zaten en hızlı/ücretsiz katman (yerel) seçilmişti."
        else:
            ollama = self.cost_optimizer.provider_manager.get("ollama")
            ollama_available = bool(ollama) and ollama.is_available()
            if ollama_available:
                cheaper_possible = True
                cheaper_note = (
                    "Yerel model (Ollama) kullanılabilir durumdaydı ama görev karmaşık "
                    f"sınıflandırıldığı ('{task_type}') için bulut/ücretli katmana geçildi -- "
                    "daha ucuz bir seçenek TEKNİK olarak vardı, kalite riskiyle tartılmalı."
                )
                faster_possible = True
                faster_note = "Yerel model kullanılabilirdi; ağ gecikmesi olmadan muhtemelen daha hızlı yanıt verirdi."
            else:
                cheaper_possible = False
                cheaper_note = "Yerel model (Ollama) bu ortamda kullanılamıyordu -- ücretsiz/ucuz alternatif yoktu."
                faster_possible = False
                faster_note = "Yerel model kullanılamadığı için hız karşılaştırması yapılamadı."

        if profile is not None and profile.quality_score < 70:
            quality_risk = True
            quality_risk_note = (
                f"Görev sınıfı '{task_type}' için CostOptimizer.TASK_COST_PROFILES kalite puanı "
                f"{profile.quality_score}/100 -- görece düşük, kalite kaybı riski var."
            )
        elif profile is not None:
            quality_risk = False
            quality_risk_note = (
                f"Görev sınıfı '{task_type}' için kalite puanı {profile.quality_score}/100 -- "
                "seçilen katman için yeterli kabul edildi."
            )
        else:
            quality_risk = False
            quality_risk_note = f"Görev sınıfı '{task_type}' için bir CostOptimizer profili yok (veri yok)."

        if ai_discovery_report is None:
            new_free_model = False
            # Sprint 36 düzeltmesi: bu metin, mission'da ai_discovery
            # departmanı hiç SEÇİLMEDİĞİNDE bile CEO raporunda (SELF
            # CHECK bölümü) otomatik gösteriliyor -- "AI Discovery"
            # sözcüğünü İÇERMEMESİ gerekir, aksi halde Sprint 17'nin
            # "ai_discovery seçilmediyse raporda 'AI Discovery' hiç
            # GEÇMEMELİ" garantisini BOZAR (bkz. test_ai_discovery.py).
            new_free_model_note = (
                "Bu görevde GitHub dışı AI ekosistemi taraması çalışmadı (veri yok) -- "
                "yeni ücretsiz model çıkıp çıkmadığı bilinmiyor."
            )
        else:
            top = ai_discovery_report.get("top") or []
            free_count = sum(1 for item in top if item.get("cost_advantage", 0) >= 90)
            new_free_model = free_count > 0
            new_free_model_note = (
                f"AI Discovery: {ai_discovery_report.get('total_found', 0)} yeni aday bulundu, "
                f"{free_count} tanesi ücretsiz/açık-kaynak sinyali taşıyor."
                if top
                else "AI Discovery çalıştı ama yeni bir aday bulamadı."
            )

        return SelfImprovementReview(
            cheaper_ai_possible=cheaper_possible,
            cheaper_ai_note=cheaper_note,
            faster_ai_possible=faster_possible,
            faster_ai_note=faster_note,
            quality_risk=quality_risk,
            quality_risk_note=quality_risk_note,
            new_free_model_available=new_free_model,
            new_free_model_note=new_free_model_note,
        )

    # --- CEO'ya gösterime hazır metin (bkz. Sprint 34 KARAR) -----------------

    def format_report(self, plan: AIStrategyPlan, review: Optional[SelfImprovementReview] = None) -> str:
        """``plan``'ı (ve varsa ``review``'i) CEO raporuna eklenmeye hazır,
        okunabilir bir metne çevirir. CEO'ya BAĞLANMASI (``report_builder.py``
        içine gömülmesi) bu sprintin kapsamı DIŞINDA bırakıldı -- bkz. sınıf
        docstring'i."""

        lines = [
            "AI STRATEGY",
            f"İstek: {plan.request}",
            f"Kategori: {plan.category.value} -- {plan.category_reason}",
            "",
            "Departmanlar:",
        ]
        for choice in plan.departments:
            lines.append(f"  - {choice.name}: {choice.reason}")
        if not plan.departments:
            lines.append("  (hiçbiri seçilmedi)")

        lines.append("")
        lines.append("Tool'lar:")
        for tool in plan.tools:
            lines.append(f"  - {tool.name}: {tool.reason}")
        if not plan.tools:
            lines.append("  (hiçbiri gerekmiyor)")

        lines.extend([
            "",
            "AI seçimi:",
            f"  Sağlayıcı: {plan.ai_choice.provider} ({plan.ai_choice.model})",
            f"  Katman: {plan.ai_choice.tier}",
            f"  Neden: {plan.ai_choice.reason}",
            f"  Tahmini maliyet: {plan.ai_choice.estimated_cost}",
            f"  Güven: {plan.ai_choice.confidence}/100",
            f"  Yedek: {plan.ai_choice.fallback_provider or '-'}",
            "",
            f"Ücretsiz yeterli mi: {'evet' if plan.free_sufficient else 'hayır'} -- {plan.free_sufficient_reason}",
            f"Yerel yeterli mi: {'evet' if plan.local_sufficient else 'hayır'} -- {plan.local_sufficient_reason}",
            f"Ücretli gerekli mi: {'evet' if plan.paid_required else 'hayır'} -- {plan.paid_required_reason}",
        ])

        if review is not None:
            lines.extend([
                "",
                "Self-improvement:",
                f"  Daha ucuz AI mümkün müydü: {'evet' if review.cheaper_ai_possible else 'hayır'} -- {review.cheaper_ai_note}",
                f"  Daha hızlı AI mümkün müydü: {'evet' if review.faster_ai_possible else 'hayır'} -- {review.faster_ai_note}",
                f"  Kalite riski var mı: {'evet' if review.quality_risk else 'hayır'} -- {review.quality_risk_note}",
                f"  Yeni ücretsiz model var mı: {'evet' if review.new_free_model_available else 'hayır'} -- {review.new_free_model_note}",
            ])

        return "\n".join(lines)
