import json
import shutil
from pathlib import Path

from src.media.production import GeneralProductionBuilder, PRODUCTION_CAPABILITIES, parse_plan_text
from src.media.quality import validate_media_goal_artifact
from src.media.renderer import LocalVideoRenderer, find_goal_production_package, has_production_media_capability

# Sprint: research/production pipeline audit. These tests used to assert
# GeneralProductionBuilder always returns hardcoded German "Leni" story
# content (character_identity["name"] == "Leni", fixed
# opportunity_selection candidates) regardless of the requested goal -- that
# WAS the exact defect behind production 77b5c0b1e9c344d2ac1cbca052e85b7c
# (a Swiss Insider goal silently received unrelated children's-cartoon
# content). The builder now parses the real, goal-driven plan text
# (MediaManager.plan()'s route_and_generate output) instead of hardcoding a
# story, and only ever touches the pre-authored "Leni" artwork when a caller
# explicitly passes ``allow_legacy_authored_series=True`` -- every other
# goal gets an honest CAPABILITY_GAP, never unrelated content.
#
# Sprint: capability-gate audit (mission 4a50230ffad2400bbb2aff173bd2a797).
# The legacy series used to be unlocked by scanning the goal text for the
# substring "leni" -- negation-blind: a goal that explicitly PROHIBITS Leni/
# silver-boat/lantern-seed assets still contains the word "leni" and was
# incorrectly treated as an opt-in request for them. Real production
# dispatch (MediaManager.plan() -> GeneralProductionBuilder.build()) never
# passes ``allow_legacy_authored_series``, so it defaults to False and the
# legacy series is now available only to tests/configuration that request it
# explicitly via the parameter -- never inferred from free-text goal content.

REAL_SOURCE = Path("workspace/assets/media/channel-default-sources")


def _copy_real_sources(source_root: Path, *prefixes: str) -> None:
    source_root.mkdir(parents=True, exist_ok=True)
    for prefix in prefixes:
        for suffix in ("-storyboard.png", "-running-poses.png"):
            shutil.copy2(REAL_SOURCE / f"{prefix}{suffix}", source_root / f"{prefix}{suffix}")


def _fingerprint(source_root: Path, prefix: str) -> str:
    import hashlib
    return hashlib.sha256((source_root / f"{prefix}-storyboard.png").read_bytes()
                          + (source_root / f"{prefix}-running-poses.png").read_bytes()).hexdigest()


def _leni_plan_text(*, title: str = "Leni ve Fener Tohumu",
                     hook: str = "Leni ormanda parlayan bir tohum buldu!") -> str:
    return f"""SENARYO
Leni ormanda parlayan bir fener tohumu buluyor ve onu dikkatle dikiyor.

SAHNELER
Sahne 1 (~8 sn): Anlatım: {hook} | Görsel: Orman içinde parlayan tohum | Ekran yazısı: Buldum!
Sahne 2 (~9 sn): Anlatım: Onu dikkatle topraga dikti. | Görsel: Leni tohumu dikerken | Ekran yazısı: Dikiyorum
Sahne 3 (~9 sn): Anlatım: Isiklari takip ederek dereyi gecti. | Görsel: Isiklarin oldugu dere | Ekran yazısı: Takip
Sahne 4 (~9 sn): Anlatım: Utangac bir kirpiye yardim etti. | Görsel: Kirpi ile Leni | Ekran yazısı: Yardim
Sahne 5 (~9 sn): Anlatım: Birlikte sicak bir fener agaci buyudu. | Görsel: Fener agaci | Ekran yazısı: Buyudu

SESLENDİRME PLANI
Windows System.Speech kullanilacak.

GÖRSEL/VİDEO PLANI
Yerel storyboard gorselleri.

ALTYAZI PLANI
Sahne zamanlamasina gore.

THUMBNAIL FİKRİ
Leni fener agacinin yaninda

BAŞLIK
{title}

AÇIKLAMA
Leni ormanda parlayan bir tohum bulur ve onu buyutur.

ETİKETLER
leni, cocuk, macera, orman, fener
"""


