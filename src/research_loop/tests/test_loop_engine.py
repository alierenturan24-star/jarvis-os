from __future__ import annotations

from src.jobs.task import Task
from src.mission.models import Mission
from src.research_loop import loop_engine as loop_engine_module
from src.research_loop.loop_engine import ResearchLoopEngine
from src.strategy.execution_planner import SelfCheckReport
from src.strategy.models import SelfImprovementReview


def _self_check(success_rate=100.0, needs_reresearch=()) -> SelfCheckReport:
    return SelfCheckReport(
        success_rate=success_rate, missing_info=(), needs_reresearch=tuple(needs_reresearch),
        was_cached_research=False, cache_note="test",
        review=SelfImprovementReview(
            cheaper_ai_possible=False, cheaper_ai_note="n", faster_ai_possible=False, faster_ai_note="n",
            quality_risk=False, quality_risk_note="n", new_free_model_available=False, new_free_model_note="n",
        ),
    )


def _mission(self_check: SelfCheckReport, ai_discovery_top=None) -> Mission:
    mission = Mission(title="hedef")
    mission.self_check = self_check
    tasks = []
    if ai_discovery_top is not None:
        tasks.append(Task(
            title="[ai_discovery]", agent="ai_discovery", target="hedef",
            metadata={"report": {"top": ai_discovery_top}},
        ))
    mission.tasks = tasks
    return mission


class _FakeCEO:
    """Sprint 37: gerçek (ağ/LLM bağımlı) Mission dispatch'ini
    ÇALIŞTIRMADAN ``ResearchLoopEngine``'in tur/durma mantığını
    deterministik test etmek için -- yalnızca ``run_mission``
    sözleşmesini (ördek tipleme) taklit eder."""

    def __init__(self, missions: list[Mission]) -> None:
        self._missions = missions
        self.calls: list[str] = []

    def run_mission(self, request: str):
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self._missions) - 1)
        return self._missions[index], None, {}


class _FakeKnowledge:
    def __init__(self) -> None:
        self.remembered = None

    def find_research(self, topic: str):
        return None

    def remember_research(self, topic, summary, report_path, source_count):
        self.remembered = (topic, summary, report_path, source_count)


class _FakeProvider:
    def is_available(self) -> bool:
        return False


class _FakeProviderManager:
    def get(self, name: str):
        return _FakeProvider()

    def generate(self, prompt: str, provider_name: str) -> str:
        raise AssertionError("Claude kullanılamıyorken generate() çağrılmamalı.")


def _engine(missions: list[Mission], monkeypatch) -> tuple[ResearchLoopEngine, _FakeCEO]:
    monkeypatch.setattr(loop_engine_module, "save_report", lambda *a, **k: "workspace/research_loop/fake.md")
    ceo = _FakeCEO(missions)
    engine = ResearchLoopEngine(ceo, knowledge=_FakeKnowledge(), provider_manager=_FakeProviderManager())
    return engine, ceo


class TestStopsWhenSufficient:
    def test_single_sufficient_round_stops_immediately(self, monkeypatch):
        engine, ceo = _engine([_mission(_self_check())], monkeypatch)
        result = engine.run("hedef", max_rounds=3)
        assert len(result.rounds) == 1
        assert len(ceo.calls) == 1
        assert result.rounds[0].sufficient is True
        assert "yeterli kanıt bulundu" in result.stopped_reason


class TestContinuesWhenInsufficient:
    def test_second_round_runs_with_a_refined_request(self, monkeypatch):
        missions = [
            _mission(_self_check(needs_reresearch=["x/y: Sandbox FAIL"])),
            _mission(_self_check()),
        ]
        engine, ceo = _engine(missions, monkeypatch)
        result = engine.run("hedef", max_rounds=3)

        assert len(result.rounds) == 2
        assert ceo.calls[0] == "hedef"
        assert ceo.calls[1] != "hedef"
        assert "x/y" in ceo.calls[1]
        assert result.rounds[1].sufficient is True


class TestMaxRoundsIsAHardCap:
    def test_never_exceeds_max_rounds_even_if_always_insufficient(self, monkeypatch):
        missions = [_mission(_self_check(needs_reresearch=["still missing"]))]
        engine, ceo = _engine(missions, monkeypatch)
        result = engine.run("hedef", max_rounds=3)

        assert len(result.rounds) == 3
        assert len(ceo.calls) == 3
        assert "Maksimum tur sayısına" in result.stopped_reason

    def test_wall_clock_guard_stops_before_any_round_when_budget_is_zero(self, monkeypatch):
        missions = [_mission(_self_check(needs_reresearch=["x"]))]
        engine, ceo = _engine(missions, monkeypatch)
        result = engine.run("hedef", max_rounds=3, max_seconds=0)

        assert len(ceo.calls) == 0
        assert len(result.rounds) == 0
        assert "süre bütçesi doldu" in result.stopped_reason


class TestRepeatedEvidenceStopsEarly:
    def test_identical_evidence_across_rounds_stops_even_if_self_check_says_insufficient(self, monkeypatch):
        same_top = [{"url": "https://a.com", "title": "A", "summary": "s", "query": "q",
                      "score": 50, "goal_fit": 50, "safety": 50, "implementation_ease": 50,
                      "cost_advantage": 50, "expected_value": 50}]
        missions = [
            _mission(_self_check(needs_reresearch=["still missing"]), ai_discovery_top=same_top),
            _mission(_self_check(needs_reresearch=["still missing"]), ai_discovery_top=same_top),
            _mission(_self_check(needs_reresearch=["still missing"]), ai_discovery_top=same_top),
        ]
        engine, ceo = _engine(missions, monkeypatch)
        result = engine.run("hedef", max_rounds=3)

        assert len(ceo.calls) == 2  # 3. tur hiç çalışmadı -- tekrar tespit edilince durdu.
        assert "AYNI kanıtlar" in result.stopped_reason


class TestCandidateAggregation:
    def test_candidates_from_all_rounds_are_collected_and_deduped_by_url(self, monkeypatch):
        top_round1 = [{"url": "https://a.com", "title": "A", "summary": "s", "query": "q",
                        "score": 50, "goal_fit": 50, "safety": 50, "implementation_ease": 50,
                        "cost_advantage": 50, "expected_value": 50}]
        top_round2 = [
            {"url": "https://a.com", "title": "A", "summary": "s", "query": "q",  # aynı URL -- dedup
             "score": 50, "goal_fit": 50, "safety": 50, "implementation_ease": 50,
             "cost_advantage": 50, "expected_value": 50},
            {"url": "https://b.com", "title": "B", "summary": "s", "query": "q",
             "score": 60, "goal_fit": 60, "safety": 60, "implementation_ease": 60,
             "cost_advantage": 60, "expected_value": 60},
        ]
        missions = [
            _mission(_self_check(needs_reresearch=["x"]), ai_discovery_top=top_round1),
            _mission(_self_check(), ai_discovery_top=top_round2),
        ]
        engine, ceo = _engine(missions, monkeypatch)
        result = engine.run("hedef", max_rounds=3)

        assert {c.url for c in result.candidates} == {"https://a.com", "https://b.com"}


class TestKnowledgeReuse:
    def test_result_without_evidence_is_not_saved_to_knowledge_base(self, monkeypatch):
        engine, ceo = _engine([_mission(_self_check())], monkeypatch)
        knowledge = engine.knowledge
        engine.run("hedef", max_rounds=1)
        assert knowledge.remembered is None
