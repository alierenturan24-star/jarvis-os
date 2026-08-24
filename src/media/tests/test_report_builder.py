from __future__ import annotations

from pathlib import Path

from src.media.report_builder import MediaReportBuilder


class TestMediaReportBuilder:
    def test_save_writes_a_markdown_file_under_workspace_media(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        builder = MediaReportBuilder()

        path = builder.save(
            topic="Bitcoin neden düştü",
            duration_seconds=60,
            plan_text="SENARYO\n...",
            quality_summary="Tüm bölümler mevcut.",
        )

        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Bitcoin neden düştü" in content
        assert "SENARYO" in content
        assert "YouTube'a yüklenmedi" in content

    def test_long_topic_does_not_exceed_windows_path_limit(self, tmp_path, monkeypatch):
        # Sprint 38'de research/report_builder.py'de yakalanan MAX_PATH
        # hatasının media için de BAŞTAN önlenmesi -- bkz. Sprint 39 notu.
        monkeypatch.chdir(tmp_path)
        builder = MediaReportBuilder()

        long_topic = "Bu çok uzun bir YouTube Shorts konusu " * 10
        path = builder.save(
            topic=long_topic, duration_seconds=60, plan_text="SENARYO\n...", quality_summary="ok",
        )

        assert path.exists()
        assert len(path.name) < 120
