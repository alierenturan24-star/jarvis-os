from __future__ import annotations

from src.agents.automation_agent import AutomationAgent
from src.automation.manager import AutomationManager
from src.planner.task import Task


class TestAutomationAgentExecute:
    def test_execute_passes_topic_to_manager(self, monkeypatch):
        captured = {}

        def fake_plan(self, topic):
            captured["topic"] = topic
            return "checklist metni"

        monkeypatch.setattr(AutomationManager, "plan", fake_plan)

        agent = AutomationAgent()
        task = Task(agent="automation", action="dispatch", target="YouTube otomasyonu kur.")

        result = agent.execute(task)

        assert result == "checklist metni"
        assert captured["topic"] == "YouTube otomasyonu kur."
