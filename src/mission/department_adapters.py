from __future__ import annotations

import time
from typing import Callable, Optional

from src.agents.base_agent import BaseAgent
from src.agents.browser_agent import BrowserAgent
from src.agents.finance_agent import FinanceAgent
from src.agents.research_agent import ResearchAgent
from src.evaluation.evaluation_engine import EvaluationEngine
from src.evolution.collector import EvolutionCollector
from src.evolution.scorer import EvolutionScorer
from src.github.categories import SUPPORTED_CATEGORIES
from src.github.github_intelligence import GitHubIntelligence
from src.github.scoring import build_reason
from src.integration.integration_planner import IntegrationPlanner
from src.jobs.task import Task
from src.mission.models import MissionType
from src.sandbox.sandbox_manager import SandboxManager

# Sprint 16 (CEO Report Engine): her adaptör, kendi ÇOKTAN HESAPLADIĞI
# gerçek nesneleri (RepoData/RepoEvaluation/SandboxResult/IntegrationPlan)
# ``task.metadata["report"]`` altında da SAKLAR -- yeni bir ölçüm/analiz
# YAPMADAN, yalnızca zaten üretilmiş sonucu CEO rapor katmanının (bkz.
# ``src.mission.report_builder``) tekrar ağ isteği atmadan okuyabilmesi
# için. ``execute()``'in insan-okunur metin dönüşü DEĞİŞMEDİ.
GITHUB_REPORT_SEARCH_LIMIT = 12

# Sprint 15: department -> gerçek modül adaptör katmanı. Hiçbir yeni
# AI/Provider/Department/Mission/Planner/Execution/Worker İCAT ETMEZ —
# yalnızca ZATEN VAR OLAN sınıfları (GitHubIntelligence, EvaluationEngine,
# SandboxManager, IntegrationPlanner, ResearchAgent, FinanceAgent,
# BrowserAgent) ``Task.handler`` sözleşmesine (``Callable[[Task], Any]``,
# bkz. ``src.jobs.task.Task``) bağlar.


# Sprint 21 düzeltmesi: metin İngilizce kategori adını içermediğinde (ki
# Türkçe mission metinlerinin neredeyse tamamı böyledir), önceden HER ZAMAN
# "ai agent"a düşülüyordu -- mission zaten sınıflandırılmış bir MissionType
# taşıdığı halde bu bilgi kullanılmıyordu. Bu eşleme, mevcut MissionType
# sınıflandırmasını (Sprint 13) mevcut GitHub kategorileriyle (Sprint 9,
# ``SUPPORTED_CATEGORIES``) BİRLEŞTİRİR -- yeni bir sınıflandırma/kategori
# sistemi İCAT ETMEZ. CODE/GITHUB/AI_DISCOVERY için "ai agent"/"llm" hâlâ
# en isabetli seçenektir (JARVIS'in kendisi bir AI agent'tır) -- bu artık
# kasıtlı bir eşleme, "hiçbiri eşleşmedi" varsayılanı değil.
MISSION_TYPE_TO_GITHUB_CATEGORY: dict[MissionType, str] = {
    MissionType.YOUTUBE: "youtube automation",
    MissionType.BROWSER: "browser agent",
    MissionType.FINANCE: "finance ai",
    MissionType.MEDIA: "video generation",
    MissionType.LEARNING: "llm",
    MissionType.AI_DISCOVERY: "llm",
    MissionType.CODE: "ai agent",
    MissionType.GITHUB: "ai agent",
    MissionType.SECURITY: "ai agent",
    MissionType.SOCIAL_MEDIA: "ai agent",
    MissionType.AUTOMATION: "ai agent",
    MissionType.RESEARCH: "ai agent",
}


