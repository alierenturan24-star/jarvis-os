from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from src.config.settings import Settings
from src.knowledge.knowledge_base import KnowledgeBase
from src.providers.provider_manager import ProviderManager
from src.research_loop import candidate_builder, sufficiency
from src.research_loop.expert_review import decide_and_run_expert_review
from src.research_loop.models import ImprovementCandidate, LoopRound, ResearchLoopResult
from src.research_loop.report_builder import save as save_report

if TYPE_CHECKING:
    # Yalnızca statik tip kontrolü -- ``src.core.ceo`` bu modülü İÇE
    # AKTARACAĞI için (bkz. ``CEO.__init__``), çalışma zamanında ``CEO``'yu
    # içe aktarmak dairesel bir bağımlılık yaratır. Bu sınıf ``ceo``'yu
    # yalnızca ``create_mission``/``dispatch_mission`` sözleşmesiyle
    # (ördek tipleme) kullanır -- ikinci bir CEO/Mission sistemi İCAT
    # ETMEZ.
    from src.core.ceo import CEO


class ResearchLoopEngine:
    """Sprint 37 AUTONOMOUS RESEARCH & SELF-IMPROVEMENT LOOP.

    HEDEF -> PLAN -> ARAŞTIR -> KANIT TOPLA -> DEĞERLENDİR -> EKSİKLERİ
    BUL -> GEREKİRSE YENİDEN ARAŞTIR -> YETERLİ KANIT VARSA DUR -> CEO
    RAPORU.

    KURAL: yeni bir Mission/CEO/Strategy sistemi İCAT ETMEZ. Her tur,
    ZATEN VAR OLAN ``CEO.run_mission`` (create_mission + dispatch_mission,
    Sprint 13-36 DEĞİŞTİRİLMEDİ) çağrısıdır; durma kararı ZATEN VAR OLAN
    ``mission.self_check``'e (Sprint 36) dayanır. Yeni İCAT EDİLEN TEK
    şey: kaç tur (``max_rounds``) ve toplam ne kadar sürede (``max_seconds``)
    -- sonsuz döngü KESİNLİKLE olmaz.
    """

    def __init__(
        self,
        ceo: "CEO",
        knowledge: Optional[KnowledgeBase] = None,
        provider_manager: Optional[ProviderManager] = None,
    ) -> None:
        self.ceo = ceo
        self.knowledge = knowledge or KnowledgeBase()
        self.provider_manager = provider_manager or ProviderManager()

    def run(
        self,
        goal: str,
        max_rounds: Optional[int] = None,
        max_seconds: Optional[int] = None,
    ) -> ResearchLoopResult:
        goal = (goal or "").strip()
        max_rounds = max_rounds if max_rounds is not None else Settings.RESEARCH_LOOP_MAX_ROUNDS
        max_seconds = max_seconds if max_seconds is not None else Settings.RESEARCH_LOOP_MAX_SECONDS

        # Bölüm 8: MEMORY/KNOWLEDGE REUSE -- aynı hedef daha önce
        # araştırıldıysa bunu AÇIKÇA not eder; eskiyi GÜNCEL varsaymaz,
        # yalnızca bağlam olarak sunar (bu turlarda yeniden doğrulanır).
        prior = self.knowledge.find_research(goal)
        knowledge_reused = prior is not None
        knowledge_note = (
            f"Bu hedef daha önce araştırılmış ({prior.get('created_at', '?')}) -- önceki özet bağlam "
            "olarak kullanıldı, güncelliği varsayılmadı, bu turlarda yeniden doğrulandı."
            if prior is not None
            else "Bu hedef daha önce araştırılmamış (KnowledgeBase'de kayıt yok)."
        )

        rounds: list[LoopRound] = []
        all_candidates: list[ImprovementCandidate] = []
        request = goal
        stopped_reason = "Döngü hiç başlatılamadı."
        started_at = time.monotonic()
        previous_urls: tuple[str, ...] = ()

        for round_number in range(1, max_rounds + 1):
            elapsed = time.monotonic() - started_at
            if elapsed >= max_seconds:
                stopped_reason = (
                    f"{round_number - 1}. turdan sonra toplam süre bütçesi doldu (>{max_seconds} sn) -- "
                    "döngü güvenlik sınırı nedeniyle durduruldu."
                )
                break

            # Tek bir turun kendisi -- ZATEN VAR OLAN, DEĞİŞTİRİLMEMİŞ
            # Mission pipeline'ı (AI Strategy + Execution Plan + gerçek
            # dispatch + Self Check hepsi ZATEN burada çalışır).
            mission, _plan, _report = self.ceo.run_mission(request)

            current_urls = candidate_builder.evidence_urls(mission)
            round_candidates = candidate_builder.build_candidates(mission, round_number=round_number)
            all_candidates.extend(round_candidates)

            sufficient, reason = sufficiency.is_sufficient(mission.self_check)
            repeated = round_number > 1 and sufficiency.has_repeated_evidence(previous_urls, current_urls)
            if repeated and not sufficient:
                reason = f"{reason} Ayrıca: önceki turla büyük ölçüde AYNI kanıtlar bulundu -- ek tur faydasız."
                sufficient = True

            rounds.append(
                LoopRound(
                    index=round_number,
                    request=request,
                    mission=mission,
                    sufficient=sufficient,
                    reason=reason,
                    evidence_urls=current_urls,
                )
            )

            if sufficient:
                stopped_reason = f"{round_number}. turda yeterli kanıt bulundu: {reason}"
                break

            if round_number == max_rounds:
                stopped_reason = f"Maksimum tur sayısına ({max_rounds}) ulaşıldı, kanıt hâlâ eksik: {reason}"
                break

            previous_urls = current_urls
            request = sufficiency.refine_goal(goal, mission.self_check, round_number + 1)

        # Aynı adayı (aynı URL) birden çok turda tekrar RAPORLAMAMAK için
        # dedup -- yeni bir ölçüm İCAT ETMEZ, yalnızca ilk görüldüğü tur
        # tutulur.
        deduped: dict[str, ImprovementCandidate] = {}
        for candidate in all_candidates:
            key = candidate.url or f"{candidate.source}:{candidate.title}"
            deduped.setdefault(key, candidate)
        candidates = tuple(deduped.values())

        last_self_check = rounds[-1].mission.self_check if rounds else None
        last_review = last_self_check.review if last_self_check is not None else None
        expert_review_text, expert_review_reason = decide_and_run_expert_review(
            candidates, last_review, self.provider_manager, goal,
        )

        report_path = save_report(goal, tuple(rounds), candidates, stopped_reason)
        synthesis = (
            f"Hedef: {goal}\nTur sayısı: {len(rounds)}\nBulunan aday sayısı: {len(candidates)}\n"
            f"Durma nedeni: {stopped_reason}"
        )
        if candidates:
            remember = dict(topic=goal, summary=synthesis, report_path=report_path,
                            source_count=len(candidates))
            try:
                self.knowledge.remember_research(
                    **remember,
                    sources=[{"source": item.source, "title": item.title, "url": item.url} for item in candidates],
                    provenance="research_loop_evidence",
                    confidence=min(1.0, len(candidates) / 3.0),
                )
            except TypeError as error:
                if "unexpected keyword argument" not in str(error):
                    raise
                self.knowledge.remember_research(**remember)

        return ResearchLoopResult(
            goal=goal,
            rounds=tuple(rounds),
            stopped_reason=stopped_reason,
            candidates=candidates,
            expert_review_text=expert_review_text,
            expert_review_reason=expert_review_reason,
            knowledge_reused=knowledge_reused,
            knowledge_note=knowledge_note,
            report_path=report_path,
        )
