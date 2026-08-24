from __future__ import annotations

from src.mission.models import MissionType
from src.mission.target_resolver import TargetKind, TargetResolver, resolve_search_category


class TestRepositoryTarget:
    def test_bare_slug_near_github_context_resolves_to_repository(self):
        target = TargetResolver().resolve(
            "GitHub üzerinde browser-use/browser-use reposunu incele.",
            mission_type=MissionType.GITHUB,
        )
        assert target.kind == TargetKind.REPOSITORY
        assert target.owner == "browser-use"
        assert target.repo == "browser-use"
        assert target.full_name == "browser-use/browser-use"
        assert target.url == "https://github.com/browser-use/browser-use"

    def test_explicit_github_url_resolves_to_repository(self):
        target = TargetResolver().resolve(
            "https://github.com/browser-use/browser-use adresini aç",
        )
        assert target.kind == TargetKind.REPOSITORY
        assert target.full_name == "browser-use/browser-use"

    def test_owner_only_url_does_not_become_repository(self):
        # Regresyon: "github.com/owner" (repo'suz) yanlışlıkla REPOSITORY
        # sanılmamalı (canlı testte yakalanan hata).
        target = TargetResolver().resolve("https://github.com/browser-use adresini aç")
        assert target.kind == TargetKind.OWNER
        assert target.owner == "browser-use"

    def test_unrelated_slash_phrase_far_from_github_mention_is_not_a_repository(self):
        # Sprint 38 canlı testinde yakalandı: "github" kelimesi metnin bir
        # yerinde geçtiği için, çok uzaktaki alakasız "AI/provider" ifadesi
        # (bir repo YOK) yanlışlıkla owner/repo sanılıyordu -- bu istek
        # CATEGORY'e (youtube automation) düşmeli, REPOSITORY'ye değil.
        text = (
            "Sonra ücretsiz AI modelleri, açık kaynak projeler, GitHub repoları, "
            "MCP'ler, skill'ler ve araçları araştır. "
            "Sonunda bana hangi ücretsiz AI/provider'ları kullandığını raporla."
        )
        target = TargetResolver().resolve(text, mission_type=MissionType.YOUTUBE)
        assert target.kind == TargetKind.CATEGORY
        assert target.category_hint == "youtube automation"


class TestOwnerTarget:
    def test_owner_only_github_url(self):
        target = TargetResolver().resolve("https://github.com/browser-use sayfasını aç")
        assert target.kind == TargetKind.OWNER
        assert target.owner == "browser-use"
        assert target.url == "https://github.com/browser-use"


class TestCategoryTarget:
    def test_named_tools_are_preserved_with_category_as_fallback(self):
        for text, expected in (
            ("Agent-Reach'i araştır.", "Agent-Reach"),
            ("ComfyUI'yi araştır.", "ComfyUI"),
            ("Open WebUI'yi araştır.", "Open WebUI"),
        ):
            target = TargetResolver().resolve(text, mission_type=MissionType.RESEARCH)
            assert target.requested_name == expected
            assert target.category_hint == "ai agent"

    def test_text_containing_known_category(self):
        target = TargetResolver().resolve("bana bir mcp server bul")
        assert target.kind == TargetKind.CATEGORY
        assert target.category_hint == "mcp server"

    def test_mission_type_fallback_when_no_category_keyword(self):
        target = TargetResolver().resolve("Yeni coin araştır.", mission_type=MissionType.FINANCE)
        assert target.kind == TargetKind.CATEGORY
        assert target.category_hint == "finance ai"


class TestFreeTextTarget:
    def test_no_signal_and_no_mission_type_is_free_text(self):
        target = TargetResolver().resolve("Jarvis'i geliştir.")
        assert target.kind == TargetKind.FREE_TEXT
        assert target.category_hint is None
        assert target.text == "Jarvis'i geliştir."

    def test_non_github_url_preserved_as_free_text(self):
        target = TargetResolver().resolve("https://example.com/docs adresini aç")
        assert target.kind == TargetKind.FREE_TEXT
        assert target.text == "https://example.com/docs"


class TestBackwardCompatibleResolveSearchCategory:
    """``resolve_search_category`` (eski adı: department_adapters.py)
    davranışı BİREBİR AYNI kalmalı -- artık target_resolver.py'de yaşıyor
    ama aynı imza/çıktıyla."""

    def test_falls_back_to_ai_agent_for_turkish_free_text(self):
        assert resolve_search_category("Jarvis'i geliştir.") == "ai agent"

    def test_matches_a_supported_category_when_present_in_text(self):
        assert resolve_search_category("bana bir mcp server bul") == "mcp server"
