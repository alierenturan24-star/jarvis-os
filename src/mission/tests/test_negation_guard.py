from __future__ import annotations

from src.mission.department import MissionType, detect_mission_type, keyword_matches


class TestKeywordMatchesNegation:
    def test_bare_keyword_matches(self):
        assert keyword_matches("internette araştır lütfen", "internette araştır") is True

    def test_negated_keyword_does_not_match(self):
        assert keyword_matches("internette araştırma yapma", "internette araştır") is False

    def test_negated_keyword_followed_by_more_text_does_not_match(self):
        assert keyword_matches(
            "internette araştırma yapma. hiçbir dosyayı değiştirme.", "internette araştır"
        ) is False

    def test_positive_continuation_yap_still_matches(self):
        assert keyword_matches("internette araştırma yap ve özet ver", "internette araştır") is True

    def test_negated_but_keyword_also_appears_positively_elsewhere_matches(self):
        text = "internette araştır lütfen, ama başka bir şeyi internette araştırma"
        assert keyword_matches(text, "internette araştır") is True

    def test_keyword_absent_returns_false(self):
        assert keyword_matches("bugün hava güzel", "internette araştır") is False


class TestDetectMissionTypeNegation:
    def test_sprint41_bug_scenario_does_not_trigger_browser(self):
        # Sprint 41'de bulunan hata: "internette araştırma YAPMA" ifadesi
        # BROWSER/RESEARCH'ü YANLIŞLIKLA tetikliyordu. Bu senaryoda kullanıcı
        # AÇIKÇA yerel kod incelemesi istiyor ve web aramasını REDDEDİYOR.
        text = (
            "Jarvis, bu projenin provider routing mimarisini incele. "
            "CostOptimizer, AIStrategyEngine ve ProviderManager arasındaki "
            "gerçek çağrı zincirini proje kodundan bul. İnternette araştırma "
            "yapma. Hiçbir dosyayı değiştirme."
        )
        assert detect_mission_type(text) != MissionType.BROWSER

    def test_simple_negation_does_not_trigger_browser(self):
        text = "Jarvis, bunu internette araştırma. CostOptimizer kodunu yerelden incele."
        assert detect_mission_type(text) != MissionType.BROWSER

    def test_bare_positive_research_still_triggers_browser(self):
        assert detect_mission_type("İnternette araştır lütfen.") == MissionType.BROWSER

    def test_positive_with_yap_continuation_still_triggers_browser(self):
        assert detect_mission_type("İnternette araştırma yap ve bana özet ver.") == MissionType.BROWSER

    def test_positive_open_and_research_still_triggers_browser(self):
        assert detect_mission_type("Web sitesi aç ve internette araştır.") == MissionType.BROWSER
