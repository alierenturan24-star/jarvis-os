from __future__ import annotations

import time
import pytest
from src.control_center.finance_engine import FinancePaperEngine, MarketBar
from src.control_center.service import ControlCenterService
from src.control_center.store import ControlCenterStore
from src.core.runtime import JarvisRuntime


class FakeJarvis:
    last_mission = None


class FakeRuntime:
    BOOTING, SLEEPING, WORKING, STOPPED = "BOOTING", "SLEEPING", "WORKING", "STOPPED"
    def __init__(self):
        self.state, self.jarvis, self.completed_tasks = self.BOOTING, FakeJarvis(), 0
        self.last_error = self.last_mission_status = None; self.received = []; self.stop_requested = False
    def boot(self): self.state = self.SLEEPING
    def execute(self, goal, execution_hints=None):
        self.received.append(goal); print("[AŞAMA: RESEARCH]", flush=True); self.completed_tasks += 1; return "real result"
    def shutdown(self): self.stop_requested = True; self.state = self.STOPPED


def wait(service):
    for _ in range(100):
        if not service.busy: return
        time.sleep(.01)
    raise AssertionError("mission did not finish")


def test_command_uses_supplied_runtime_and_persists_real_result(tmp_path):
    runtime = FakeRuntime(); store = ControlCenterStore(tmp_path / "state.json")
    service = ControlCenterService(runtime, store)
    service.submit_command("piyasayı tara", "voice"); wait(service)
    assert runtime.received == ["piyasayı tara"]
    mission = store.snapshot()["missions"][-1]
    assert mission["result"] == "real result" and mission["source"] == "voice"
    assert any(x["stage"] == "RESEARCH" for x in service.snapshot()["activities"])


def test_successful_provider_only_goal_without_mission_is_not_blocked(tmp_path):
    runtime = FakeRuntime()
    service = ControlCenterService(runtime, ControlCenterStore(tmp_path / "state.json"))
    goal = (
        "Bugünün tarihini belirt ve sistemin çalıştığını doğrulamak için kısa bir durum raporu hazırla. "
        "Harici işlem yapma, dosya değiştirme ve hiçbir şey yayınlama."
    )

    service.submit_command(goal)
    wait(service)

    mission = service.store.snapshot()["missions"][-1]
    assert mission["status"] == "COMPLETED"
    assert mission["stage"] == "COMPLETED"
    assert mission["result"] == "real result"
    assert mission["domain_progress"] == {}
    assert "error" not in mission


class _RuntimeProvider:
    def __init__(self, *, available=True, response="ok"):
        self.available = available
        self.response = response
        self.calls = 0

    def is_available(self):
        return self.available

    def generate(self, prompt, model=None, system=None):
        self.calls += 1
        return self.response


def test_real_control_center_chat_path_falls_back_after_ollama_timeout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = JarvisRuntime()
    chat_agent = runtime.jarvis.agent_router.registry.get("chat")
    manager = chat_agent.router.manager
    ollama = _RuntimeProvider(response="Ollama zaman aşımına uğradı.")
    groq = _RuntimeProvider(available=False, response="çağrılmamalı")
    gemini = _RuntimeProvider(response="18 Ağustos 2026. Sistem çalışıyor.")
    aiml = _RuntimeProvider(response="çağrılmamalı")
    manager._providers = {
        "ollama": ollama,
        "groq": groq,
        "gemini": gemini,
        "aiml": aiml,
    }
    service = ControlCenterService(runtime, ControlCenterStore(tmp_path / "state.json"))
    goal = (
        "Bugünün tarihini belirt ve sistemin çalıştığını doğrulamak için kısa bir durum raporu hazırla. "
        "Harici işlem yapma, dosya değiştirme ve hiçbir şey yayınlama."
    )

    service.submit_command(goal)
    wait(service)

    record = service.store.snapshot()["missions"][-1]
    route = runtime.jarvis.last_provider_route
    provider_logs = [
        item["message"] for item in service.snapshot()["activities"]
        if item["stage"] == "PROVIDER"
    ]
    assert record["status"] == "COMPLETED"
    assert record["stage"] == "COMPLETED"
    assert runtime.context_snapshot()["local_date"] in record["result"]
    assert "18 Ağustos 2026" not in record["result"]
    assert "çeliştiği için gösterilmedi" in record["result"]
    assert "Ollama zaman aşımına uğradı." not in record["result"]
    assert record["provider_route"]["provider_used"] == "gemini"
    assert record["provider_route"]["fallback_used"] is True
    assert route.chosen_provider == "ollama"
    assert route.provider_used == "gemini"
    assert "ollama -> gemini" in route.reason
    assert ollama.calls == 1
    assert groq.calls == 0
    assert gemini.calls == 1
    assert aiml.calls == 0
    assert any("PROVIDER] OLLAMA" in line for line in provider_logs)
    assert any("PROVIDER] GEMINI (fallback)" in line for line in provider_logs)