def test_generic_video_resolves_real_repository_capabilities():
    assert has_production_media_capability("YouTube için yeni video üret")
    assert set(PRODUCTION_CAPABILITIES) == {"story_generation", "scene_generation",
        "character_visual_generation", "motion_generation", "narration_generation",
        "thumbnail_generation", "video_render", "technical_validation", "semantic_validation"}


def test_specific_pre_authored_goal_package_is_not_required():
    assert find_goal_production_package("entirely unseen generic youtube production goal") is None
    assert GeneralProductionBuilder().available


# Test A (part 1): a goal that does not ask for the authored "Leni" series
# gets an honest CAPABILITY_GAP, never the unrelated pre-authored artwork --
# this is the exact fix for the 77b5c0b1e9c344d2ac1cbca052e85b7c defect.
def test_non_leni_goal_returns_capability_gap_not_unrelated_story(tmp_path):
    source_root = tmp_path / "sources"
    _copy_real_sources(source_root, "lantern")
    plan_text = _leni_plan_text().replace("Leni", "Reporter").replace("leni", "reporter")
    builder = GeneralProductionBuilder(source_root=source_root, output_root=tmp_path / "generated")

    result = builder.build(goal="Swiss Insider için bugün bir haber videosu hazırla",
                            plan_text=plan_text, memory={}, duration_seconds=40)

    assert result.success is False
    assert "CAPABILITY_GAP" in result.error
    assert not result.manifest_path
    assert not list((tmp_path / "generated").rglob("production.json"))


# Test A (part 2): malformed/unparseable plan text must fail honestly, never
# silently fall back to a canned story.
def test_malformed_plan_text_fails_honestly(tmp_path):
    source_root = tmp_path / "sources"
    _copy_real_sources(source_root, "lantern")
    builder = GeneralProductionBuilder(source_root=source_root, output_root=tmp_path / "generated")

    result = builder.build(goal="Leni icin yeni bir macera videosu",
                            plan_text="not a real plan, missing all required sections",
                            memory={}, duration_seconds=40)

    assert result.success is False
    assert "script parsing failed" in result.error


def test_parse_plan_text_rejects_incomplete_scene_lines():
    broken = "SENARYO\nKisa bir senaryo.\n\nSAHNELER\nSahne 1: eksik format\n"
    assert parse_plan_text(broken) is None


def test_all_authored_sources_used_returns_capability_gap(tmp_path):
    source_root = tmp_path / "sources"
    _copy_real_sources(source_root, "lantern", "silver-boat")
    builder = GeneralProductionBuilder(source_root=source_root, output_root=tmp_path / "generated")
    memory = {"productions": [{"visual": {"source_generation_fingerprint": _fingerprint(source_root, name)}}
                              for name in ("lantern", "silver-boat")]}

    result = builder.build(goal="Leni icin yeni bir video", plan_text=_leni_plan_text(),
                            memory=memory, duration_seconds=40, allow_legacy_authored_series=True)

    assert not result.success and "exact reuse rejected" in result.error
    assert not result.manifest_path


# Regression for mission 4a50230ffad2400bbb2aff173bd2a797: a goal that
# EXPLICITLY PROHIBITS the legacy authored series ("do NOT use: Leni, silver
# boat, lantern seed, ... in that case stop honestly with CAPABILITY_GAP")
# still contains the literal word "leni" inside the prohibition clause. The
# old keyword-substring gate was negation-blind and unlocked the assets
# anyway; the new explicit-opt-in gate must not, regardless of what words
# appear in free-text goal content.
def test_goal_that_prohibits_leni_still_returns_capability_gap(tmp_path):
    source_root = tmp_path / "sources"
    _copy_real_sources(source_root, "lantern", "silver-boat")
    builder = GeneralProductionBuilder(source_root=source_root, output_root=tmp_path / "generated")
    goal = (
        "Swiss Insider icin bugun bir konu hazirla. Gercek image/video generation "
        "capability mevcut degilse: - Leni, - silver boat, - lantern seed, - demo, "
        "- placeholder, - alakasiz onceden hazirlanmis asset kullanma. Bu durumda "
        "CAPABILITY_GAP ile durustce dur."
    )

    result = builder.build(goal=goal, plan_text=_leni_plan_text(title="Hibrit Calisma Modeli"),
                            memory={}, duration_seconds=40)

    assert result.success is False
    assert "CAPABILITY_GAP" in result.error
    assert not result.manifest_path
    assert not list((tmp_path / "generated").rglob("production.json"))
    assert "character_visual_generation" in result.missing_capabilities
    assert "video_render" not in result.missing_capabilities


