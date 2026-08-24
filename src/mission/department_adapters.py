from __future__ import annotations

import re
import time
from typing import Callable, Optional

from src.agents.automation_agent import AutomationAgent
from src.agents.base_agent import BaseAgent
from src.agents.browser_agent import BrowserAgent
from src.agents.coding_agent import CodingAgent
from src.agents.finance_agent import FinanceAgent
from src.finance.learning import FinanceLearningAgent
from src.agents.media_agent import MediaAgent
from src.agents.research_agent import ResearchAgent
from src.evaluation.evaluation_engine import EvaluationEngine
from src.evolution.collector import EvolutionCollector
from src.evolution.scorer import EvolutionScorer
from src.github.errors import GitHubIntelligenceError
from src.github.github_intelligence import GitHubIntelligence
from src.github.scoring import build_reason
from src.integration.integration_planner import IntegrationPlanner
from src.jobs.task import Task
from src.mission.target_resolver import (  # noqa: F401 -- geriye dönük uyumluluk için yeniden dışa aktarım
    MISSION_TYPE_TO_GITHUB_CATEGORY,
    Target,
    TargetKind,
    TargetResolver,
    resolve_search_category,
    target_matches_repo,
)
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


# Sprint 21'de burada tanımlanmış olan ``MISSION_TYPE_TO_GITHUB_CATEGORY``
# ve ``resolve_search_category()``, Sprint 31A'da ``target_resolver.py``'ye
# TAŞINDI (yukarıdaki import bloğundan yeniden dışa aktarılıyor -- geriye
# dönük uyumluluk, davranış BİREBİR AYNI). Aşağıdaki 4 adaptör artık bu
# fonksiyonu DOĞRUDAN çağırmıyor: Mission oluşturulurken TEK bir kez
# üretilmiş ``Target``'ı (``task.metadata["target"]``) okuyor -- kategori
# çözümlemesi yalnızca ``target.kind == CATEGORY`` iken, TEK bir yerden
# (``TargetResolver`` içinde) devreye giriyor (bkz. Sprint 31B tasarımı).


# Sprint 33B: README'nin kendisi CEO raporuna HAM olarak basılmaz --
# yeni bir LLM/Agent/Provider İCAT ETMEDEN, sabit anahtar kelime/madde-
# işareti sezgileriyle kısa, kontrollü bir özet çıkarılır (proje amacı /
# temel özellikler / kurulum-bağımlılık sinyalleri / güvenlik notları).
_FEATURE_LINE_PATTERN = re.compile(r"^\s*[-*•]\s+(.*)")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_README_SETUP_KEYWORDS = (
    "install", "npm install", "pip install", "requirements.txt", "docker",
    "pnpm", "yarn", "prerequisite", "kurulum", "bağımlılık", "dependency",
    "dependencies", "setup", ".env",
)
_README_SECURITY_KEYWORDS = (
    "api key", "api_key", "secret", "token", "password", "credential",
    "oauth", "güvenlik", "security", "vulnerability",
)
_README_SUMMARY_MAX_CHARS = 200
_README_FEATURE_MAX_ITEMS = 5


