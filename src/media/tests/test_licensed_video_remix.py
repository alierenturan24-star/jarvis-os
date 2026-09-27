from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.media.capability_model import MediaGenerationResult, MediaModelProfile, TEXT_TO_IMAGE, TEXT_TO_VIDEO
from src.media.production import GeneralProductionBuilder
from src.media.manager import _looks_predominantly_english
from src.media.renderer import LocalVideoRenderer, find_ffmpeg
from src.providers.wikimedia_media_provider import WikimediaMediaProvider


PLAN = """
SENARYO
İsviçre'de yaşayan Türkler için güncel konuyu kısa ve kaynaklı biçimde anlatıyoruz.

SAHNELER
Sahne 1 (~2 sn): Anlatım: İlk bilgi. | Görsel: İsviçre şehir yaşamı | Ekran yazısı: Giriş
Sahne 2 (~2 sn): Anlatım: İkinci bilgi. | Görsel: İsviçre toplu taşıma | Ekran yazısı: Ayrıntı
Sahne 3 (~2 sn): Anlatım: Üçüncü bilgi. | Görsel: İsviçre gündelik hayat | Ekran yazısı: Bağlam
Sahne 4 (~2 sn): Anlatım: Sonuç. | Görsel: İsviçre manzarası | Ekran yazısı: Sonuç

SESLENDİRME PLANI
Yeni Türkçe anlatım.

GÖRSEL/VİDEO PLANI
Lisansı doğrulanmış Commons klipleri.

MÜZİK VE SES PLANI
Yerel özgün müzik.

ALTYAZI
Türkçe.

THUMBNAIL FİKRİ
İsviçre'de bugün

BAŞLIK
İsviçre'de Bugün Ne Değişti?

AÇIKLAMA
Kaynaklı kısa açıklama.

ETİKETLER
İsviçre, Türkler, gündem
"""


class _ApiResponse:
    content = b""

    def raise_for_status(self):
        return None

    def json(self):
        return {"query": {"pages": {"1": {"imageinfo": [{
            "mime": "video/webm", "size": 20_000,
            "url": "https://upload.wikimedia.org/example.webm",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:example.webm",
            "extmetadata": {
                "LicenseShortName": {"value": "CC BY 4.0"},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                "Artist": {"value": "Example Author"},
            },
        }]}}}}


class _DownloadResponse:
    content = b""

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        del chunk_size
        return iter((b"v" * 12_000,))


def test_wikimedia_clip_requires_and_persists_reusable_license(monkeypatch):
    responses = iter((_ApiResponse(), _DownloadResponse()))
    monkeypatch.setattr("src.providers.wikimedia_media_provider.requests.get", lambda *a, **k: next(responses))

    result = WikimediaMediaProvider().generate_video_clip("Swiss city life")

    assert result.success
    assert result.capability == TEXT_TO_VIDEO
    assert result.provenance["license"] == "CC BY 4.0"
    assert result.provenance["source_url"].startswith("https://commons.wikimedia.org/")
    assert result.provenance["attribution_required"] is True


def test_wrong_english_plan_is_detected_for_turkish_remix_request():
    assert _looks_predominantly_english(
        "Have you ever wondered how the traditional instrument is made and how every detail works?"
    ) is True
    assert _looks_predominantly_english(
        "Bu geleneksel çalgının nasıl yapıldığını ve ustaların çalışmalarını anlatıyoruz."
    ) is False


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg unavailable")
def test_licensed_clip_to_new_narrated_vertical_mp4_pipeline(tmp_path, monkeypatch):
    ffmpeg = find_ffmpeg()
    source = tmp_path / "licensed.webm"
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "3",
        "-c:v", "libvpx-vp9", str(source),
    ], check=True, timeout=60)
    clip_bytes = source.read_bytes()

    def licensed_clip(self, prompt, **kwargs):
        del self, prompt, kwargs
        return MediaGenerationResult(
            True, "wikimedia_commons", "licensed-video-search-v1", TEXT_TO_VIDEO,
            content_bytes=clip_bytes, cost_class="free",
            provenance={
                "generation_type": "licensed_stock_video_retrieval", "mime": "video/webm",
                "source_url": "https://commons.wikimedia.org/wiki/File:test.webm",
                "author": "Test Author", "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution_required": True,
            },
        )

    def narration(root, script, language, voice):
        del script, language, voice
        target = Path(root) / "narration.wav"
        subprocess.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=8",
            "-c:a", "pcm_s16le", str(target),
        ], check=True, timeout=30)
        return target, "test_local_voice", True

    profile = MediaModelProfile(
        provider_id="unused_image", model_id="unused", capabilities=(TEXT_TO_IMAGE,),
        availability=True, auth_required=False, cost_class="free", free_tier=True,
        subscription_cli=False, local_or_remote="local", quality_tier=1, speed_tier=1,
    )
    monkeypatch.setattr(WikimediaMediaProvider, "generate_video_clip", licensed_clip)
    monkeypatch.setattr("src.media.production.write_narration_audio", narration)
    monkeypatch.setattr("src.media.production.narration_capability_available", lambda: True)
    monkeypatch.setattr("src.media.production.rank_available_providers", lambda *a, **k: ([(profile, object())], ()))

    builder = GeneralProductionBuilder(
        source_root=tmp_path / "unused", output_root=tmp_path / "packages",
    )
    built = builder.build(
        goal="İsviçre gündemi", plan_text=PLAN, memory={}, duration_seconds=8,
        channel_language="tr-TR", research_grounded=True,
        research_evidence_ref={"source_count": 2}, free_only=True,
    )

    assert built.success, built.error
    manifest = json.loads(Path(built.manifest_path).read_text(encoding="utf-8"))
    assert len(manifest["scene_files"]) == 4
    assert all(row["generation_type"] == "licensed_stock_video_retrieval"
               for row in manifest["scene_provenance"])
    assert manifest["music"]["license"] == "original"
    assert manifest["publish_used"] is False
    assert Path(manifest["thumbnail_path"]).is_file()
    assert (Path(built.manifest_path).parent / manifest["subtitle_file"]).is_file()

    monkeypatch.setattr("src.media.renderer._find_production_package", lambda topic: Path(built.manifest_path))
    rendered = LocalVideoRenderer(output_root=tmp_path / "rendered").render(
        "İsviçre gündemi", PLAN, 8,
    )
    assert rendered.success, rendered.error
    assert Path(rendered.artifact_path).is_file()
    assert Path(rendered.artifact_path).stat().st_size > 20_000
