from __future__ import annotations

from typing import Optional

from src.strategy.execution_planner import SelfCheckReport

# Sprint 37: "GEREKİRSE YENİDEN ARAŞTIR / YETERLİ KANIT VARSA DUR" döngüsünün
# durma kararı. Yeni bir ölçüm İCAT ETMEZ -- yalnızca Sprint 36'nın ZATEN
# hesapladığı ``SelfCheckReport`` alanlarını (``needs_reresearch``,
# ``success_rate``) okur. Eşik değeri (``MIN_SUCCESS_RATE``) bu sprintte
# YENİ eklenen tek "karar" -- her yerde olduğu gibi dürüstçe, sabit ve
# test edilebilir tutulur.
MIN_SUCCESS_RATE = 60.0

# Sprint 37: "aynı gereksiz araştırmayı tekrarladı mı?" (canlı kabul testi
# soru listesi) -- iki tur arasında bulunan kanıt URL kümesi büyük ölçüde
# ÇAKIŞIYORSA (yeni arama gerçek bir yeni sonuç GETİRMEDİYSE) ek tur
# faydasızdır, döngü erken durur.
REPEATED_EVIDENCE_OVERLAP_THRESHOLD = 0.9


def is_sufficient(self_check: Optional[SelfCheckReport], min_success_rate: float = MIN_SUCCESS_RATE) -> tuple[bool, str]:
    """Bu tur "yeterli kanıt" mi ürettü, yoksa yeni bir tur mu gerekli?

    Yalnızca Sprint 36'nın ZATEN hesapladığı ``SelfCheckReport``'a dayanır
    -- yeni bir kanıt/kalite ölçümü İCAT ETMEZ.
    """

    if self_check is None:
        return False, "Self-check üretilemedi (veri yok) -- yeterlilik değerlendirilemedi, ek tur denenecek."

    if self_check.needs_reresearch:
        items = "; ".join(self_check.needs_reresearch)
        return False, f"Tekrar araştırılması gereken {len(self_check.needs_reresearch)} bulgu var: {items}"

    if self_check.success_rate < min_success_rate:
        return (
            False,
            f"Başarı oranı %{self_check.success_rate:.0f}, eşik %{min_success_rate:.0f}'in altında.",
        )

    return (
        True,
        f"Tekrar araştırılması gereken bulgu yok, başarı oranı %{self_check.success_rate:.0f} "
        f"(eşik %{min_success_rate:.0f}) -- kanıt yeterli kabul edildi.",
    )


def refine_goal(original_goal: str, self_check: Optional[SelfCheckReport], round_number: int) -> str:
    """Bir sonraki tur için, önceki turun eksiklerine dayanan DÜRÜST bir
    istek metni üretir -- aynı isteği kelimesi kelimesine tekrarlamak
    yerine (aynı sonuçları getirme riski), eksik kalan noktaları AÇIKÇA
    belirtir. Yeni bir arama/sorgu motoru İCAT ETMEZ -- mevcut pipeline'a
    (``CEO.create_mission``) girecek metni zenginleştirir."""

    if self_check is None:
        return (
            f"{original_goal} (Not: {round_number}. tur -- önceki turun değerlendirmesi "
            "üretilemedi, farklı/alternatif kaynaklarla tekrar araştır.)"
        )

    hints = list(self_check.needs_reresearch) + list(self_check.missing_info)
    if not hints:
        return original_goal

    hint_text = "; ".join(hints[:3])
    return (
        f"{original_goal} (Not: {round_number}. tur -- önceki turda şunlar yeterli bulunmadı: "
        f"{hint_text}. Alternatif/farklı kaynakları araştır.)"
    )


def has_repeated_evidence(
    previous_urls: tuple[str, ...],
    current_urls: tuple[str, ...],
    threshold: float = REPEATED_EVIDENCE_OVERLAP_THRESHOLD,
) -> bool:
    """İki ardışık turun kanıt URL kümesi büyük ölçüde AYNIYSA ``True`` --
    yeni arama gerçekten yeni bir sonuç getirmedi demektir."""

    previous = {url for url in previous_urls if url}
    current = {url for url in current_urls if url}
    if not previous or not current:
        return False

    overlap = len(previous & current)
    ratio = overlap / len(current)
    return ratio >= threshold
