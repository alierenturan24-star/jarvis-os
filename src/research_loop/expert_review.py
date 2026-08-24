from __future__ import annotations

from typing import Optional

from src.providers.provider_manager import ProviderManager
from src.research_loop.models import ImprovementCandidate
from src.strategy.models import SelfImprovementReview

# Sprint 37, bölüm 5: "Claude da JARVIS'in çalışanı olsun" -- Claude ayrı
# bir patron DEĞİL, JARVIS/Strategy'nin "bu adım Claude gerektiriyor mu?"
# kararına bağlı, DAR/NET görevli bir işçi. Bu modül:
#   1) Claude'a GEREK olup olmadığına ZATEN hesaplanmış sinyallerle karar
#      verir (yeni bir puanlama İCAT ETMEZ -- Sprint 35'in
#      ``SelfImprovementReview.quality_risk``'i + adaylar arasında net bir
#      ücretsiz kazananın olup olmadığı).
#   2) Gerekliyse ``ProviderManager`` üzerinden GERÇEK, DAR bir istek
#      gönderir (tüm araştırma geçmişi DEĞİL -- yalnızca en iyi 3 aday).
#   3) Sağlayıcı gerçekten YOKSA (API anahtarı tanımlı değil) bunu
#      AÇIKÇA raporlar -- sahte/simüle bir "Claude cevabı" ÜRETMEZ.
MIN_CANDIDATES_FOR_COMPARATIVE_REVIEW = 3
CLEAR_FREE_WINNER_SCORE_GAP = 15


def _needs_expert_review(candidates: tuple[ImprovementCandidate, ...], review: Optional[SelfImprovementReview]) -> tuple[bool, str]:
    if review is not None and review.quality_risk:
        return True, f"AI Strategy self-improvement review kalite riski işaretledi: {review.quality_risk_note}"

    if len(candidates) >= MIN_CANDIDATES_FOR_COMPARATIVE_REVIEW:
        scores = sorted((c.score for c in candidates), reverse=True)
        gap = scores[0] - scores[1] if len(scores) >= 2 else 999
        if gap < CLEAR_FREE_WINNER_SCORE_GAP:
            return (
                True,
                f"{len(candidates)} aday arasında net bir kazanan yok (en iyi iki skor farkı {gap} puan) "
                "-- mimari/karşılaştırmalı bir uzman değerlendirmesi faydalı olabilir.",
            )

    return False, "Ücretsiz/mevcut katmandaki değerlendirme (EvolutionScorer/EvaluationEngine) yeterli kabul edildi, Claude gerekmedi."


def _build_prompt(goal: str, candidates: tuple[ImprovementCandidate, ...]) -> str:
    top = candidates[:3]
    blocks = []
    for index, candidate in enumerate(top, start=1):
        blocks.append(
            f"Aday {index}: {candidate.title}\n"
            f"  Kaynak: {candidate.source} ({candidate.url})\n"
            f"  Bulgu: {candidate.finding}\n"
            f"  Skor: {candidate.score}/100, Maliyet avantajı: {candidate.cost_advantage}/100\n"
            f"  Risk notu: {candidate.risk_note}"
        )
    return (
        f"Hedef: {goal}\n\n"
        f"Bu {len(top)} adayın mimari/uygunluk farklarını DEĞERLENDİR. Yalnızca aşağıdaki bilgilere dayan, "
        "kısa ve somut yaz (en fazla 150 kelime). Hangisi hedefe daha uygun ve neden? "
        "Hiçbir öneri otomatik uygulanmayacak, yalnızca bir öneri metni üretiyorsun.\n\n"
        + "\n\n".join(blocks)
    )


def decide_and_run_expert_review(
    candidates: tuple[ImprovementCandidate, ...],
    review: Optional[SelfImprovementReview],
    provider_manager: ProviderManager,
    goal: str,
) -> tuple[Optional[str], str]:
    """Claude'a gerçekten ihtiyaç var mı? Varsa GERÇEK, dar bir istekle
    çağırır; yoksa veya sağlayıcı kullanılamıyorsa ``None`` + dürüst bir
    gerekçe döner. Asla sahte bir "Claude cevabı" ÜRETMEZ."""

    if not candidates:
        return None, "Hiçbir aday üretilmedi, değerlendirilecek bir şey yok."

    needed, reason = _needs_expert_review(candidates, review)
    if not needed:
        return None, reason

    provider = provider_manager.get("anthropic")
    if provider is None or not provider.is_available():
        return None, (
            f"{reason} Ancak Claude (Anthropic) şu an KULLANILAMIYOR "
            "(ANTHROPIC_API_KEY tanımlı değil veya sağlayıcı kayıtlı değil) -- "
            "sahte bir entegrasyon YAZILMADI, bu eksiklik açıkça raporlanıyor."
        )

    prompt = _build_prompt(goal, candidates)
    route = provider_manager.route_and_generate(
        prompt, task_type="long_research", preferred_provider="anthropic",
    )
    answer = route.output
    return answer, f"{reason} Claude (Anthropic) kullanılabilir durumdaydı, dar kapsamlı bir istekle çağrıldı."