def summarize_readme(text: Optional[str]) -> Optional[dict]:
    """Bir README metninden (``RepoData.readme_excerpt``) kısa, kontrollü
    bir özet üretir: proje amacı, temel özellikler (madde işaretli
    satırlar), kurulum/bağımlılık sinyalleri, güvenlik açısından önemli
    noktalar. Salt-deterministik/sezgisel (regex + anahtar kelime) --
    hiçbir LLM çağrısı YAPMAZ. Metin yoksa/boşsa ``None`` döner."""

    if not text or not text.strip():
        return None

    lines = text.splitlines()

    purpose = ""
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue  # başlık satırı -- proje adı DEĞİL, gerçek amaç cümlesi aranıyor
        cleaned = _MARKDOWN_IMAGE_PATTERN.sub("", stripped)
        cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned).strip()
        if len(cleaned) > 15 and not cleaned.lower().startswith(("http://", "https://")):
            purpose = cleaned[:_README_SUMMARY_MAX_CHARS]
            break

    features: list[str] = []
    for raw_line in lines:
        match = _FEATURE_LINE_PATTERN.match(raw_line)
        if not match:
            continue
        feature = match.group(1).strip()
        if feature and feature not in features:
            features.append(feature[:120])
        if len(features) >= _README_FEATURE_MAX_ITEMS:
            break

    lowered = text.lower()
    setup_signals = sorted({kw for kw in _README_SETUP_KEYWORDS if kw in lowered})
    security_notes = sorted({kw for kw in _README_SECURITY_KEYWORDS if kw in lowered})

    return {
        "purpose": purpose or "(README'den net bir amaç cümlesi çıkarılamadı)",
        "features": features,
        "setup_signals": setup_signals,
        "security_notes": security_notes,
    }


def _resolve_task_target(task: Task) -> Target:
    """``task.metadata["target"]``'ı okur; yoksa (Mission'ı doğrudan,
    ``MissionEngine`` atlanarak oluşturan eski/test kodu için) AYNI
    ``TargetResolver`` ile anlık olarak çözümler -- davranış AYNI kalır,
    yalnızca "bir kez mi, anlık mı" değişir."""

    target = task.metadata.get("target")
    if target is not None:
        return target
    return TargetResolver().resolve(
        str(getattr(task, "target", "")), mission_type=task.metadata.get("mission_type")
    )


def search_target_repositories(
    intelligence, target: Target, *, max_results: int, fetch_readme: bool = False,
):
    """Search a named project first and use its category only as fallback."""
    if target.requested_name:
        named_search = getattr(intelligence, "search_named_target", None)
        if named_search is not None:
            repos = named_search(
                target.requested_name,
                max_results=max_results,
                fetch_readme=fetch_readme,
            )
            if repos:
                return repos, target.requested_name
    category = target.category_hint or "ai agent"
    search_kwargs = {"max_results": max_results}
    if fetch_readme:
        search_kwargs["fetch_readme"] = True
    repos = intelligence.search(category, **search_kwargs)
    # Category search is discovery, not evidence by itself.  Apply the same
    # semantic relevance model used by Evaluation so a high-star but
    # off-domain repository cannot count as a capability candidate.
    from src.evaluation.relevance import RELEVANCE_LOW_THRESHOLD, relevance_score
    repos = [repo for repo in repos if relevance_score(repo) >= RELEVANCE_LOW_THRESHOLD]
    if target.requested_name:
        repos = [repo for repo in repos if target_matches_repo(target, repo)]
    return repos, category


