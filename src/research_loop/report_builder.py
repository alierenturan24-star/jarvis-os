from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.mission.report_builder import build_ceo_report
from src.research_loop.models import ImprovementCandidate, LoopRound

if TYPE_CHECKING:
    from src.research_loop.models import ResearchLoopResult

# Sprint 37: ZATEN VAR OLAN ``src.research.report_builder``/
# ``src.evolution.report_builder`` deseniyle AYNI -- yalnızca
# ``workspace/`` altına bir markdown dosyası YAZAR, ana projeye hiçbir
# şey KOPYALAMAZ/ENTEGRE ETMEZ.
WORKSPACE_DIR = Path("workspace") / "research_loop"


def _slug(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", (text or "").lower()).strip()
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug[:60] or "hedef"


def save(
    goal: str,
    rounds: tuple[LoopRound, ...],
    candidates: tuple[ImprovementCandidate, ...],
    stopped_reason: str,
) -> str:
    """Bir araştırma döngüsünün tam raporunu diske yazar, dosya yolunu
    döndürür. Her turun bölümü ZATEN VAR OLAN ``build_ceo_report`` ile
    üretilir -- yeni bir rapor motoru İCAT EDİLMEZ."""

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = WORKSPACE_DIR / f"{_slug(goal)}_{timestamp}.md"

    lines = [f"# Araştırma Döngüsü: {goal}", "", f"Durma nedeni: {stopped_reason}", ""]
    for round_ in rounds:
        lines.append(f"## Tur {round_.index}")
        lines.append(f"İstek: {round_.request}")
        lines.append(f"Yeterli mi: {'evet' if round_.sufficient else 'hayır'} -- {round_.reason}")
        lines.append("")
        lines.append(build_ceo_report(round_.mission))
        lines.append("")

    lines.append("## Improvement Candidates")
    if candidates:
        for candidate in candidates:
            lines.append(
                f"- [{candidate.source}] {candidate.title} ({candidate.url}) -- "
                f"skor {candidate.score}/100, maliyet avantajı {candidate.cost_advantage}/100"
            )
            lines.append(f"  Bulgu: {candidate.finding}")
            lines.append(f"  Kazanç: {candidate.gain_note}")
            lines.append(f"  Risk: {candidate.risk_note}")
            lines.append(f"  Öneri: {candidate.recommendation}")
    else:
        lines.append("(hiçbir aday üretilmedi)")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def format_report(result: "ResearchLoopResult") -> str:
    """``ResearchLoopResult``'ı CEO'ya gösterime hazır bir metne çevirir.
    Her turun raporu ZATEN VAR OLAN ``build_ceo_report(mission)`` ile
    üretilir, yeniden YAZILMAZ -- yalnızca tur başlıkları + döngü özeti +
    ImprovementCandidate tablosu + Expert Review bölümü EKLENİR."""

    lines = [
        "AUTONOMOUS RESEARCH LOOP",
        f"Hedef: {result.goal}",
        f"Tur sayısı: {len(result.rounds)}",
        f"Durma nedeni: {result.stopped_reason}",
        f"Knowledge reuse: {result.knowledge_note}",
        "",
    ]

    for round_ in result.rounds:
        lines.append("=" * 32)
        lines.append(f"TUR {round_.index}/{len(result.rounds)} -- istek: {round_.request}")
        lines.append(f"Yeterli mi: {'evet' if round_.sufficient else 'hayır'} -- {round_.reason}")
        lines.append("=" * 32)
        lines.append(build_ceo_report(round_.mission))
        lines.append("")

    lines.append("=" * 32)
    lines.append("IMPROVEMENT CANDIDATES")
    if result.candidates:
        for candidate in result.candidates:
            lines.append(
                f"- [{candidate.source}] {candidate.title} ({candidate.url}) -- "
                f"skor {candidate.score}/100, maliyet avantajı {candidate.cost_advantage}/100 "
                f"(tur {candidate.round_number})"
            )
            lines.append(f"    Bulgu: {candidate.finding}")
            lines.append(f"    Kazanç: {candidate.gain_note}")
            lines.append(f"    Risk: {candidate.risk_note}")
            lines.append(f"    Öneri: {candidate.recommendation}")
    else:
        lines.append("(hiçbir aday üretilmedi)")

    lines.append("")
    lines.append("=" * 32)
    lines.append("EXPERT REVIEW (Claude)")
    lines.append(f"Gerekçe: {result.expert_review_reason}")
    if result.expert_review_text:
        lines.append("")
        lines.append(result.expert_review_text)
    else:
        lines.append("Claude kullanılmadı (yukarıdaki gerekçeye bkz.).")

    lines.append("")
    lines.append(f"Rapor dosyası: {result.report_path or '-'}")

    return "\n".join(lines)