def test_live_runtime_status_prompt_uses_real_chat_context_without_mission(tmp_path, monkeypatch):
    from src.mission.department_orchestrator import DepartmentOrchestrator
    from src.research.manager import ResearchManager

    runtime = JarvisRuntime()
    chat_agent = runtime.jarvis.agent_router.registry.get("chat")
    manager = chat_agent.router.manager
    provider = _RuntimeProvider(response="Kısa yerel durum raporu.")
    manager._providers = {"ollama": provider}

    mission_calls, research_calls, orchestrator_calls = [], [], []
    monkeypatch.setattr(
        runtime.jarvis.ceo, "run_mission",
        lambda goal: mission_calls.append(goal),
    )
    monkeypatch.setattr(
        ResearchManager, "research",
        lambda self, *args, **kwargs: research_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        DepartmentOrchestrator, "dispatch",
        lambda self, *args, **kwargs: orchestrator_calls.append((args, kwargs)),
    )
    service = ControlCenterService(runtime, ControlCenterStore(tmp_path / "state.json"))
    prompt = (
        "Bugünün gerçek tarihini ve yerel saat dilimini belirt. Ardından yalnızca "
        "doğrulanmış runtime gerçeklerini kullanarak kısa bir JARVIS sistem durum "
        "raporu ver. Runtime context içinde olmayan hiçbir subsystem hakkında aktif, "
        "sağlıklı veya çalışıyor iddiasında bulunma. Harici işlem yapma, dosya "
        "değiştirme ve hiçbir şey yayınlama."
    )

    service.submit_command(prompt)
    wait(service)

    record = service.store.snapshot()["missions"][-1]
    snapshot = runtime.context_snapshot()
    assert record["status"] == "COMPLETED"
    assert runtime.jarvis.last_mission is None
    assert mission_calls == []
    assert research_calls == []
    assert orchestrator_calls == []
    assert record["departments"] == []
    assert record["domain_progress"] == {}
    assert snapshot["local_date"] in record["result"]
    assert f"PID={snapshot['runtime_pid']}" in record["result"]
    assert "runtime_state=WORKING" in record["result"]
    assert provider.calls == 1


def test_blocked_command_persists_traceback_context(tmp_path):
    runtime = FakeRuntime()

    def fail(_goal, execution_hints=None):
        raise RuntimeError("diagnostic failure")

    runtime.execute = fail
    service = ControlCenterService(runtime, ControlCenterStore(tmp_path / "state.json"))
    service.submit_command("test goal")
    wait(service)

    mission = service.store.snapshot()["missions"][-1]
    assert mission["status"] == "BLOCKED"
    assert mission["error"] == "diagnostic failure"
    assert "Traceback (most recent call last)" in mission["error_context"]
    assert "RuntimeError: diagnostic failure" in mission["error_context"]


def test_pause_blocks_new_work_and_emergency_stop_stops_runtime(tmp_path):
    runtime = FakeRuntime(); service = ControlCenterService(runtime, ControlCenterStore(tmp_path / "state.json"))
    service.pause()
    with pytest.raises(RuntimeError): service.submit_command("goal")
    service.stop(emergency=True); assert runtime.state == runtime.STOPPED


