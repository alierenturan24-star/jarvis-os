from pathlib import Path
from types import SimpleNamespace

from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.completion import domain_completion, evaluate_goal_completion
from src.mission.mission_engine import MissionEngine
from src.strategy.execution_planner import build_self_check


GOAL = (
    "YouTube tarafında yeni içerik fırsatlarını araştır, geçmiş üretim ve learning hafızanı "
    "kullanarak yeni videolar planla ve üret. Finance tarafında gerçek public market data "
    "kullanarak PAPER araştırma ve learning döngüsünü çalıştır, yeni strateji adayları keşfet, "
    "backtest ve OOS ile doğrula. Qualified olmayan stratejilerde işlem açma. Gerçek para "
    "kullanma ve hiçbir videoyu yayınlama."
)


def _done(agent, metadata):
    task = Task(title=agent, agent=agent, handler=lambda _: "ok", metadata=metadata)
    task.status = TaskStatus.COMPLETED
    task.result = SimpleNamespace(output="ok")
    return task


def _finance_report():
    metric = {"trade_count": 4, "net_return_after_costs": -.01, "max_drawdown": .04,
              "win_rate": .25, "profit_factor": .8, "expectancy": -.002, "sharpe": -.2}
    candidates = [{"name": family, "family": family, "source": "bounded exploration",
                   "discovered_at": "now", "baseline_or_new": "new", "logic_summary": family,
                   "parameters": {}, "assets_tested": ["BTCUSDT"], "regimes_tested": ["mixed"],
                   **metric, "train_metrics": metric, "out_of_sample_metrics": metric,
                   "qualified": False, "qualification_reasons": ["OOS below threshold"]}
                  for family in ("trend", "momentum")]
    return {"strategy_lab": {"strategy_count": 2, "candidates": candidates,
            "decision": "NO QUALIFIED STRATEGY", "paper_promoted": False,
            "source": "Binance official OHLCV", "market_truth_source": True}}


def _youtube_record(path):
    return {"creative": {"story_concept": "new story", "script": "script", "scene_count": 4,
            "story_beats": ["hook", "setup", "action", "ending"]},
            "artifact": {"final_video_path": str(path), "thumbnail_path": str(path.with_suffix('.png')),
                         "technical_validation": True, "semantic_validation": True,
                         "production_provenance": "generative_image_story_pipeline"},
            "visual": {"body_motion": True, "body_motion_ratio": 2.2},
            "audio": {"silence_detected": False, "peak_db": -9.0},
            "quality": {"production_readiness": True}, "thumbnail": {}}


def _mission(tmp_path, monkeypatch, youtube=True, finance=True):
    monkeypatch.setattr("src.media.quality.validate_media_goal_artifact",
                        lambda path, goal="": SimpleNamespace(passed=True))
    mission = MissionEngine().create_mission(GOAL)
    tasks = []
    if youtube:
        video = tmp_path / "new.mp4"; video.write_bytes(b"real-video")
        video.with_suffix(".png").write_bytes(b"thumbnail")
        tasks.append(_done("media", {"artifact_path": str(video),
                     "youtube_production": _youtube_record(video), "learning_persisted": True}))
    if finance:
        tasks.extend((_done("finance", {"report": _finance_report()}),
                      _done("learning", {"report": {"learning_persisted": True}})))
    mission.tasks = tasks
    return mission


def test_same_message_preserves_both_subgoals():
    mission = MissionEngine().create_mission(GOAL)
    assert {"media", "finance", "learning"} <= set(mission.departments)
    assert {r.domain for r in mission.completion_requirements} >= {"youtube", "finance"}


def test_real_youtube_pipeline_is_selected_and_history_cues_survive():
    mission = MissionEngine().create_mission(GOAL)
    media = next(t for t in MissionEngine().orchestrator.create_tasks(mission) if t.agent == "media")
    assert "geçmiş üretim" in media.target and "learning hafızanı" in media.target


def test_finance_complete_youtube_missing_is_not_complete(tmp_path, monkeypatch):
    assert not evaluate_goal_completion(_mission(tmp_path, monkeypatch, youtube=False)).satisfied


def test_youtube_complete_finance_missing_is_not_complete(tmp_path, monkeypatch):
    assert not evaluate_goal_completion(_mission(tmp_path, monkeypatch, finance=False)).satisfied


def test_both_complete_is_complete(tmp_path, monkeypatch):
    assert evaluate_goal_completion(_mission(tmp_path, monkeypatch)).satisfied


def test_plan_only_media_cannot_complete_youtube_production():
    mission = MissionEngine().create_mission(GOAL)
    mission.tasks = [_done("media", {"report": {"plan": "only"}})]
    assert not evaluate_goal_completion(mission).satisfied


def test_recovery_scope_exposes_only_incomplete_domain(tmp_path, monkeypatch):
    state = domain_completion(_mission(tmp_path, monkeypatch, youtube=False))
    assert state["finance"]["status"] == "COMPLETE"
    assert state["youtube"]["status"] == "INCOMPLETE"


def test_publish_and_real_money_remain_disabled(tmp_path, monkeypatch):
    state = domain_completion(_mission(tmp_path, monkeypatch))
    assert state["youtube"]["evidence"]["publish_not_used"] == "PRESENT"
    assert state["finance"]["evidence"]["real_money_not_used"] == "PRESENT"


def test_self_check_cannot_be_100_with_missing_youtube(tmp_path, monkeypatch):
    check = build_self_check(_mission(tmp_path, monkeypatch, youtube=False), None)
    assert check.success_rate < 100 and "MISSING" in check.artifact_statuses

