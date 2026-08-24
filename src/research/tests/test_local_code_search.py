from __future__ import annotations

from src.research.local_code_search import (
    MAX_FILE_EXCERPT_CHARS,
    detect_referenced_symbols,
    format_evidence,
    gather_code_evidence,
    is_local_code_query,
)

# Sprint 41 (LOCAL CODE INTELLIGENCE) -- bu testler GERÇEK proje dosyalarını
# okur (mock YOK): ``CostOptimizer``/``ProviderManager``/``AIStrategyEngine``
# JARVIS'in kendi kod tabanında GERÇEKTEN var olan sınıflardır, bu yüzden
# sahte bir index kurmak yerine ZATEN VAR OLAN gerçek taramayı kullanmak
# hem daha basit hem de "sinyal gerçek koddan gelir" iddiasını GERÇEKTEN
# doğrular.


class TestDetectReferencedSymbols:
    def test_finds_real_known_classes(self):
        text = "CostOptimizer ve ProviderManager arasındaki çağrı zincirini bul."
        found = detect_referenced_symbols(text)
        assert "CostOptimizer" in found
        assert "ProviderManager" in found

    def test_finds_ai_strategy_engine_after_scan_folder_extension(self):
        # Sprint 41: JARVIS_SCAN_FOLDERS'a "src/strategy" eklendi --
        # AIStrategyEngine artık bulunabilmeli (önceden bulunamıyordu).
        found = detect_referenced_symbols("AIStrategyEngine nasıl çalışıyor?")
        assert "AIStrategyEngine" in found

    def test_plain_english_sentence_without_real_symbols_finds_nothing_relevant(self):
        found = detect_referenced_symbols("Bugün hava çok güzel, dışarı çıkalım mı?")
        assert found == []

    def test_jarvis_address_form_is_excluded_even_though_it_is_a_real_class(self):
        # Sprint 41 canlı testinde yakalandı: "Jarvis," neredeyse HER
        # istekte bir HİTAP olarak geçer -- src/core/jarvis.py'deki GERÇEK
        # ``Jarvis`` sınıfıyla aynı ada sahip olsa da, bu YÜZDEN her mesaj
        # yanlışlıkla yerel-kod sorgusu SANILMAMALI.
        found = detect_referenced_symbols(
            "Jarvis, Bitcoin neden düştü konusunda 60 saniyelik YouTube Shorts hazırla."
        )
        assert "Jarvis" not in found
        assert found == []  # başka hiçbir gerçek sembole de referans yok

    def test_short_common_names_are_filtered_as_noise(self):
        # "Task" gibi 4 karakterden kısa/çok genel adlar (MIN_SYMBOL_NAME_LENGTH)
        # gürültü olarak elenmemeli -- ama en az uzunluk kontrolü çöküşe
        # yol AÇMAMALI.
        found = detect_referenced_symbols("Bu bir görev.")
        assert isinstance(found, list)


class TestIsLocalCodeQuery:
    def test_true_when_real_symbol_referenced(self):
        assert is_local_code_query("ProviderManager'ı incele.") is True

    def test_false_for_generic_text(self):
        assert is_local_code_query("Bitcoin neden düştü?") is False

    def test_false_for_ordinary_request_addressed_to_jarvis(self):
        # Sprint 41 TEST 2 regresyonu: "Jarvis," hitabı TEK BAŞINA yerel
        # kod sorgusu SAYILMAMALI.
        assert is_local_code_query(
            "Jarvis, Bitcoin neden düştü konusunda 60 saniyelik YouTube Shorts hazırla. "
            "Güncel bilgiyi araştır."
        ) is False


class TestGatherCodeEvidence:
    def test_returns_real_file_paths_and_bounded_excerpts(self):
        evidence = gather_code_evidence(["CostOptimizer"])
        assert len(evidence) == 1
        assert evidence[0].file_path == "src/providers/cost_optimizer.py"
        assert len(evidence[0].excerpt) <= MAX_FILE_EXCERPT_CHARS
        assert "class CostOptimizer" in evidence[0].excerpt

    def test_ast_extraction_excludes_unrelated_imports(self):
        # Sprint 41 CONTEXT CONTROL: dosyanın TAMAMI (import'lar dahil)
        # DEĞİL, yalnızca ilgili sınıfın kaynak segmenti gönderilmeli.
        evidence = gather_code_evidence(["CostOptimizer"])
        assert "from src.config.settings import Settings" not in evidence[0].excerpt

    def test_unknown_symbol_returns_no_evidence(self):
        evidence = gather_code_evidence(["BuSinifKesinlikleYok123"])
        assert evidence == []

    def test_respects_max_symbols_cap(self):
        # Gerçekten var olan birden çok sembol versek bile, en fazla
        # MAX_SYMBOLS_PER_QUERY kadarı işlenir (context patlamasın diye).
        many_symbols = ["CostOptimizer", "ProviderManager", "AIStrategyEngine", "MediaManager", "FinanceManager", "AutomationManager"]
        evidence = gather_code_evidence(many_symbols, max_symbols=3)
        assert len(evidence) <= 3


class TestFormatEvidence:
    def test_no_evidence_message_is_honest(self):
        text = format_evidence([])
        assert "bulunamadı" in text

    def test_evidence_is_labeled_as_local_not_internet(self):
        evidence = gather_code_evidence(["CostOptimizer"])
        text = format_evidence(evidence)
        assert "internet KULLANILMADI" in text
        assert "CostOptimizer" in text