def test_approval_reject_is_persisted_and_never_executes_action(tmp_path):
    service = ControlCenterService(FakeRuntime(), ControlCenterStore(tmp_path / "state.json"))
    item = service.create_approval("finance_real_trade", {"need": "BTC order", "why": "signal"})
    assert service.decide_approval(item["id"], False)["status"] == "REJECTED"
    assert service.store.snapshot()["approvals"][-1]["status"] == "REJECTED"


def test_backtest_is_evidence_labelled_and_charges_fees(tmp_path):
    bars = []
    for i in range(240):
        close = 100 + (i % 60 if (i // 60) % 2 == 0 else 60 - i % 60)
        bars.append(MarketBar(i, close, close + 1, close - 1, close, 1000))
    result = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json")).backtest("BTC", bars)
    assert result["label"] == "BACKTEST — NOT LIVE"
    assert result["fees_rate"] > 0 and result["slippage_rate"] > 0
    assert result["out_of_sample_bars"] > 0 and result["qualified"] is False


def test_live_trade_has_no_execution_and_always_creates_pending_approval(tmp_path):
    approval = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json")).request_live_trade({"asset": "BTCUSDT", "max_planned_loss": 10})
    assert approval["status"] == "PENDING" and approval["type"] == "finance_real_trade"


def test_bare_asset_is_normalized_to_quote_pair():
    from src.control_center.finance_engine import BinancePublicMarketData
    assert BinancePublicMarketData._symbol("BTC") == "BTCUSDT"
    assert BinancePublicMarketData._symbol("ETHBTC") == "ETHBTC"


def test_qualification_fails_closed_without_enough_evidence(tmp_path):
    engine = FinancePaperEngine(ControlCenterStore(tmp_path / "state.json"))
    result = engine.qualification()
    assert result["qualified"] is False and result["live_activation"] is False


class FakeMarket:
    def price(self, asset):
        return {"symbol": "BTCUSDT", "price": 100.0, "change_percent_24h": 1.0, "source": "official fake"}
    def ohlcv(self, asset, interval="1h", limit=500):
        return [MarketBar(i, 90+i*.2, 91+i*.2, 89+i*.2, 90+i*.2, 1000) for i in range(max(100, limit))]
    _symbol = staticmethod(lambda asset: "BTCUSDT" if asset in {"BTC", "BTCUSDT"} else asset)


def test_paper_lifecycle_marks_excursions_closes_target_and_updates_performance(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json")
    engine = FinancePaperEngine(store, FakeMarket())
    position = engine.paper_signal("BTC")
    assert position["status"] == "OPEN"
    first = engine.mark_to_market({"BTC": position["entry"] * 1.01})
    assert first["positions"][0]["unrealized_pnl"] > 0
    closed = engine.mark_to_market({"BTC": position["target"] * 1.01})
    assert closed["closed"][-1]["reason"] == "TARGET"
    assert closed["performance"]["trade_count"] == 1
    assert store.snapshot()["paper"]["positions"] == []


def test_stop_close_persists_full_trade_record(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json"); engine = FinancePaperEngine(store, FakeMarket())
    position = engine.paper_signal("BTC")
    trade = engine.mark_to_market({"BTC": position["stop"] * .99})["closed"][-1]
    for key in ("asset", "direction", "entry", "entry_timestamp", "position_size", "stop", "target", "fees",
                "slippage", "exit", "pnl", "pnl_percent", "reason", "strategy", "market_regime", "confidence",
                "max_adverse_excursion", "max_favorable_excursion"):
        assert key in trade
    assert trade["reason"] == "STOP" and trade["pnl"] < 0


def test_performance_keeps_backtest_oos_and_paper_separate(tmp_path):
    store = ControlCenterStore(tmp_path / "state.json"); engine = FinancePaperEngine(store, FakeMarket())
    engine.backtest("BTC", FakeMarket().ohlcv("BTC", limit=240))
    result = engine.performance()
    assert set(("paper", "backtest", "out_of_sample", "strategy_regime")) <= result.keys()
