from __future__ import annotations

from src.finance.report_builder import FinanceReportBuilder

# Sprint 39 canlı testinde yakalandı: research/report_builder.py'de
# (Sprint 38) düzeltilen AYNI Windows MAX_PATH hatası finance için de
# tetiklendi -- uzun bir istek metni "asset" olarak ham dosya adına
# geçince "[Errno 22] Invalid argument" ile çöküyordu.


class TestSafeFilename:
    def test_short_asset_is_unaffected(self):
        assert FinanceReportBuilder._safe_filename("bitcoin") == "bitcoin"

    def test_long_asset_is_truncated_to_a_safe_length(self):
        long_asset = "a" * 500
        result = FinanceReportBuilder._safe_filename(long_asset)
        assert len(result) <= FinanceReportBuilder._MAX_FILENAME_TOPIC_LENGTH

    def test_truncated_filename_has_no_trailing_underscore(self):
        long_asset = ("kelime " * 100).strip()
        result = FinanceReportBuilder._safe_filename(long_asset)
        assert not result.endswith("_")

    def test_save_does_not_crash_on_a_very_long_asset(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        builder = FinanceReportBuilder()
        very_long_asset = (
            "Jarvis, Bitcoin neden düştü konusunda 60 saniyelik bir YouTube Shorts hazırla. " * 3
        )
        path = builder.save(
            asset=very_long_asset, analysis="özet", risk_score=10,
            opportunity_score=20, sentiment_score=30, results=[],
        )
        assert path.exists()
