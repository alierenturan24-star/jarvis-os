from __future__ import annotations

from pathlib import Path

from src.mission.models import Mission
from src.research_loop.models import ImprovementCandidate, LoopRound, ResearchLoopResult
from src.research_loop.report_builder import format_report, save


def _mission(title="hedef") -> Mission:
    return Mission(title=title)


def _round(index=1, sufficient=True) -> LoopRound:
    return LoopRound(
        index=index, request=f"hedef tur {index}", mission=_mission(), sufficient=sufficient,
        reason="test gerekçe", evidence_urls=("https://x.com",),
    )


def _candidate() -> ImprovementCandidate:
    return ImprovementCandidate(
        goal="hedef", source="ai_discovery", title="Aday", url="https://x.com",
        finding="bulgu", gain_note="kazanç", risk_note="risk", recommendation="öneri",
        score=80, cost_advantage=90, round_number=1,
    )


class TestSave:
    def test_writes_a_markdown_file_under_workspace_research_loop(self, tmp_path, monkeypatch):
        import src.research_loop.report_builder as report_builder_module
        monkeypatch.setattr(report_builder_module, "WORKSPACE_DIR", tmp_path / "research_loop")

        path = save("test hedefi", (_round(),), (_candidate(),), "yeterli kanıt bulundu")

        written = Path(path)
        assert written.exists()
        content = written.read_text(encoding="utf-8")
        assert "test hedefi" in content
        assert "Aday" in content
        assert "yeterli kanıt bulundu" in content

    def test_no_candidates_still_writes_file_without_crashing(self, tmp_path, monkeypatch):
        import src.research_loop.report_builder as report_builder_module
        monkeypatch.setattr(report_builder_module, "WORKSPACE_DIR", tmp_path / "research_loop")

        path = save("hedef", (_round(),), (), "durduruldu")
        assert Path(path).exists()
        assert "hiçbir aday üretilmedi" in Path(path).read_text(encoding="utf-8")


class TestFormatReport:
    def test_includes_round_headers_and_candidate_table(self):
        result = ResearchLoopResult(
            goal="hedef", rounds=(_round(1), _round(2, sufficient=True)),
            stopped_reason="2. turda yeterli kanıt bulundu", candidates=(_candidate(),),
            expert_review_text=None, expert_review_reason="Claude gerekmedi",
            knowledge_reused=False, knowledge_note="daha önce araştırılmamış",
            report_path="workspace/research_loop/x.md",
        )
        text = format_report(result)
        assert "TUR 1/2" in text
        assert "TUR 2/2" in text
        assert "IMPROVEMENT CANDIDATES" in text
        assert "Aday" in text
        assert "EXPERT REVIEW" in text
        assert "Claude kullanılmadı" in text
        assert "workspace/research_loop/x.md" in text

    def test_expert_review_text_is_included_when_present(self):
        result = ResearchLoopResult(
            goal="hedef", rounds=(_round(),), stopped_reason="test",
            candidates=(_candidate(),), expert_review_text="X daha uygun çünkü Y.",
            expert_review_reason="kalite riski var", knowledge_reused=False,
            knowledge_note="n", report_path=None,
        )
        text = format_report(result)
        assert "X daha uygun çünkü Y." in text

    def test_no_candidates_section_says_so(self):
        result = ResearchLoopResult(
            goal="hedef", rounds=(_round(),), stopped_reason="test", candidates=(),
            expert_review_text=None, expert_review_reason="aday yok", knowledge_reused=False,
            knowledge_note="n", report_path=None,
        )
        text = format_report(result)
        assert "hiçbir aday üretilmedi" in text
