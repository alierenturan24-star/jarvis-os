from __future__ import annotations

from src.providers.provider_manager import ProviderManager

GOAL_PROMPT = (
    "Sen JARVIS Coding Agent'sın...\nGörev: Inspect the python file "
    "src/media/quality.py (read-only) and explain to JARVIS what it does "
    "and which quality gates it enforces. Do not modify any file.\n"
)


class _RecordingProvider:
    """Like the shared ``_FakeProvider`` (test_provider_manager_routing.py)
    but also records every prompt it actually received -- needed to prove
    fallback candidates get the IDENTICAL concrete task, not a generic one."""

    def __init__(self, available: bool = True, response: str | None = None) -> None:
        self._available = available
        self._response = response if response is not None else (
            "ok" if available else "sağlayıcı hatası: boom"
        )
        self.calls = 0
        self.received_prompts: list[str] = []

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, model: str | None = None) -> str:
        self.calls += 1
        self.received_prompts.append(prompt)
        return self._response


class TestG_SuccessfulClaudeCodeIsReturnedWithoutUnnecessaryFallback:
    def test_claude_code_success_on_first_try_skips_codex_entirely(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        claude_code = _RecordingProvider(response="Gerçek quality.py incelemesi.")
        codex = _RecordingProvider(response="çağrılmamalı")
        manager._providers = {"claude_code": claude_code, "codex": codex}

        result = manager.route_and_generate(
            GOAL_PROMPT, task_type="coding", preferred_provider="claude_code",
        )

        assert result.success is True
        assert result.provider_used == "claude_code"
        assert result.fallback_used is False
        assert result.output == "Gerçek quality.py incelemesi."
        assert claude_code.calls == 1
        assert codex.calls == 0


class TestH_ClaudeCodeFailureStillUsesExistingFallbackChain:
    def test_claude_code_timeout_style_failure_falls_back_to_codex(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        claude_code = _RecordingProvider(
            response="claude_code sağlayıcı hatası: Claude Code zaman aşımına uğradı (180 sn).",
        )
        codex = _RecordingProvider(response="Codex'in gerçek cevabı.")
        manager._providers = {"claude_code": claude_code, "codex": codex}

        result = manager.route_and_generate(
            GOAL_PROMPT, task_type="coding", preferred_provider="claude_code",
        )

        assert result.fallback_used is True
        assert result.provider_used == "codex"
        assert result.output == "Codex'in gerçek cevabı."
        assert claude_code.calls == 1
        assert codex.calls == 1


class TestI_FallbackProviderReceivesTheOriginalConcreteTaskNotGeneric:
    """Requirement 9.I: whatever provider ends up running (including a
    fallback), it must receive the EXACT same prompt as the first attempt
    -- ProviderManager must never substitute a generic prompt on retry."""

    def test_codex_fallback_receives_byte_identical_prompt_to_claude_code_attempt(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        manager = ProviderManager()
        claude_code = _RecordingProvider(response="claude_code sağlayıcı hatası: zaman aşımı")
        codex = _RecordingProvider(response="Codex cevabı.")
        manager._providers = {"claude_code": claude_code, "codex": codex}

        manager.route_and_generate(GOAL_PROMPT, task_type="coding", preferred_provider="claude_code")

        assert claude_code.received_prompts == [GOAL_PROMPT]
        assert codex.received_prompts == [GOAL_PROMPT]
        assert claude_code.received_prompts == codex.received_prompts
        assert "src/media/quality.py" in codex.received_prompts[0]