class _BuiltProduction:
    """Build once per test via a real GeneralProductionBuilder.build() call
    (real ffmpeg crops, real TTS) and expose the manifest for assertions --
    isolated to tmp_path so tests never depend on/pollute shared workspace
    state or each other's execution order."""

    def __init__(self, tmp_path: Path, *, title: str = "Leni ve Fener Tohumu",
                 hook: str = "Leni ormanda parlayan bir tohum buldu!",
                 channel_market: str = "Switzerland", channel_language: str = "de-CH",
                 research_grounded: bool = False) -> None:
        source_root = tmp_path / "sources"
        _copy_real_sources(source_root, "lantern")
        builder = GeneralProductionBuilder(source_root=source_root, output_root=tmp_path / "generated")
        self.result = builder.build(
            goal="Leni icin yeni bir macera videosu", plan_text=_leni_plan_text(title=title, hook=hook),
            memory={}, duration_seconds=44, channel_id="test-ch",
            channel_market=channel_market, channel_language=channel_language,
            research_grounded=research_grounded,
            research_evidence_ref={"created_at": "2026-08-01", "source_count": 3} if research_grounded else None,
            allow_legacy_authored_series=True,
        )
        assert self.result.success, self.result.error
        self.root = Path(self.result.manifest_path).parent
        self.manifest = json.loads(Path(self.result.manifest_path).read_text(encoding="utf-8"))


# Test C: selected_opportunity/creative_angle/title/hook trace to the real
# parsed plan text, not fixed literals -- two different plan texts must
# produce two different manifests.
def test_manifest_content_derives_from_real_plan_text(tmp_path):
    first = _BuiltProduction(tmp_path / "a", title="Leni ve Fener Tohumu",
                              hook="Leni ormanda parlayan bir tohum buldu!")
    second = _BuiltProduction(tmp_path / "b", title="Leni ve Yeni Bir Macera",
                               hook="Leni bu sefer daga tirmaniyor!")

    assert first.manifest["selected_title"] == "Leni ve Fener Tohumu"
    assert second.manifest["selected_title"] == "Leni ve Yeni Bir Macera"
    assert first.manifest["selected_opportunity"] == first.manifest["selected_title"]
    assert first.manifest["creative_angle"] == first.manifest["hook"]
    assert first.manifest["hook"] != second.manifest["hook"]
    assert first.manifest["opportunity_selection"]["selected"] != second.manifest["opportunity_selection"]["selected"]
    # boilerplate literals from the old hardcoded template must never appear
    for manifest in (first.manifest, second.manifest):
        assert manifest["opportunity_selection"]["candidates"] != ["silver boat", "lantern seed", "hedgehog rescue"]


def test_research_grounded_flag_reaches_opportunity_selection_basis(tmp_path):
    grounded = _BuiltProduction(tmp_path / "g", research_grounded=True)
    ungrounded = _BuiltProduction(tmp_path / "u", research_grounded=False)

    assert grounded.manifest["source_refs"]
    assert "research-grounded" in grounded.manifest["opportunity_selection"]["basis"]
    assert not ungrounded.manifest["source_refs"]
    assert "NO stored research" in ungrounded.manifest["opportunity_selection"]["basis"]