def resolve_search_category(text: str, mission_type: Optional[MissionType] = None) -> str:
    """Bir GitHub arama kategorisi çıkarır.

    Departman görevlerinin ``target``'ı bir Mission başlığı (serbest
    Türkçe metin), GitHub arama kategorisi (İngilizce, sabit 10 seçenek
    -- bkz. ``SUPPORTED_CATEGORIES``) DEĞİLDİR. Öncelik: (1) metin
    kategorilerden birini kelimesi kelimesine içeriyorsa o kullanılır;
    (2) yoksa ve ``mission_type`` verildiyse ``MISSION_TYPE_TO_GITHUB_CATEGORY``
    eşlemesi kullanılır; (3) o da yoksa güvenli/genel "ai agent"
    varsayılanına düşülür.
    """

    lowered = (text or "").lower()
    for category in SUPPORTED_CATEGORIES:
        if category in lowered:
            return category
    if mission_type is not None:
        mapped = MISSION_TYPE_TO_GITHUB_CATEGORY.get(mission_type)
        if mapped:
            return mapped
    return "ai agent"


class GitHubDepartmentAgent(BaseAgent):
    """``github`` departmanını gerçek ``GitHubIntelligence.search()``'e bağlar."""

    def __init__(self, intelligence: Optional[GitHubIntelligence] = None) -> None:
        super().__init__("GitHub Department Agent")
        self.intelligence = intelligence or GitHubIntelligence()

    def execute(self, task: Task) -> str:
        category = resolve_search_category(
            str(getattr(task, "target", "")), mission_type=task.metadata.get("mission_type"),
        )
        repos = self.intelligence.search(category, max_results=GITHUB_REPORT_SEARCH_LIMIT)

        if not repos:
            task.metadata["report"] = {"category": category, "total_found": 0, "top": []}
            return f"GitHubIntelligence.search('{category}'): repo bulunamadı."

        # Sıralama için ZATEN VAR OLAN puanlama (GitHubIntelligence.score,
        # aynen GitHubIntelligence.recommend()'in kendi içinde yaptığı gibi)
        # -- yeni bir puanlama YAZILMADI, mevcut skor + gerekçe üretimi
        # yeniden kullanıldı.
        scored = []
        for repo in repos:
            quality, risk = self.intelligence.score(repo)
            scored.append({
                "repo": repo,
                "quality_score": quality,
                "risk_score": risk,
                "reason": build_reason(repo, quality, risk),
            })
        scored.sort(key=lambda item: (-item["quality_score"], item["risk_score"]))

        task.metadata["report"] = {
            "category": category,
            "total_found": len(repos),
            "top": scored[:5],
        }

        lines = [f"GitHubIntelligence.search('{category}') -> {len(repos)} repo bulundu."]
        for item in scored[:5]:
            lines.append(f"- {item['repo'].full_name} ({item['repo'].stars}★) {item['repo'].url}")
        return "\n".join(lines)


EVALUATION_CANDIDATE_LIMIT = 5


