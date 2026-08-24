from src.mission.department import detect_mission_type
from src.mission.models import MissionType
from src.providers.cost_optimizer import CostOptimizer


def test_local_runtime_fact_requests_remain_normal_chat():
    prompts = (
        "Bugünün tarihi nedir?",
        "JARVIS sistem durumunu söyle.",
        "Bugünün tarihini ve kısa sistem durum raporunu ver.",
        "Runtime state, PID ve son hatayı söyle.",
    )

    for prompt in prompts:
        assert detect_mission_type(prompt) is None


def test_real_research_requests_still_create_missions():
    expected = {
        "İnternetten güncel AI agent araçlarını araştır ve rapor hazırla.": MissionType.RESEARCH,
        # The existing priority semantics specialize this request as AI discovery.
        "GitHub'da açık kaynak AI agent frameworklerini araştır.": MissionType.AI_DISCOVERY,
        "Gemini ve Claude'u araştırıp karşılaştır.": MissionType.RESEARCH,
        "Bu repository'deki runtime mimarisini araştır ve raporla.": MissionType.RESEARCH,
    }

    for prompt, mission_type in expected.items():
        assert detect_mission_type(prompt) == mission_type


def test_live_prompt_does_not_treat_bulunma_as_research_or_bugunun_as_coding():
    prompt = (
        "Bugünün gerçek tarihini ve yerel saat dilimini belirt. Ardından yalnızca "
        "doğrulanmış runtime gerçeklerini kullanarak kısa bir JARVIS sistem durum "
        "raporu ver. Runtime context içinde olmayan hiçbir subsystem hakkında aktif, "
        "sağlıklı veya çalışıyor iddiasında bulunma. Harici işlem yapma, dosya "
        "değiştirme ve hiçbir şey yayınlama."
    )

    assert detect_mission_type(prompt) is None
    assert CostOptimizer.classify(prompt) == "chat"
    assert CostOptimizer.classify("Bu bug için düzeltme yap.") == "coding"
