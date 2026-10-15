from __future__ import annotations

from pathlib import Path

from src.providers.yt_dlp_media_provider import (
    LicensedYtDlpVideoProvider, _license_allowed,
)


class _FakeYDL:
    def __init__(self, options: dict, *, license_name: str = "Creative Commons Attribution license (reuse allowed)"):
        self.options = options
        self.license_name = license_name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url: str, download: bool = False):
        if url.startswith("ytsearch"):
            return {"entries": [{"id": "abc123"}]}
        info = {
            "id": "abc123",
            "title": "Swiss Parliament",
            "uploader": "Example Creator",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "license": self.license_name,
            "duration": 120,
        }
        if download:
            target = self.options["outtmpl"].replace("%(ext)s", "mp4")
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"0" * 20_000)
        return info


def _factory(license_name: str):
    return lambda options: _FakeYDL(options, license_name=license_name)


def test_youtube_creative_commons_license_is_allowed():
    assert _license_allowed("Creative Commons Attribution license (reuse allowed)")
    assert _license_allowed("CC BY 4.0")
    assert not _license_allowed("Standard YouTube License")
    assert not _license_allowed("CC BY-SA 4.0")


def test_provider_downloads_only_explicit_cc_by(tmp_path):
    provider = LicensedYtDlpVideoProvider(
        _factory("Creative Commons Attribution license (reuse allowed)")
    )
    result = provider.find_and_download("Bundeshaus Bern parliament video", tmp_path)
    assert result.success
    assert Path(result.path).is_file()
    assert result.provenance["source_url"].startswith("https://www.youtube.com/")
    assert result.provenance["author"] == "Example Creator"
    assert result.provenance["attribution_required"] is True


def test_provider_rejects_standard_youtube_license(tmp_path):
    provider = LicensedYtDlpVideoProvider(_factory("Standard YouTube License"))
    result = provider.find_and_download("Bundeshaus Bern", tmp_path)
    assert result.success is False
    assert "license=Standard YouTube License" in result.error
    assert list(tmp_path.iterdir()) == []


def test_provider_rejects_share_alike(tmp_path):
    provider = LicensedYtDlpVideoProvider(_factory("CC BY-SA 4.0"))
    result = provider.find_and_download("Swiss flag Bern", tmp_path)
    assert result.success is False