class EvaluationDepartmentAgent(BaseAgent):
    """``evaluation`` departmanı: Sprint 18 itibarıyla tek bir repoyu
    değerlendirmekle kalmaz, AI Validation Pipeline'ın TAMAMINI (GitHub
    bilgisi zaten elde -> Evaluation -> Sandbox (gerekiyorsa) ->
    IntegrationPlanner) her aday için ayrı ayrı çalıştırıp CEO'nun
    ÖNER/BEKLET/REDDET kararını üretebileceği ham veriyi toplar.

    Hiçbir yeni analiz/puanlama sistemi İCAT ETMEZ: ``GitHubIntelligence.
    search()``, ``EvaluationEngine.evaluate()``, ``SandboxManager.
    run_pipeline()`` (kendi mevcut ``_check_evaluation_gates`` eşiği
    sayesinde uygun olmayan adaylarda klonlama YAPMADAN erken durur --
    "sandbox gerekiyorsa çalıştır" davranışı buradan GELİYOR, yeni bir
    koşul YAZILMADI) ve ``IntegrationPlanner.analyze()`` -- dördü de
    ZATEN VAR. Departman görevleri Sprint 13 tasarımı gereği
    birbirinden BAĞIMSIZDIR (``depends_on`` yok), bu yüzden bu görev
    kendi gerçek girdisini (GitHub araması) kendisi üretir.
    """

    def __init__(
        self,
        intelligence: Optional[GitHubIntelligence] = None,
        engine: Optional[EvaluationEngine] = None,
        manager: Optional[SandboxManager] = None,
        planner: Optional[IntegrationPlanner] = None,
    ) -> None:
        super().__init__("Evaluation Department Agent")
        self.intelligence = intelligence or GitHubIntelligence()
        self.engine = engine or EvaluationEngine()
        self.manager = manager or SandboxManager()
        self.planner = planner or IntegrationPlanner()

    def execute(self, task: Task) -> str:
        category = resolve_search_category(
            str(getattr(task, "target", "")), mission_type=task.metadata.get("mission_type"),
        )
        repos = self.intelligence.search(category, max_results=EVALUATION_CANDIDATE_LIMIT)

        if not repos:
            task.metadata["report"] = {"category": category, "candidates": [], "summary": None}
            return f"EvaluationEngine: '{category}' kategorisinde değerlendirilecek repo bulunamadı."

        candidates = [self._validate_candidate(repo) for repo in repos]
        summary = self.engine.summary([c["evaluation"] for c in candidates])

        task.metadata["report"] = {
            "category": category,
            "candidates": candidates,
            "summary": summary,
        }

        lines = [f"AI Validation Pipeline -> {len(candidates)} aday (GitHub->Evaluation->Sandbox->Integration)."]
        for candidate in candidates:
            lines.append(
                f"- {candidate['repo'].full_name}: {candidate['evaluation'].overall_score}/100 "
                f"(risk={candidate['evaluation'].risk_level}, sandbox={candidate['sandbox_verdict']})"
            )
        lines.append(
            f"Özet: ortalama {summary['average_overall_score']}/100, "
            f"uygun {summary['suitable_count']}/{summary['count']}"
        )
        return "\n".join(lines)

    def _validate_candidate(self, repo) -> dict:
        """Tek bir aday için 1) GitHub bilgisi (zaten elimizde) 2)
        Evaluation 3) Sandbox (gerekiyorsa -- run_pipeline'ın kendi
        mevcut değerlendirme eşiği sayesinde) 4) IntegrationPlanner
        zincirini çalıştırır. Karar (ÖNER/BEKLET/REDDET) BURADA
        verilmez -- CEO Report Engine'e (bkz. ``report_builder.py``)
        aittir; bu yalnızca sandbox'ın PASS/FAIL etiketini (raporda
        okunabilir olsun diye) ekler."""

        evaluation = self.engine.evaluate(repo)
        sandbox_result = self.manager.run_pipeline(repo.url, evaluation, repo=repo)
        try:
            integration_plan = self.planner.analyze(sandbox_result, evaluation)
        finally:
            self.manager.cleanup(sandbox_result)

        sandbox_verdict = (
            "PASS"
            if sandbox_result.status.value == "ready_for_review"
            and sandbox_result.network_risk != "HIGH"
            and sandbox_result.execution_risk != "HIGH"
            and sandbox_result.dependency_risk != "HIGH"
            else "FAIL"
        )

        return {
            "repo": repo,
            "evaluation": evaluation,
            "sandbox_result": sandbox_result,
            "sandbox_verdict": sandbox_verdict,
            "integration_plan": integration_plan,
        }


