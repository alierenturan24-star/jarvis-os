from pathlib import Path

from src.knowledge.knowledge_base import KnowledgeBase
from src.media.quality import check_media_plan_quality, validate_media_goal_artifact
from src.media.report_builder import MediaReportBuilder
from src.media.renderer import LocalVideoRenderer, find_ffmpeg, has_production_media_capability, find_goal_production_package
from src.media.learning import YouTubeLearningAgent
from src.media.production import GeneralProductionBuilder
from src.providers.router import ModelRouter
from src.utils.language_policy import TURKISH_OUTPUT_POLICY
from src.utils.llm_utils import is_llm_failure

# Sprint 39: JARVIS'in bu ortamda GERÇEKTEN sahip olduğu üretim araçlarının
# dürüst envanteri (bkz. Sprint 39 CAPABILITY AUDIT) -- LLM'e bağlam olarak
# verilir (uydurma/var olmayan bir araç önermesin diye) VE çıktıya
# deterministik olarak (LLM'in söylediklerine GÜVENMEDEN) eklenir, çünkü
# yerel modellerin bu tür ortam-durumu bilgisini tutarlı yansıtmadığı
# Sprint 38 canlı testinde GÖZLENDİ.
ENVIRONMENT_CAPABILITY_NOTE = (
    "Bu ortamda GERÇEKTEN kurulu olan: yerel Ollama (metin üretimi), Windows'un "
    "kendi System.Speech (SAPI) seslendirme motoru (yalnızca İngilizce sesler -- "
    "Zira/David -- Türkçe ses YOK). Bu ortamda kurulu OLMAYAN: FFmpeg, herhangi "
    "bir video/görsel render aracı, Türkçe metin-okuma (TTS) motoru, thumbnail/"
    "görsel üretim aracı. Bu yüzden gerçek bir ses/video dosyası ÜRETİLEMEDİ -- "
    "yalnızca bir ÜRETİM PLANI hazırlandı."
)

# Sprint: real-production quality-gate audit -- Phase 8 repair loop. Gates
# fixable by a plain regenerate-and-rerender (no content/topic change).
# research_grounding/narrative_coherence/visual_relevance/technical_render_validity
# are deliberately excluded: those require going back to the opportunity/script
# stage (a different topic/research input), which an automatic retry cannot do.
_REPAIRABLE_GATES = {"audio_completeness", "av_timing", "repetition", "shorts_structure"}
_MAX_REPAIR_ATTEMPTS = 2