# Test D: each scene carries a real script_beat_id and narration_segment
# traceable back to the actual generated script -- not a positional-only,
# untraceable list.
def test_scene_plan_traces_to_script_and_beats(tmp_path):
    built = _BuiltProduction(tmp_path)
    scene_plan = built.manifest["scene_plan"]

    assert len(scene_plan) == len(built.manifest["scene_files"]) == len(built.manifest["story_beats"])
    seen_narration = set()
    for entry, beat in zip(scene_plan, built.manifest["story_beats"]):
        assert entry["script_beat_id"] == beat
        assert entry["scene_id"]
        assert entry["narration_segment"] and entry["narration_segment"] not in seen_narration
        seen_narration.add(entry["narration_segment"])
        assert entry["visual_description"]
        assert entry["duration_seconds"] > 0
    assert scene_plan[0]["script_beat_id"] == "HOOK"
    assert scene_plan[-1]["script_beat_id"] == "RESOLUTION"
    # hook/ending are directly traceable to the first/last scene's own
    # narration -- not independently invented text.
    assert built.manifest["hook"] == scene_plan[0]["narration_segment"]
    assert built.manifest["ending"] == scene_plan[-1]["narration_segment"]


# Test E: narration is generated from the SAME final script recorded in the
# manifest (not a separately/independently generated text).
def test_narration_generated_from_final_script(tmp_path):
    built = _BuiltProduction(tmp_path)
    audio = built.root / built.manifest["audio_file"]

    assert audio.is_file() and audio.stat().st_size > 1024
    assert built.manifest["script"] == "Leni ormanda parlayan bir fener tohumu buluyor ve onu dikkatle dikiyor."
    assert built.manifest["hook"] == built.manifest["scene_plan"][0]["narration_segment"]
    assert built.manifest["narration_seconds"] and built.manifest["narration_seconds"] > 0


def test_edge_tts_voice_follows_channel_language(tmp_path):
    swiss = _BuiltProduction(tmp_path / "ch", channel_market="Switzerland", channel_language="de-CH")
    assert "de-CH" in swiss.manifest["narration_provider"]
    assert swiss.manifest["target_country_language"] == "Switzerland / de-CH"


def test_real_audio_thumbnail_scenes_and_motion_are_required_assets(tmp_path):
    built = _BuiltProduction(tmp_path)
    root, data = built.root, built.manifest
    assert (root / data["audio_file"]).stat().st_size > 1024
    assert Path(data["thumbnail_path"]).stat().st_size > 10_000
    assert 4 <= len(data["scene_files"]) <= 6
    assert all((root / p).stat().st_size > 10_000 for p in data["scene_files"])
    assert len(data["character_motion"][0]["pose_files"]) == 3


# Test F: final render duration follows the real measured narration length,
# not a fixed caller-supplied default -- proves the "narration ends ~20s
# before a 60s video" defect (a long accidental silent tail) is now
# structurally prevented, not just caught after the fact.
def test_render_duration_follows_narration_not_fixed_default(tmp_path):
    built = _BuiltProduction(tmp_path)
    renderer = LocalVideoRenderer(output_root=tmp_path / "artifacts")
    import src.media.renderer as renderer_mod
    original = renderer_mod._find_production_package
    renderer_mod._find_production_package = lambda topic, asset_root="workspace/assets/media": Path(built.result.manifest_path)
    try:
        # duration_seconds=44 is passed to build(), but real edge-tts/SAPI
        # narration for this short script is well under 44s -- the final
        # artifact must track the REAL narration length, not sit padded out
        # to 44s of silence.
        render = renderer.render("Leni icin yeni bir macera videosu", built.manifest["script"], 44)
    finally:
        renderer_mod._find_production_package = original

    assert render.success, render.error
    artifact = Path(render.artifact_path)
    check = validate_media_goal_artifact(artifact, "Leni icin yeni bir macera videosu")
    assert check.gates["av_timing"]["passed"] is True
    narration_seconds = built.manifest["narration_seconds"]
    quality_manifest = json.loads(artifact.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert abs(quality_manifest["duration_seconds"] - narration_seconds) < 1.0
    assert quality_manifest["duration_seconds"] < 44
