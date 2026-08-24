from __future__ import annotations

from src.mission.models import Mission
from src.research_loop.models import ImprovementCandidate

# Sprint 37: "her bulgu için sor: bu bulgu kullanıcının hedefini GERÇEKTEN
# geliştiriyor mu?" -- yeni bir puanlama sistemi İCAT EDİLMEZ. ai_discovery
# departmanının ZATEN ürettiği ``EvolutionScorer`` alanları (goal_fit/
# safety/cost_advantage/expected_value -- bkz. src/evolution/scorer.py)
# KALİTE+HEDEFE UYGUNLUK+MALİYET+GÜVENLİK'i, evaluation departmanının
# ZATEN ürettiği ``RepoEvaluation`` alanları (risk_level/integration_
# difficulty -- bkz. src/evaluation/evaluation_engine.py) BAKIM+ENTEGRASYON
# RİSKİ'ni karşılar. Bu modül yalnızca bu ZATEN VAR OLAN sinyalleri
# ``ImprovementCandidate`` sözleşmesine EŞLER.
FREE_COST_ADVANTAGE_THRESHOLD = 90


def _ai_discovery_candidates(mission: Mission, round_number: int) -> list[ImprovementCandidate]:
    task = next((t for t in mission.tasks if t.agent == "ai_discovery"), None)
    if task is None or not task.metadata:
        return []

    report = task.metadata.get("report") or {}
    top = report.get("top") or []

    candidates: list[ImprovementCandidate] = []
    for item in top:
        cost_advantage = int(item.get("cost_advantage", 0))
        is_free = cost_advantage >= FREE_COST_ADVANTAGE_THRESHOLD
        candidates.append(
            ImprovementCandidate(
                goal=mission.title,
                source="ai_discovery",
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                finding=str(item.get("summary", ""))[:400],
                gain_note=(
                    f"goal_fit={item.get('goal_fit', 0)}/100, expected_value={item.get('expected_value', 0)}/100 "
                    f"(EvolutionScorer, arama sorgusu: '{item.get('query', '')}')."
                ),
                risk_note=(
                    f"safety={item.get('safety', 0)}/100 (EvolutionScorer heuristik güvenlik puanı; "
                    "yüksek riskli terim taraması, gerçek bir güvenlik denetimi DEĞİL)."
                ),
                recommendation=(
                    "Sandbox'ta statik analiz ile incele (yalnızca GitHub repo URL'siyse mümkün)."
                    if "github.com" in str(item.get("url", ""))
                    else "Önce resmi kaynağından (dokümantasyon/README) doğrula, sonra Sandbox/Integration ile değerlendir."
                ),
                score=int(item.get("score", 0)),
                cost_advantage=cost_advantage,
                round_number=round_number,
            )
        )
    return candidates


def _evaluation_candidates(mission: Mission, round_number: int) -> list[ImprovementCandidate]:
    task = next((t for t in mission.tasks if t.agent == "evaluation"), None)
    if task is None or not task.metadata:
        return []

    report = task.metadata.get("report") or {}
    entries = report.get("candidates") or []

    candidates: list[ImprovementCandidate] = []
    for entry in entries:
        repo = entry.get("repo")
        evaluation = entry.get("evaluation")
        if repo is None or evaluation is None:
            continue

        sandbox_verdict = entry.get("sandbox_verdict", "?")
        integration_plan = entry.get("integration_plan")
        merge_ready = bool(integration_plan and getattr(integration_plan, "merge_ready", False))

        candidates.append(
            ImprovementCandidate(
                goal=mission.title,
                source="evaluation",
                title=repo.full_name,
                url=repo.url,
                finding=evaluation.recommendation,
                gain_note=(
                    f"overall={evaluation.overall_score:.0f}/100, "
                    f"relevance={evaluation.relevance_score:.0f}/100 (EvaluationEngine)."
                ),
                risk_note=(
                    f"risk={evaluation.risk_level}, integration_difficulty={evaluation.integration_difficulty}, "
                    f"sandbox={sandbox_verdict}."
                ),
                recommendation=(
                    "İnsan onayıyla Integration bölümündeki entegrasyon sırasını uygula."
                    if merge_ready and evaluation.risk_level == "LOW"
                    else "Sandbox'ta statik analiz sonucunu ve Integration planını insan gözden geçirmesiyle doğrula."
                ),
                score=int(round(evaluation.overall_score)),
                cost_advantage=0,
                round_number=round_number,
            )
        )
    return candidates


def build_candidates(mission: Mission, round_number: int = 1) -> tuple[ImprovementCandidate, ...]:
    """Bu mission'ın (bir araştırma turunun) GERÇEK ai_discovery/evaluation
    sonuçlarından ``ImprovementCandidate`` üretir. Departman hiç
    seçilmediyse veya sonuç üretmediyse boş tuple döner -- uydurma aday
    ÜRETİLMEZ."""

    return tuple(_ai_discovery_candidates(mission, round_number) + _evaluation_candidates(mission, round_number))


def evidence_urls(mission: Mission) -> tuple[str, ...]:
    """Bu mission turunda bulunan tüm kanıt URL'leri (ai_discovery +
    github) -- yalnızca ``sufficiency.has_repeated_evidence``'ın iki tur
    arasındaki çakışmayı tespit edebilmesi için toplanır."""

    urls: list[str] = []

    ai_discovery_task = next((t for t in mission.tasks if t.agent == "ai_discovery"), None)
    if ai_discovery_task and ai_discovery_task.metadata:
        report = ai_discovery_task.metadata.get("report") or {}
        for item in report.get("top") or []:
            url = str(item.get("url", "")).strip()
            if url:
                urls.append(url)

    github_task = next((t for t in mission.tasks if t.agent == "github"), None)
    if github_task and github_task.metadata:
        report = github_task.metadata.get("report") or {}
        for item in report.get("top") or []:
            repo = item.get("repo")
            url = getattr(repo, "url", "") if repo is not None else ""
            if url:
                urls.append(url)

    return tuple(urls)