class SandboxDepartmentAgent(BaseAgent):
    """``sandbox`` departmanını gerçek ``SandboxManager``'a bağlar.

    Gerçek bir repo üzerinde ``run_pipeline`` çalıştırabilmek için (yine
    bağımsız görev nedeniyle) kendi gerçek adayını (``GitHubIntelligence``
    + ``EvaluationEngine``) üretir, sonra ``SandboxManager.run_pipeline``'ı
    çağırır. İş bitince ``cleanup()`` ile sandbox dizinini SİLER (kalıcı
    disk kirliliği bırakmaz -- ``SandboxManager``'ın kendi sözleşmesi).
    """

    def __init__(
        self,
        intelligence: Optional[GitHubIntelligence] = None,
        engine: Optional[EvaluationEngine] = None,
        manager: Optional[SandboxManager] = None,
    ) -> None:
        super().__init__("Sandbox Department Agent")
        self.intelligence = intelligence or GitHubIntelligence()
        self.engine = engine or EvaluationEngine()
        self.manager = manager or SandboxManager()

    def execute(self, task: Task) -> str:
        repo, evaluation = self._pick_candidate(task)
        if repo is None or evaluation is None:
            category = resolve_search_category(
                str(getattr(task, "target", "")), mission_type=task.metadata.get("mission_type"),
            )
            task.metadata["report"] = {"repo": None, "result": None, "duration_seconds": 0.0}
            return f"SandboxManager: '{category}' kategorisinde denenecek repo bulunamadı."

        # Gerçek geçen süre -- SandboxManager hiçbir CPU/RAM ölçümü
        # YAPMIYOR (yalnızca statik analiz; kod hiç çalıştırılmıyor), bu
        # yüzden yeni bir kaynak profilleyici İCAT ETMEK yerine yalnızca
        # bu GERÇEK çağrının ne kadar sürdüğünü ölçüyoruz.
        started = time.monotonic()
        result = self.manager.run_pipeline(repo.url, evaluation, repo=repo)
        duration = time.monotonic() - started

        task.metadata["report"] = {
            "repo": repo,
            "result": result,
            "duration_seconds": round(duration, 2),
        }

        try:
            return (
                f"SandboxManager.run_pipeline('{repo.full_name}') -> "
                f"status={result.status.value}. {result.recommended_action}"
            )
        finally:
            self.manager.cleanup(result)

    def _pick_candidate(self, task: Task):
        category = resolve_search_category(
            str(getattr(task, "target", "")), mission_type=task.metadata.get("mission_type"),
        )
        repos = self.intelligence.search(category, max_results=5)
        if not repos:
            return None, None

        evaluations = self.engine.evaluate_many(repos)
        candidates = self.engine.top_candidates(evaluations, limit=1, only_suitable=False)
        if not candidates:
            return None, None

        evaluation = candidates[0]
        repo = next((r for r in repos if r.name == evaluation.name), repos[0])
        return repo, evaluation


class IntegrationDepartmentAgent(BaseAgent):
    """``integration`` departmanını gerçek ``IntegrationPlanner``'a bağlar.

    Aynı bağımsızlık nedeniyle kendi gerçek github -> evaluation ->
    sandbox zincirini üretip ``IntegrationPlanner.analyze()``'i gerçek
    girdilerle (``SandboxResult`` + ``RepoEvaluation``) çağırır.
    """

    def __init__(
        self,
        intelligence: Optional[GitHubIntelligence] = None,
        engine: Optional[EvaluationEngine] = None,
        manager: Optional[SandboxManager] = None,
        planner: Optional[IntegrationPlanner] = None,
    ) -> None:
        super().__init__("Integration Department Agent")
        self.intelligence = intelligence or GitHubIntelligence()
        self.engine = engine or EvaluationEngine()
        self.manager = manager or SandboxManager()
        self.planner = planner or IntegrationPlanner()

    def execute(self, task: Task) -> str:
        category = resolve_search_category(
            str(getattr(task, "target", "")), mission_type=task.metadata.get("mission_type"),
        )
        repos = self.intelligence.search(category, max_results=5)
        if not repos:
            task.metadata["report"] = {"repo": None, "plan": None}
            return f"IntegrationPlanner: '{category}' kategorisinde aday bulunamadı."

        evaluations = self.engine.evaluate_many(repos)
        candidates = self.engine.top_candidates(evaluations, limit=1, only_suitable=False)
        if not candidates:
            task.metadata["report"] = {"repo": None, "plan": None}
            return "IntegrationPlanner: değerlendirme sonrası aday kalmadı."

        evaluation = candidates[0]
        repo = next((r for r in repos if r.name == evaluation.name), repos[0])
        sandbox_result = self.manager.run_pipeline(repo.url, evaluation, repo=repo)

        try:
            plan = self.planner.analyze(sandbox_result, evaluation)
            task.metadata["report"] = {"repo": repo, "plan": plan}
            return f"IntegrationPlanner.analyze('{repo.full_name}') -> {plan.summary}"
        finally:
            self.manager.cleanup(sandbox_result)


