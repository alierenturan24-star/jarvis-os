from __future__ import annotations

from src.mission.department import detect_mission_type, detect_research_loop_intent

# Sprint 37: canlı kabul testinin (bölüm 9) iki örnek istemi -- ikisi de
# "daha iyi ol" ifadesini AÇIKÇA içerir.
YOUTUBE_SELF_IMPROVEMENT_PROMPT = (
    "JARVIS, YouTube otomasyonunda daha iyi ol. Bu hedef için kullanabileceğin "
    "ücretsiz AI'ları, açık kaynak projeleri, skill'leri, MCP'leri, araçları ve "
    "yöntemleri araştır."
)
LIVE_ACCEPTANCE_PROMPT = (
    "JARVIS, YouTube otomasyonunda daha iyi ol. Bu hedef için ücretsiz AI'ları, "
    "açık kaynak projeleri, skill'leri, MCP'leri ve otomasyon araçlarını araştır. "
    "En yararlı seçenekleri değerlendir. Gerekirse farklı araçlar ve AI modelleri "
    "kullan. Kendini nasıl geliştirebileceğini bana raporla. Hiçbir şeyi kurma "
    "veya entegre etme."
)


class TestDetectResearchLoopIntent:
    def test_youtube_self_improvement_prompt_triggers_loop(self):
        assert detect_research_loop_intent(YOUTUBE_SELF_IMPROVEMENT_PROMPT) is True

    def test_live_acceptance_prompt_triggers_loop(self):
        assert detect_research_loop_intent(LIVE_ACCEPTANCE_PROMPT) is True

    def test_ordinary_single_shot_mission_does_not_trigger_loop(self):
        assert detect_mission_type("bitcoin fiyatını araştır") is not None
        assert detect_research_loop_intent("bitcoin fiyatını araştır") is False

    def test_plain_chat_never_triggers_loop_even_with_generic_words(self):
        assert detect_mission_type("merhaba, nasılsın") is None
        assert detect_research_loop_intent("merhaba, nasılsın") is False

    def test_self_improvement_phrase_without_any_mission_signal_does_not_trigger(self):
        # "self improvement" TEK BAŞINA (hiçbir Mission-tipi anahtar
        # kelimeyle ÇAKIŞMAYAN bir cümlede) -- KURAL: loop yalnızca ZATEN
        # bir Mission sayılan isteklere EKLENİR, yeni bir sınıflandırma
        # İCAT ETMEZ.
        text = "Bugün hava çok güzel, self improvement önemli bence."
        assert detect_mission_type(text) is None
        assert detect_research_loop_intent(text) is False

    def test_english_self_improvement_phrase_also_triggers_when_mission_detected(self):
        text = "Research free AI tools for coding, self improvement for JARVIS coding skills, kod yaz."
        assert detect_mission_type(text) is not None
        assert detect_research_loop_intent(text) is True
