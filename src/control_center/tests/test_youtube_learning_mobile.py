from pathlib import Path


def test_youtube_learning_mobile_contract_has_preview_thumbnail_and_fields():
    web = Path("src/control_center/web")
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "app.css").read_text(encoding="utf-8")
    assert all(name in html for name in (
        "youtubeHistory", "youtubeLearning", "youtubeCharacters",
        "youtubeExperiments", "youtubeAnalytics", "youtubeArtifacts", "videoDemo",
    ))
    assert "youtube-one-click-remix" in js
    assert "TEK TIK: TREND BUL VE HAZIR VİDEOYU KURGULA" in js
    assert "Önceki konuları tekrarlama" in js
    assert "30 güne genişlet" in js
    assert "Ücretli servis kullanma" in js
    one_click_goal = js.split("const goal='", 1)[1].split("';try", 1)[0]
    assert len(one_click_goal) < 450
    assert "Public Domain, CC0 veya CC BY" in html
    assert "thumbnail_path" in js and "WHAT CHANGED" in js
    assert "@media(max-width:390px)" in css
    assert ".cards{grid-template-columns:1fr}" in css
