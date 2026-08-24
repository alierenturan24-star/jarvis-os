from pathlib import Path
from playwright.sync_api import sync_playwright
import html as html_escape
import json

root = Path(__file__).resolve().parents[1]
output = root / "workspace" / "artifacts" / "acceptance" / "youtube-learning-390x844.png"
output.parent.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    markup = (root / "src/control_center/web/index.html").read_text(encoding="utf-8")
    css = (root / "src/control_center/web/app.css").read_text(encoding="utf-8")
    markup = markup.replace('<link rel="stylesheet" href="/app.css">', f"<style>{css}</style>")
    page.set_content(markup)
    state = json.loads((root / "workspace/control_center/state.json").read_text(encoding="utf-8"))
    productions = state["youtube_learning"]["productions"]
    latest = productions[-1]
    page.locator("#home").evaluate("node => node.classList.remove('active')")
    page.locator("#youtube").evaluate("node => node.classList.add('active')")
    history_cards = []
    for row in reversed(productions):
        thumbnail = row["artifact"].get("thumbnail_path")
        image = f'<img src="{Path(thumbnail).resolve().as_uri()}" alt="thumbnail">' if thumbnail else ""
        history_cards.append(
            f"<article>{image}<h3>{html_escape.escape(row['topic'])}</h3>"
            f"<p>Quality {row['quality']['overall']} · Motion {row['quality']['motion']} · "
            f"Story {row['quality']['story']}</p></article>"
        )
    page.locator("#youtubeHistory").evaluate(
        "(node, value) => node.innerHTML = value", "".join(history_cards))
    previous = productions[-2]
    changed = [key for key, value in latest["fingerprints"].items() if previous["fingerprints"].get(key) != value]
    page.locator("#youtubeLearning").evaluate("(node, value) => node.innerHTML = value",
        f"<article><h3>WHAT CHANGED</h3><p>{html_escape.escape(' · '.join(changed))}</p><h3>NEXT CHANGES</h3><p>{html_escape.escape(' · '.join(latest['learning']['change_next']))}</p></article>"
    )
    page.locator("#youtubeCharacters").evaluate("(node, value) => node.innerHTML = value",
        f"<article><h3>Leni</h3><p>{html_escape.escape(' · '.join(state['youtube_learning']['characters']['Leni']['successful_poses']))}</p></article>"
    )
    page.locator("#youtubeAnalytics").evaluate("(node, value) => node.innerHTML = value", "<article><h3>YOUTUBE ANALYTICS · NOT CONNECTED</h3></article>")
    video_uri = Path(latest["artifact"]["final_video_path"]).as_uri()
    thumb_uri = Path(latest["artifact"]["thumbnail_path"]).resolve().as_uri()
    page.locator("#youtubeArtifacts").evaluate("(node, value) => node.innerHTML = value",
        f'<article><video controls src="{video_uri}"></video><img src="{thumb_uri}" alt="Production 2 thumbnail"><h3>Production 2 preview + thumbnail</h3></article>')
    page.screenshot(path=str(output), full_page=True)
    assert page.locator("#youtube").is_visible()
    assert page.locator("#youtubeHistory").is_visible()
    assert page.locator("#youtubeLearning").is_visible()
    assert page.locator("#youtubeCharacters").is_visible()
    assert page.locator("#youtubeAnalytics").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= 390")
    browser.close()
print(output)