class GitHubDepartmentAgent(BaseAgent):
    """``github`` departmanını gerçek ``GitHubIntelligence.search()``'e bağlar."""

    def __init__(self, intelligence: Optional[GitHubIntelligence] = None) -> None:
        super().__init__("GitHub Department Agent")
        self.intelligence = intelligence or GitHubIntelligence()

    def execute(self, task: Task) -> str:
        target = _resolve_task_target(task)

        # Sprint 31A: REPOSITORY hedefi -- kategori araması YAPILMAZ,
        # doğrudan owner/repo üzerinden TEK repo getirilir (bkz. adım 6).
        if target.kind == TargetKind.REPOSITORY:
            # Sprint 33B: kullanıcı açıkça TEK bir repo istediğinde (ör.
            # "github.com/owner/repo"), README de bu tek, deliberate hedef
            # için ucuz (tek istek) bir ek çağrıyla çekilir.
            try:
                repo = self.intelligence.get_repository(target.full_name, fetch_readme=True)
            except GitHubIntelligenceError as error:
                task.metadata["report"] = {
                    "category": None, "target": target.full_name, "total_found": 0, "top": [],
                    "evidence_repo": None, "readme_summary": None,
                }
                return f"GitHubIntelligence.get_repository('{target.full_name}'): {error}"

            quality, risk = self.intelligence.score(repo)
            scored = [{
                "repo": repo,
                "quality_score": quality,
                "risk_score": risk,
                "reason": build_reason(repo, quality, risk),
            }]
            task.metadata["report"] = {
                "category": None, "target": target.full_name, "total_found": 1, "top": scored,
                "evidence_repo": repo.full_name,
                "readme_summary": summarize_readme(repo.readme_excerpt),
            }
            return (
                f"GitHubIntelligence.get_repository('{target.full_name}') -> "
                f"{repo.full_name} ({repo.stars}★) {repo.url}"
            )

        category = target.category_hint or "ai agent"
        # Sprint 33B: mission genelinde bir "kanıt reposu" belirlendiyse
        # (bkz. DepartmentOrchestrator._resolve_evidence_repo -- yalnızca
        # AI Validation Pipeline gerçekten çalışıyorsa dolu gelir), o
        # adayın README'si de aynı arama isteğiyle (ek istek YAPMADAN)
        # çekilir; aksi halde (sade GitHub taraması) davranış DEĞİŞMEZ.
        evidence_repo = task.metadata.get("evidence_repo")
        repos, search_query = search_target_repositories(
            self.intelligence, target, max_results=GITHUB_REPORT_SEARCH_LIMIT,
            fetch_readme=bool(evidence_repo),
        )

        if not repos:
            task.metadata["report"] = {
                "category": category, "total_found": 0, "top": [],
                "evidence_repo": evidence_repo, "readme_summary": None,
            }
            return f"GitHubIntelligence.search('{search_query}'): repo bulunamadı."

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

        readme_summary = None
        if evidence_repo:
            match = next((item for item in scored if item["repo"].full_name == evidence_repo), None)
            if match is not None:
                readme_summary = summarize_readme(match["repo"].readme_excerpt)

        task.metadata["report"] = {
            "category": category,
            "total_found": len(repos),
            "top": scored[:5],
            "evidence_repo": evidence_repo,
            "readme_summary": readme_summary,
        }

        lines = [f"GitHubIntelligence.search('{search_query}') -> {len(repos)} repo bulundu."]
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
        target = _resolve_task_target(task)

        # Sprint 31A: REPOSITORY hedefi -- kategori araması YAPILMAZ,
        # doğrudan owner/repo üzerinden TEK repo değerlendirilir.
        # Sprint 32: ``fetch_readme=True`` -- EvaluationEngine.evaluate()
        # -> relevance_score() -> _readme_bonus() ZATEN ``repo.
        # readme_excerpt``'i puanlamada kullanıyordu (bkz.
        # src/evaluation/relevance.py) ama hiçbir çağıran bunu
        # doldurmuyordu (hep ``None``); burada AÇILIYOR -- yeni bir
        # puanlama/özellik İCAT EDİLMEDİ, zaten var olan bir yol devreye
        # sokuluyor.
        if target.kind == TargetKind.REPOSITORY:
            category = None
            try:
                repos = [self.intelligence.get_repository(target.full_name, fetch_readme=True)]
            except GitHubIntelligenceError as error:
                task.metadata["report"] = {
                    "category": None, "candidates": [], "summary": None,
                }
                return f"EvaluationEngine: get_repository('{target.full_name}') başarısız: {error}"
        else:
            category = target.category_hint or "ai agent"
            repos, _ = search_target_repositories(
                self.intelligence, target,
                max_results=EVALUATION_CANDIDATE_LIMIT, fetch_readme=True,
            )

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
        target = _resolve_task_target(task)
        evidence_repo = task.metadata.get("evidence_repo")
        repo, evaluation = self._pick_candidate(target, evidence_repo=evidence_repo)
        if repo is None or evaluation is None:
            task.metadata["report"] = {"repo": None, "result": None, "duration_seconds": 0.0}
            if target.kind == TargetKind.REPOSITORY:
                return f"SandboxManager: '{target.full_name}' repo'su getirilemedi."
            category = target.category_hint or "ai agent"
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

    def _pick_candidate(self, target: Target, evidence_repo: Optional[str] = None):
        # Sprint 31A: REPOSITORY hedefi -- kategori araması YAPILMAZ,
        # doğrudan owner/repo üzerinden TEK repo getirilip değerlendirilir.
        if target.kind == TargetKind.REPOSITORY:
            try:
                repo = self.intelligence.get_repository(target.full_name)
            except GitHubIntelligenceError:
                return None, None
            return repo, self.engine.evaluate(repo)

        category = target.category_hint or "ai agent"
        repos, _ = search_target_repositories(self.intelligence, target, max_results=5)
        if not repos:
            return None, None

        # Sprint 33B: mission genelinde bir "kanıt reposu" belirlendiyse
        # (bkz. DepartmentOrchestrator._resolve_evidence_repo), Evaluation/
        # Sandbox/Integration/README'in AYNI repoyu değerlendirmesi için
        # önce bu arama sonuçları arasında ONU arar -- bulunamazsa (nadir,
        # farklı bir arama anına denk gelme ihtimali) mevcut top_candidates
        # mantığına GÜVENLİ şekilde düşer.
        if evidence_repo:
            matched = next((r for r in repos if r.full_name == evidence_repo), None)
            if matched is not None:
                return matched, self.engine.evaluate(matched)

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
        target = _resolve_task_target(task)
        evidence_repo = task.metadata.get("evidence_repo")

        # Sprint 31A: REPOSITORY hedefi -- kategori araması YAPILMAZ,
        # doğrudan owner/repo üzerinden TEK repo entegrasyon için analiz edilir.
        if target.kind == TargetKind.REPOSITORY:
            try:
                repo = self.intelligence.get_repository(target.full_name)
            except GitHubIntelligenceError as error:
                task.metadata["report"] = {"repo": None, "plan": None}
                return f"IntegrationPlanner: get_repository('{target.full_name}') başarısız: {error}"
            evaluation = self.engine.evaluate(repo)
        else:
            category = target.category_hint or "ai agent"
            repos, _ = search_target_repositories(self.intelligence, target, max_results=5)
            if not repos:
                task.metadata["report"] = {"repo": None, "plan": None}
                return f"IntegrationPlanner: '{category}' kategorisinde aday bulunamadı."

            # Sprint 33B: mission genelinde bir "kanıt reposu" belirlendiyse,
            # Evaluation/Sandbox/Integration/README'in AYNI repoyu
            # değerlendirmesi için önce bu arama sonuçları arasında ONU
            # arar -- bulunamazsa mevcut top_candidates mantığına düşer.
            matched = next((r for r in repos if evidence_repo and r.full_name == evidence_repo), None)
            if matched is not None:
                repo = matched
                evaluation = self.engine.evaluate(repo)
            else:
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
            "learning": FinanceLearningAgent(),
            "browser": BrowserAgent(),
            "github": GitHubDepartmentAgent(),
            "evaluation": EvaluationDepartmentAgent(),
            "sandbox": SandboxDepartmentAgent(),
            "integration": IntegrationDepartmentAgent(),
            "ai_discovery": AIDiscoveryDepartmentAgent(),
            # Sprint 39: "media" (içerik/senaryo/sahne/seslendirme-planı
            # üretimi, bkz. src.media) ve "automation" (yayın-öncesi
            # kontrol listesi, bkz. src.automation) artık GERÇEK, bağımsız
            # alt sistemlere bağlı -- ikisi de yalnızca ÖNERİ/PLAN üretir,
            # hiçbir dosya/hesap/yayın işlemi ÇALIŞTIRMAZ (bkz. o
            # modüllerin kendi docstring'leri).
            "media": MediaAgent(),
            "automation": AutomationAgent(),
            "coding": CodingAgent(),
        }

    def resolve(self, department_name: str) -> Optional[Callable[[Task], object]]:
        agent = self._agents.get(department_name)
        return agent.to_handler() if agent is not None else None
