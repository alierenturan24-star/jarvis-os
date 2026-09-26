from __future__ import annotations

from src.providers.wikimedia_media_provider import WikimediaMediaProvider


class _Response:
    def __init__(self, *, payload=None, content=b"", status_code=200):
        self._payload = payload
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


def test_wikimedia_provider_keeps_license_attribution(monkeypatch):
    api_payload = {
        "query": {"pages": {"1": {"imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/free.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Free.jpg",
            "extmetadata": {
                "LicenseShortName": {"value": "CC BY 4.0"},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                "Artist": {"value": "<b>Example Author</b>"},
            },
        }]}}},
    }

    def fake_get(url, **kwargs):
        if "w/api.php" in url:
            return _Response(payload=api_payload)
        return _Response(content=b"image" * 2000)

    monkeypatch.setattr("requests.get", fake_get)

    result = WikimediaMediaProvider().generate_image("Swiss Alps")

    assert result.success is True
    assert result.cost_class == "free"
    assert result.provenance["generation_type"] == "licensed_stock_retrieval"
    assert result.provenance["license"] == "CC BY 4.0"
    assert result.provenance["author"] == "Example Author"
    assert result.provenance["source_url"].startswith("https://commons.wikimedia.org/")


def test_wikimedia_provider_rejects_share_alike_for_simple_reuse(monkeypatch):
    api_payload = {
        "query": {"pages": {"1": {"imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/share-alike.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:ShareAlike.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}},
        }]}}},
    }
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: _Response(payload=api_payload))

    result = WikimediaMediaProvider().generate_image("Swiss city")

    assert result.success is False
    assert "No reusable" in result.error
