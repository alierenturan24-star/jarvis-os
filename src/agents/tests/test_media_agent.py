from __future__ import annotations

from src.agents.media_agent import MediaAgent
from src.planner.task import Task


class TestMediaAgentTopicAndDurationExtraction:
    def test_topic_extracted_from_konusunda_pattern(self):
        assert MediaAgent._extract_topic(
            "Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla."
        ) == "Bitcoin neden düştü"

    def test_no_konusunda_pattern_uses_full_text(self):
        text = "60 saniyelik bir YouTube Shorts hazırla."
        assert MediaAgent._extract_topic(text) == text

    def test_duration_extracted_from_saniyelik(self):
        assert MediaAgent._extract_duration("60 saniyelik bir video hazırla.") == 60

    def test_duration_extracted_from_saniye(self):
        assert MediaAgent._extract_duration("30 saniye sürecek bir video.") == 30

    def test_no_duration_defaults_to_60(self):
        assert MediaAgent._extract_duration("Bir video hazırla.") == 60


class TestMediaAgentExecute:
    def test_execute_passes_topic_duration_and_provider_to_manager(self, monkeypatch):
        captured = {}

        def fake_plan(self, topic, duration_seconds=60, preferred_provider=None):
            captured["topic"] = topic
            captured["duration_seconds"] = duration_seconds
            captured["preferred_provider"] = preferred_provider
            return "plan metni"

        from src.media.manager import MediaManager
        monkeypatch.setattr(MediaManager, "plan", fake_plan)

        agent = MediaAgent()
        task = Task(
            agent="media", action="dispatch",
            target="Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla.",
            metadata={"preferred_ai_provider": "ollama"},
        )

        result = agent.execute(task)

        assert result == "plan metni"
        assert captured["topic"] == "Bitcoin neden düştü"
        assert captured["duration_seconds"] == 60
        assert captured["preferred_provider"] == "ollama"
