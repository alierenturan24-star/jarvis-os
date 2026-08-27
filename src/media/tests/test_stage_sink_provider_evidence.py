from __future__ import annotations

from src.config.settings import Settings
from src.media.capability_model import MediaGenerationResult, TEXT_TO_IMAGE
from src.media.production import GeneralProductionBuilder
from src.providers.nvidia_provider import NvidiaMediaProvider

# Mission repair (real Swiss-Insider-Shorts follow-up evidence, item 1): a
# real timeout only reported "text_to_image_scene_1_of_4" -- not WHICH
# media provider/model was actually being attempted. ``stage_sink`` is now
# written with the provider/model identity immediately BEFORE the blocking
# network call (see ``GeneralProductionBuilder._generate_scene_image``), so
# it survives even if the call itself never returns.

_PLAN_TEXT = """SENARYO
Isvicre'de hibrit calisma modeli hizla yayiliyor ve verimliligi artiriyor.

SAHNELER
Sahne 1 (~8 sn): Anlatım: Isvicre'de yeni bir is trendi | Görsel: Isvicre sehir manzarasi, ofis binalari | Ekran yazısı: Trend basliyor
Sahne 2 (~8 sn): Anlatım: Ofis ve ev arasinda denge | Görsel: Evden calisan kisi | Ekran yazısı: Denge
Sahne 3 (~8 sn): Anlatım: Verimlilik artiyor | Görsel: Yukselen grafik | Ekran yazısı: Verimlilik
Sahne 4 (~8 sn): Anlatım: Gelecek burada | Görsel: Mutlu calisanlar | Ekran yazısı: Gelecek

SESLENDİRME PLANI
Windows System.Speech kullanilacak.

GÖRSEL/VİDEO PLANI
Dinamik provider ile uretilecek.

ALTYAZI PLANI
Sahne zamanlamasina gore.

THUMBNAIL FİKRİ
Yukselen grafik ve mutlu calisanlar

BAŞLIK
Hibrit Calisma Modeli Yukseliyor

AÇIKLAMA
Isvicre'de hibrit calisma modelinin yukselisini anlatan kisa video.

ETİKETLER
isvicre, hibrit, calisma, verimlilik
"""


def test_stage_sink_captures_provider_and_model_before_the_blocking_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(Settings, "LTX_API_KEY", "")

    def _always_fails(self, prompt, **kwargs):
        return MediaGenerationResult(
            False, "nvidia", Settings.NVIDIA_IMAGE_MODEL, TEXT_TO_IMAGE, error="simulated timeout",
        )

    monkeypatch.setattr(NvidiaMediaProvider, "generate_image", _always_fails)

    builder = GeneralProductionBuilder(source_root=tmp_path / "sources", output_root=tmp_path / "generated")
    sink: dict = {}
    result = builder.build(
        goal="test", plan_text=_PLAN_TEXT, memory={}, duration_seconds=32, stage_sink=sink,
    )

    assert result.success is False
    assert sink["last_stage"].startswith("text_to_image_scene_1_via_nvidia/")
    assert Settings.NVIDIA_IMAGE_MODEL in sink["last_stage"]
