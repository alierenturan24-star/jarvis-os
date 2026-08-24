from pathlib import Path


def test_youtube_learning_mobile_contract_has_preview_thumbnail_and_fields():
    web = Path("src/control_center/web")
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "app.css").read_text(encoding="utf-8")
    assert all(name in html for name in (
        "youtubeHistory", "youtubeLearning", "youtubeCharacters",
        "youtubeExperiments", "youtubeAnalytics", "youtubeArtifacts",
    ))
    assert "thumbnail_path" in js and "WHAT CHANGED" in js
    assert "@media(max-width:390px)" in css
    assert ".cards{grid-template-columns:1fr}" in css
