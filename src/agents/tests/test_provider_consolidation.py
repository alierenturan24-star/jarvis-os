from src.agents.planning_agent import PlanningAgent
from src.ai.brain import Brain
from src.core.commander import Commander
from src.opportunity.manager import OpportunityManager
from src.evolution.manager import EvolutionManager
from src.council.council import AICouncil
from src.council.models import ModelProfile
from src.providers.provider_manager import RouteResult
from src.planner.task import Task


def _capture(owner):
    seen = {}
    def route(prompt, task_type, **kwargs):
        seen.update(task_type=task_type, **kwargs)
        return RouteResult("ok", "fake", "fake", "test", False, 0.0, True, ("fake",))
    owner.router.manager.route_and_generate = route
    return seen


def test_planning_agent_uses_canonical_planning_route():
    agent = PlanningAgent(); seen = _capture(agent)
    assert agent.execute(Task(agent="planning", action="plan", target="x")) == "ok"
    assert seen["task_type"] == "planning"


def test_brain_preserves_preference_through_canonical_chat_route():
    brain = Brain(); seen = _capture(brain)
    assert brain.think("x", "openai") == "ok"
    assert seen == {"task_type": "short_chat", "preferred_provider": "openai"}


def test_commander_uses_canonical_chat_route():
    commander = Commander(); seen = _capture(commander)
    commander.intent_router.detect = lambda message: "chat"
    assert commander.process("hello") == "ok"
    assert seen["task_type"] == "short_chat"


def test_opportunity_manager_uses_canonical_research_route():
    manager = OpportunityManager(); seen = _capture(manager)
    answer = manager._summarize([{"title": "x", "score": 80, "risk": 10}])
    assert answer == "ok"
    assert seen["task_type"] == "long_research"


def test_evolution_manager_uses_canonical_research_route():
    manager = EvolutionManager(); seen = _capture(manager)
    assert manager._evaluate("x", [{"title": "x", "score": 80}]) == "ok"
    assert seen["task_type"] == "long_research"


def test_ai_council_preserves_profile_preference_and_route_telemetry():
    council = AICouncil(); seen = {}
    def route(prompt, task_type, **kwargs):
        seen.update(task_type=task_type, **kwargs)
        return RouteResult("ok", "anthropic", "gemini", "fallback", True, 0.1, True,
                           ("anthropic", "gemini"))
    council.provider_manager.route_and_generate = route
    response = council._ask_model("x", ModelProfile("expert", "anthropic", "model"))
    assert response.success and response.answer == "ok"
    assert seen == {"task_type": "long_research", "preferred_provider": "anthropic", "model_name": "model"}