class MediaManager:
    """Sprint 39: JARVIS'in araştırdığını GERÇEK bir üretim planına
    dönüştüren YouTube içerik departmanı yöneticisi.

    ``src.finance.manager.FinanceManager`` ile BİREBİR AYNI desen: tek bir
    LLM çağrısı (``ModelRouter`` üzerinden, ZATEN VAR OLAN provider seçim
    mantığı), sonucu diske kaydeden bir ReportBuilder. Yeni bir Mission/
    Strategy/Provider katmanı İCAT ETMEZ; ne bir video/ses dosyası
    ÜRETİR ne de herhangi bir yere YÜKLER."""

    def __init__(self) -> None:
        self.knowledge = KnowledgeBase()
        self.report_builder = MediaReportBuilder()
        self.router = ModelRouter()
        self.renderer = LocalVideoRenderer()
        self.last_artifact_path = ""
        self.last_production_record = None
        self.last_capability_gap: dict | None = None
        self.learning = YouTubeLearningAgent()
        self.production_builder = GeneralProductionBuilder()
        self.channel_id = "default"
        self.channel_market = "Germany"
        self.channel_language = "de-DE"
        self.learning.refresh_character_memory()

    def set_channel_scope(self, channel_id: str) -> None:
        from src.control_center.store import ControlCenterStore
        from src.media.channel_store import ChannelScopedStore
        base = ControlCenterStore()
        channel = base.snapshot()["channels"][channel_id]
        self.channel_id, self.channel_market, self.channel_language = channel_id, channel["market"], channel["language"]
        self.learning = YouTubeLearningAgent(ChannelScopedStore(base, channel_id))
        self.learning.refresh_character_memory()

    def plan(
        self,
        topic: str,
        duration_seconds: int = 60,
        preferred_provider: str | None = None,
        produce_artifact: bool = False,
        stage_sink: dict | None = None,
    ) -> str:
        topic = topic.strip()
        self.last_capability_gap = None
        if not topic:
            return "İçerik planı için konu belirtilmedi."

        # A runtime retry may resume an already validated production for the
        # exact same goal. This is not a new production/experiment and must
        # not append duplicate learning history.
        if produce_artifact:
            history = self.learning.store.snapshot().get("youtube_learning", {}).get("productions", [])
            prior = next((row for row in reversed(history)
                          if row.get("original_goal") == topic
                          and row.get("quality", {}).get("production_readiness") is True
                          and Path(row.get("artifact", {}).get("final_video_path", "")).is_file()), None)
            if prior:
                self.last_artifact_path = prior["artifact"]["final_video_path"]
                self.last_production_record = prior
                return ("Önceden tamamlanmış aynı production retry sırasında yeniden render edilmedi; "
                        f"validated artifact resume edildi.\nGERÇEK VIDEO ARTIFACT\n{self.last_artifact_path}")

        print(f"[Media] '{topic}' için {duration_seconds} sn'lik içerik planı hazırlanıyor...")

        # Sprint 39 bölüm 8: "önce mevcut bilgi/KnowledgeBase" -- yeni bir
        # araştırma İCAT ETMEZ, ZATEN VAR OLAN ``KnowledgeBase.find_research``
        # (Sprint 37/38) ile bu konuda daha önce bir araştırma var mı
        # kontrol edilir (varsa bağlam olarak kullanılır; "research"
        # departmanı bu mission'da AYRICA/paralel çalışıyor olabilir --
        # departmanlar bağımsız olduğu için o turun SONUCUNU burada
        # DOĞRUDAN okuyamayız, bkz. Sprint 39 mimari notu).
        prior = self.knowledge.find_research(topic)
        if prior is not None:
            context_block = (
                f"Bu konuda daha önce yapılmış bir araştırma özeti var "
                f"({prior.get('created_at', '?')}):\n{str(prior.get('summary', ''))[:800]}\n"
            )
        else:
            context_block = (
                "Bu konuda önceden kayıtlı bir araştırma bulunamadı -- kendi genel "
                "bilgine dayan, uydurma istatistik/rakam/tarih verme, emin değilsen açıkça belirt.\n"
            )

        capability_note = (
            "Bu ortamda GERÇEKTEN kurulu olan: yerel Ollama, workspace-local "
            "FFmpeg/ffprobe, deterministic scene-card composition ve Windows "
            "System.Speech TTS. Yayınlama capability'si kullanılmaz."
            if find_ffmpeg()
            else "FFmpeg/video encoder bulunamadı; gerçek MP4 üretimi BLOCKED."
        )
        learning_plan = self.learning.production_plan(topic)

        prompt = f"""
Sen JARVIS YouTube İçerik Üretim Departmanı yapımcısısın.

Konu: {topic}
Hedef süre: {duration_seconds} saniye (YouTube Shorts)

{context_block}

Ortam durumu (dikkate al, plan bunu yansıtsın):
{capability_note}

Kalıcı production memory (exact script/scene/config tekrar etme; bounded variation kullan):
{learning_plan}

FORMAT PATERNLERİ (öğrenilmiş; KOPYALAMA DEĞİL):
Yukarıdaki "format_patterns" yalnızca SOYUT format kategorileridir (hook yapısı, tempo,
merak açığı, başlık yapısı, görsel değişim sıklığı). Belirli bir rakibin BİREBİR
script'ini, başlığını, görsellerini veya telif içeriğini KOPYALAMA -- yalnızca hangi
FORMAT özelliklerinin işe yaradığını öğren ve konuya özgü, özgün bir açı üret.

{TURKISH_OUTPUT_POLICY}

Görev: Aşağıdaki 9 başlığın HEPSİNİ, TAM OLARAK bu isimlerle ve bu sırayla üret:

SENARYO
({duration_seconds} saniyelik doğal konuşma dilinde anlatım metni.)

SAHNELER
(Metni 4-6 sahneye böl. Her satır: "Sahne N (~X sn): Anlatım: ... | Görsel: ... | Ekran yazısı: ...")

SESLENDİRME PLANI
(Yukarıdaki ortam durumuna göre GERÇEKÇİ bir öneri yap -- var olmayan bir aracı varmış gibi gösterme.)

GÖRSEL/VİDEO PLANI
(Her sahne için görsel kaynağı önerisi -- yukarıdaki ortam durumuna göre GERÇEKÇİ ol.)

ALTYAZI PLANI
(Sahne zamanlamasına dayalı kısa altyazı satırları.)

THUMBNAIL FİKRİ
(Kısa, çarpıcı bir thumbnail açıklaması -- metin olarak, gerçek görsel ÜRETİLMEYECEK.)

BAŞLIK
(60 karakteri geçmeyen bir YouTube Shorts başlığı.)

AÇIKLAMA
(2-3 cümlelik video açıklaması.)

ETİKETLER
(5-8 etiket, virgülle ayrılmış.)

Kurallar:
- Uydurma istatistik/rakam/tarih kullanma, emin değilsen belirt.
- Kesin yatırım tavsiyesi verme.
- Var olmayan bir aracı kurulu/kullanılabilirmiş gibi anlatma.
"""

        if stage_sink is not None:
            stage_sink["last_stage"] = "planning"

        provider_name = self._resolve_provider(preferred_provider)

        # Sprint 40: Research'ün (Summarizer) zaten kullandığı
        # ``route_and_generate``'e geçildi -- otomatik Ollama fallback'i
        # ve çağrı geçmişi kaydını (bkz. src.providers.execution_history)
        # ÜCRETSİZ kazanır, yeni bir fallback mantığı İCAT EDİLMEDİ.
        route_result = self.router.manager.route_and_generate(
            prompt=prompt, task_type="planning", preferred_provider=provider_name,
        )
        plan_text = route_result.output

        if is_llm_failure(plan_text) and produce_artifact:
            plan_text = self._deterministic_fallback_plan(topic, duration_seconds)
            plan_text += "\n\nPROVIDER RECOVERY\nYerel deterministik üretim planı kullanıldı."

        if is_llm_failure(plan_text):
            return (
                "İçerik planı üretilemedi (model yanıt vermedi).\n"
                f"Hata: {plan_text}\n\n"
                "Gerçek bir plan uydurulmadı -- bu, boş/başarısız bir sonuçtur."
            )

        if route_result.fallback_used:
            plan_text += (
                f"\n\n(Not: birincil sağlayıcı ({route_result.chosen_provider}) başarısız oldu, "
                f"otomatik olarak {route_result.provider_used}'a geçildi.)"
            )

        quality = check_media_plan_quality(plan_text)
        report_path = self.report_builder.save(
            topic=topic,
            duration_seconds=duration_seconds,
            plan_text=plan_text,
            quality_summary=quality.summary,
        )

        artifact_block = ""
        if produce_artifact:
            # Sprint: real-production quality-gate audit -- ``prior`` (above) is
            # the SAME KnowledgeBase.find_research() lookup already used for LLM
            # prompt context; reused here (no second research system) as the
            # truthful "was this topic actually research-grounded" signal recorded
            # into the manifest and enforced by the quality gate.
            research_evidence_ref = (
                {"created_at": prior.get("created_at"), "source_count": prior.get("source_count")}
                if prior is not None else None
            )

            def _build_production():
                if stage_sink is not None:
                    stage_sink["last_stage"] = "production_build"
                return self.production_builder.build(
                    goal=topic, plan_text=plan_text,
                    memory=self.learning.store.snapshot().get("youtube_learning", {}),
                    duration_seconds=duration_seconds,
                    channel_id=self.channel_id,
                    channel_market=self.channel_market,
                    channel_language=self.channel_language,
                    research_grounded=prior is not None,
                    research_evidence_ref=research_evidence_ref,
                    stage_sink=stage_sink,
                )

            if find_goal_production_package(topic) is None:
                build = _build_production()
                if not build.success:
                    self.last_artifact_path = ""
                    if build.missing_capabilities:
                        self.last_capability_gap = {
                            "missing_capabilities": list(build.missing_capabilities),
                            "available_capabilities": list(build.available_capabilities),
                            "required_capabilities": list(build.required_capabilities),
                            "requested_content_type": "youtube_short",
                            "channel_id": self.channel_id,
                            "topic": topic,
                            "reason": build.error,
                            "report_path": str(report_path),
                        }
                    return (
                        f"{plan_text}\n\nVIDEO RENDER: BLOCKED\n{build.error}\n"
                        "Yeni artifact üretilmedi; hiçbir video yayınlanmadı."
                    )

            artifact_block = self._produce_with_bounded_repair(
                topic, plan_text, duration_seconds, _build_production, stage_sink=stage_sink,
            )

        production_note = (
            "Gerçek video taslağı yerel olarak üretildi; YouTube'a yüklenmedi."
            if self.last_artifact_path else
            "Gerçek video artifact üretilemedi; hiçbir şey YouTube'a yüklenmedi."
        )
        return (
            f"YouTube içerik planı tamamlandı (hedef: {duration_seconds} sn).\n\n"
            f"{plan_text}\n\n"
            f"KALİTE KONTROL\n{quality.summary}\n\n"
            f"ORTAM DURUMU\n{capability_note}\n\n{production_note}\n\n"
            f"Rapor kaydedildi:\n{report_path}{artifact_block}"
        )

    def _produce_with_bounded_repair(
        self, topic: str, plan_text: str, duration_seconds: int, rebuild, *, stage_sink: dict | None = None,
    ) -> str:
        """Render, self-check against the real quality gates, and bounded-retry
        the *repairable* failures (Sprint: real-production quality-gate audit,
        Phase 8 -- "repair loop"). A repairable gate failure (audio/timing/
        motion-repetition/Shorts-format) triggers a full regenerate-and-rerender
        (there is no isolated per-stage regeneration API yet, so the retry unit
        is coarse: a whole new build+render, not a single patched scene) up to
        ``_MAX_REPAIR_ATTEMPTS`` times. A non-repairable failure (research
        grounding, narrative coherence, visual relevance -- these require going
        back to the opportunity/script stage, not re-rendering the same content)
        stops immediately and reports truthfully. Either way, this never creates
        a ``youtube_publish`` approval itself -- that only happens downstream in
        ``workforce.quality_review``, which independently re-runs the same
        ``validate_media_goal_artifact`` gates against the artifact this method
        returns.
        """
        attempts = 0
        repair_log: list[str] = []
        while True:
            if stage_sink is not None:
                stage_sink["last_stage"] = "render"
            render = self.renderer.render(topic, plan_text, duration_seconds, stage_sink=stage_sink)
            if not render.success:
                self.last_artifact_path = ""
                return f"\n\nVIDEO RENDER: BLOCKED\n{render.error}"

            if stage_sink is not None:
                stage_sink["last_stage"] = "quality_check"
            check = validate_media_goal_artifact(Path(render.artifact_path), topic)
            failing = [name for name in check.critical_failures if name != "publication_readiness"]
            self.last_artifact_path = render.artifact_path
            self.last_production_record = self.learning.record(
                goal=topic, artifact_path=render.artifact_path, plan_text=plan_text,
            )
            if not failing:
                block = f"\n\nGERÇEK VIDEO ARTIFACT\n{render.artifact_path}"
                if repair_log:
                    block += "\n\nREPAIR LOG\n" + "\n".join(repair_log)
                return block

            repairable = [name for name in failing if name in _REPAIRABLE_GATES]
            non_repairable = [name for name in failing if name not in _REPAIRABLE_GATES]
            if non_repairable or attempts >= _MAX_REPAIR_ATTEMPTS:
                reason = (
                    f"non-repairable quality gate failure(s): {', '.join(non_repairable)}"
                    if non_repairable else
                    f"repair attempts exhausted ({_MAX_REPAIR_ATTEMPTS}) for: {', '.join(repairable)}"
                )
                block = f"\n\nQUALITY: NOT READY FOR PUBLICATION\n{reason}"
                if repair_log:
                    block += "\n\nREPAIR LOG\n" + "\n".join(repair_log)
                return block

            attempts += 1
            repair_log.append(f"attempt {attempts}: regenerated due to {', '.join(repairable)}")
            rebuilt = rebuild()
            if not rebuilt.success:
                self.last_artifact_path = ""
                if rebuilt.missing_capabilities:
                    self.last_capability_gap = {
                        "missing_capabilities": list(rebuilt.missing_capabilities),
                        "available_capabilities": list(rebuilt.available_capabilities),
                        "required_capabilities": list(rebuilt.required_capabilities),
                        "requested_content_type": "youtube_short",
                        "channel_id": self.channel_id,
                        "topic": topic,
                        "reason": rebuilt.error,
                    }
                return f"\n\nVIDEO RENDER: BLOCKED\n{rebuilt.error}"

    @staticmethod
    def _deterministic_fallback_plan(topic: str, duration_seconds: int) -> str:
        scene_seconds = max(1, duration_seconds // 4)
        return f"""SENARYO
{topic}. Bu yerel taslak yalnız verilen hedefi görselleştirir; doğrulanmamış olgu veya istatistik içermez.

SAHNELER
Sahne 1 (~{scene_seconds} sn): Anlatım: Konuya giriş | Görsel: Renkli gökyüzü ve çizgi karakter | Ekran yazısı: Merhaba
Sahne 2 (~{scene_seconds} sn): Anlatım: Karakter keşfe çıkar | Görsel: Hareket eden çizgi karakter | Ekran yazısı: Keşfet
Sahne 3 (~{scene_seconds} sn): Anlatım: Dostluk ve merak | Görsel: Renkli sahne | Ekran yazısı: Birlikte
Sahne 4 (~{scene_seconds} sn): Anlatım: Kapanış | Görsel: Mutlu karakter | Ekran yazısı: Görüşürüz

SESLENDİRME PLANI
Windows System.Speech denenir; uygun ses yoksa sessiz audio track dürüstçe kullanılır.

GÖRSEL/VİDEO PLANI
Yerel deterministic scene-card görselleri FFmpeg ile birleştirilir.

ALTYAZI PLANI
Verilen hedef metni zamanlanmış SRT taslağına yazılır.

THUMBNAIL FİKRİ
Renkli gökyüzünde dost canlısı çizgi karakter.

BAŞLIK
Çocuklar İçin Renkli Bir Keşif

AÇIKLAMA
Yerel araçlarla oluşturulan yayınlanmamış video taslağı.

ETİKETLER
çocuk, çizgi film, keşif, dostluk"""

    def _resolve_provider(self, preferred_provider: str | None) -> str:
        """Sprint 39: ``FinanceManager._resolve_provider`` ile BİREBİR AYNI
        desen -- AI Strategy Engine'in seçtiği provider'ı yalnızca GERÇEKTEN
        kullanılabilirse kullanır, aksi halde "ollama" varsayılanına düşer."""

        if not preferred_provider:
            return "ollama"

        candidate = self.router.manager.get(preferred_provider)
        if candidate is not None and candidate.is_available():
            return preferred_provider

        return "ollama"
