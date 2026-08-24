from __future__ import annotations

from src.research.report_builder import ReportBuilder

# Sprint 37 canlı testinde yakalandı: uzun bir konu (ör. tüm kullanıcı
# isteğinin cümlesi) dosya adına AYNEN yazılınca Windows MAX_PATH (260
# karakter) sınırı aşılıyor, ``save()`` "[Errno 22] Invalid argument" ile
# çöküyordu -- Sprint 37'ye ÖZGÜ değil, ``ReportBuilder`` önceden de bu
# hataya açıktı, uzun bir istekle ilk kez tetiklendi.


class TestSafeFilename:
    def test_short_topic_is_unaffected(self):
        assert ReportBuilder._safe_filename("bitcoin fiyatı") == "bitcoin_fiyatı"

    def test_long_topic_is_truncated_to_a_safe_length(self):
        long_topic = "a" * 500
        result = ReportBuilder._safe_filename(long_topic)
        assert len(result) <= ReportBuilder._MAX_FILENAME_TOPIC_LENGTH

    def test_truncated_filename_has_no_trailing_underscore(self):
        long_topic = ("kelime " * 100).strip()
        result = ReportBuilder._safe_filename(long_topic)
        assert not result.endswith("_")

    def test_save_does_not_crash_on_a_very_long_topic(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        builder = ReportBuilder()
        very_long_topic = (
            "JARVIS, YouTube otomasyonunda daha iyi ol. " * 6
            + "(Not: 2. tur -- önceki turda şunlar yeterli bulunmadı: "
            "darkzOGx/youtube-automation-agent: Sandbox FAIL.)"
        )
        path = builder.save(very_long_topic, "özet", [])
        assert path.exists()
