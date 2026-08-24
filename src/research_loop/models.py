from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Yalnızca statik tip kontrolü için -- ``src.mission.models.Mission``'a
    # çalışma zamanı bağımlılığı YOKTUR (``src.mission.models`` zaten bu
    # paketten habersiz kalmalı -- Sprint 37 KURAL: ikinci bir Mission
    # sistemi İCAT EDİLMEZ, yalnızca ZATEN VAR OLAN ``Mission``'ı sarar).
    from src.mission.models import Mission


@dataclass(frozen=True)
class ImprovementCandidate:
    """Sprint 37 SELF IMPROVEMENT çıktısı: HEDEF/BULGU/KAZANÇ/RİSK/ÖNERİ.

    Yeni bir puanlama sistemi İCAT ETMEZ -- ``score``/``cost_advantage``
    alanları, kaynağına göre ZATEN VAR OLAN ``EvolutionScorer.rank()``
    (ai_discovery) veya ``EvaluationEngine.evaluate()`` (evaluation)
    çıktısından AYNEN kopyalanır (bkz. ``candidate_builder.py``).
    """

    goal: str
    source: str  # "ai_discovery" | "evaluation"
    title: str
    url: str
    finding: str
    gain_note: str
    risk_note: str
    recommendation: str
    score: int
    cost_advantage: int
    round_number: int


@dataclass(frozen=True)
class LoopRound:
    """Bir araştırma turunun sonucu -- ``mission`` ZATEN VAR OLAN
    ``CEO.create_mission``/``dispatch_mission``'ın döndürdüğü GERÇEK
    ``Mission`` nesnesidir, yeniden üretilmez."""

    index: int
    request: str
    mission: "Mission"
    sufficient: bool
    reason: str
    evidence_urls: tuple[str, ...]


@dataclass(frozen=True)
class ResearchLoopResult:
    """``ResearchLoopEngine.run()``'ın tam sonucu -- CEO raporuna
    (``build_research_loop_report``) ve canlı kabul testi kontrol
    listesine cevap verecek her alanı taşır."""

    goal: str
    rounds: tuple[LoopRound, ...]
    stopped_reason: str
    candidates: tuple[ImprovementCandidate, ...]
    expert_review_text: Optional[str]
    expert_review_reason: str
    knowledge_reused: bool
    knowledge_note: str
    report_path: Optional[str] = None