class AIDiscoveryDepartmentAgent(BaseAgent):
    """``ai_discovery`` departmanını (Sprint 17) gerçek
    ``EvolutionCollector``/``EvolutionScorer``'a bağlar.

    Bu ikisi de ZATEN VAR (bu sprintten önce yazılmış): ``EvolutionCollector``
    ``WebSearchTool`` (gerçek DuckDuckGo araması) ile GitHub'ın dışındaki AI
    ekosistemini (HuggingFace, Ollama, OpenRouter, Anthropic, OpenAI,
    Gemini, DeepSeek, Qwen, Mistral, NVIDIA, Reddit, ...) tarar;
    ``EvolutionScorer`` bulunanları (zaten var olan, mevcut) sezgisel
    ölçütlerle (hedef uyumu/güvenlik/maliyet avantajı/beklenen değer)
    puanlar. Yeni bir arama motoru, LLM çağrısı veya puanlama sistemi
    İCAT EDİLMEDİ -- ``EvolutionManager.scan()``'in LLM-sentezli
    (ollama) yolu YERİNE, CEO raporunda yapılandırılmış/deterministik
    bir tablo gösterebilmek için ``collector``+``scorer`` doğrudan
    kullanıldı.
    """

    def __init__(
        self,
        collector: Optional[EvolutionCollector] = None,
        scorer: Optional[EvolutionScorer] = None,
    ) -> None:
        super().__init__("AI Discovery Department Agent")
        self.collector = collector or EvolutionCollector()
        self.scorer = scorer or EvolutionScorer()

    def execute(self, task: Task) -> str:
        focus = str(getattr(task, "target", "")).strip()
        collected = self.collector.collect(focus=focus)

        if not collected:
            task.metadata["report"] = {"focus": focus, "total_found": 0, "top": []}
            return "EvolutionCollector: yeni AI aracı/modeli bulunamadı."

        ranked = self.scorer.rank(collected, limit=8)
        task.metadata["report"] = {
            "focus": focus,
            "total_found": len(collected),
            "top": ranked,
        }

        lines = [
            f"EvolutionCollector.collect() -> {len(collected)} aday bulundu; "
            f"EvolutionScorer.rank() -> en iyi {len(ranked)}."
        ]
        for item in ranked[:5]:
            lines.append(f"- {item['title']} ({item['score']}/100) {item['url']}")
        return "\n".join(lines)


class DepartmentAdapterRegistry:
    """Department adı -> gerçek modüle bağlı ``Task.handler`` eşleşmesi.

    Yeni bir Department/Mission/Planner/Execution/Worker İCAT ETMEZ;
    yalnızca zaten var olan sınıfları (``BaseAgent`` alt sınıfları +
    ``GitHubIntelligence``/``EvaluationEngine``/``SandboxManager``/
    ``IntegrationPlanner``) ``Task.handler`` sözleşmesine bağlar.
    ``browser``/``research``/``finance`` için mevcut ``BaseAgent``
    alt sınıfları (``BrowserAgent``/``ResearchAgent``/``FinanceAgent``)
    doğrudan yeniden kullanılır -- ikinci bir ajan türü YAZILMAZ.
    """

    def __init__(self, agents: Optional[dict[str, BaseAgent]] = None) -> None:
        self._agents: dict[str, BaseAgent] = agents or {
            "research": ResearchAgent(),
            "finance": FinanceAgent(),
            "browser": BrowserAgent(),
            "github": GitHubDepartmentAgent(),
            "evaluation": EvaluationDepartmentAgent(),
            "sandbox": SandboxDepartmentAgent(),
            "integration": IntegrationDepartmentAgent(),
            "ai_discovery": AIDiscoveryDepartmentAgent(),
        }
        # "automation": Sprint 15 itibarıyla arkasında GERÇEK, bağımsız bir
        # JARVIS alt sistemi (ör. src/automation) YOK -- bu yüzden burada
        # KASITLI OLARAK bağlanmadı (bkz. rapor: "hâlâ eksik").

    def resolve(self, department_name: str) -> Optional[Callable[[Task], object]]:
        agent = self._agents.get(department_name)
        return agent.to_handler() if agent is not None else None
