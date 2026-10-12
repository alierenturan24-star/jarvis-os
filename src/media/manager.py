import re
from datetime import datetime
from pathlib import Path

from src.knowledge.knowledge_base import KnowledgeBase
from src.media.quality import check_media_plan_quality, validate_media_goal_artifact
from src.media.report_builder import MediaReportBuilder
from src.media.renderer import LocalVideoRenderer, find_ffmpeg, has_production_media_capability, find_goal_production_package
from src.media.learning import YouTubeLearningAgent
from src.media.production import GeneralProductionBuilder, parse_plan_text
from src.providers.router import ModelRouter
from src.research.manager import topic_wants_current_information
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
# Public (not module-private) name: round 4 repair -- department_orchestrator
# needs the REAL repair-attempt count to size media's outer department
# timeout budget from this module's own bounded worst-case, the same
# pattern already used for "research"/"coding" (see
# ``department_orchestrator.MEDIA_DEPARTMENT_TASK_TIMEOUT_SECONDS``).
MAX_REPAIR_ATTEMPTS = 2

_SPORTS_DOMAIN_SIGNALS = (
    "futbol", "football", "calcio", "maç", "match", "gol", "stadyum",
    "stadium", "stadio", "taraftar", "supporters",
)
_NEWS_MEDIA_DOMAIN_SIGNALS = (
    "corriere", "gazete", "giornale", "newspaper", "editör", "editor",
    "redazione", "newsroom", "journalist", "gazeteci", "direzione del",
)


def _research_evidence_text(opportunity: dict | None) -> str:
    if not opportunity:
        return ""
    parts = [str(opportunity.get("selected_topic") or "")]
    for item in opportunity.get("supporting_evidence") or ():
        if isinstance(item, dict):
            parts.extend((
                str(item.get("title") or ""), str(item.get("summary") or ""),
                str(item.get("url") or ""), str(item.get("source_identity") or ""),
                str(item.get("publisher") or ""),
            ))
    return "\n".join(part for part in parts if part.strip())


def _research_domain_drift(plan_text: str, opportunity: dict | None) -> str | None:
    """Catch an observed cross-domain hallucination before rendering.

    This deliberately uses only strong domain words. Generic words such as
    ``team/squadra`` are excluded because editorial and company teams use
    them too.  The gate therefore catches a football story invented from a
    newspaper-management article without rejecting ordinary wording.
    """
    evidence = _research_evidence_text(opportunity).casefold()
    plan = (plan_text or "").casefold()
    evidence_sports = sum(signal in evidence for signal in _SPORTS_DOMAIN_SIGNALS)
    evidence_news = sum(signal in evidence for signal in _NEWS_MEDIA_DOMAIN_SIGNALS)
    plan_sports = sum(signal in plan for signal in _SPORTS_DOMAIN_SIGNALS)
    if evidence_news >= 1 and evidence_sports == 0 and plan_sports >= 2:
        return (
            "Kaynak bir gazete/medya kariyerini anlatırken plan desteklenmeyen "
            "bir futbol hikâyesi üretti."
        )
    return None


def _unsupported_research_claims(plan_text: str, opportunity: dict | None) -> tuple[str, ...]:
    """Reject concrete claims the selected source evidence never makes.

    This is intentionally a narrow deterministic safety net for observed
    news/health hallucinations.  It does not try to fact-check the world; it
    only compares high-risk claims in the generated plan with the already
    collected titles/snippets that are the production's sole factual basis.
    """
    if not opportunity:
        return ()
    plan = (plan_text or "").casefold()
    evidence = _research_evidence_text(opportunity).casefold()
    claim_families = (
        ("kanser/kötü hücre", ("kanser", "kötü hücre", "kotu hucre"),
         ("kanser", "kötü hücre", "kotu hucre", "cancer", "malign")),
        ("sağlık durumunun stabil olduğu", ("durumu stabil", "sağlık durumu stabil"),
         ("durumu stabil", "sağlık durumu stabil", "stable condition", "état stable", "stabile")),
        ("doktorların başarı beklentisi", ("doktorlar operasyonun başarılı", "başarıyla geçmesi bekleniyor"),
         ("doktorlar operasyonun başarılı", "başarıyla geçmesi bekleniyor", "expected to be successful")),
        ("hayat kurtardığı", ("hayat kurtardı", "hayat kurtarır"),
         ("hayat kurtardı", "hayat kurtarır", "saved his life", "rettete sein leben")),
        ("dünya çapında dua/tepki", ("tüm dünyadan dualar", "dünyadan dualar"),
         ("tüm dünyadan dualar", "dünyadan dualar", "prayers from around the world")),
        ("dünya çapında yankı/tepki", ("tüm dünyada yankı", "dünya çapında yankı"),
         ("tüm dünyada yankı", "dünya çapında yankı", "worldwide reaction", "around the world")),
        ("durumun kontrol altında olduğu", ("durum kontrol altında", "durumun kontrol altında"),
         ("durum kontrol altında", "durumun kontrol altında", "under control", "sous contrôle")),
        ("yetkililerin açıklaması", ("yetkililer belirtiyor", "yetkililer bildirdi", "yetkililer açıkladı"),
         ("yetkililer", "authorities", "officials", "behörden", "autorités")),
        ("ameliyatın riski önleme gerekçesi", (
            "risk oluşmasını engellemek", "risk olusmasini engellemek",
            "risk oluşturmasını önlemek", "risk olusturmasini onlemek",
        ), ("risk oluşmasını engellemek", "risk oluşturmasını önlemek", "prevent risk", "risiko verhindern")),
    )
    unsupported = [
        label for label, plan_cues, evidence_cues in claim_families
        if any(cue in plan for cue in plan_cues)
        and not any(cue in evidence for cue in evidence_cues)
    ]
    if (
        re.search(r"yetkililer[^.!?]{0,90}(?:belirtiyor|bildirdi|açıkladı)", plan)
        and not any(cue in evidence for cue in ("yetkililer", "authorities", "officials", "behörden", "autorités"))
        and "yetkililerin açıklaması" not in unsupported
    ):
        unsupported.append("yetkililerin açıklaması")
    # A Swiss publisher is not evidence that an international event happened
    # "from Switzerland".  Keep target-market framing separate from location.
    if any(cue in plan for cue in ("sviçre'den", "svicre'den", "isviçreden", "isvicreden")) and not any(
        cue in evidence for cue in ("isviçre", "schweiz", "suisse", "svizzera", "switzerland")
    ):
        unsupported.append("olayın İsviçre kaynaklı olduğu")
    # In medical copy, a nodule/knot must not silently be upgraded into a
    # mass/tumour when the evidence only says nodule.  The ordinary audience
    # meaning of "kitle" is deliberately excluded by requiring lung/health
    # context in the generated plan.
    if (
        "kitle" in plan
        and any(cue in plan for cue in ("akciğer", "akciger", "nodül", "nodul", "ameliyat"))
        and not any(cue in evidence for cue in ("kitle", "mass", "tumor", "tümör", "tumour"))
    ):
        unsupported.append("nodülün kitle/tümör diye büyütülmesi")

    # Naming a publisher as a verifier is a concrete attribution, not style.
    # Check the outlets observed in the live failure; absent outlets must be
    # removed by the correction pass before rendering.
    for outlet, evidence_cues in {
        "SRF": ("srf.ch", " srf ", "source_identity: srf"),
        "RTS": ("rts.ch", " rts ", "source_identity: rts"),
        "RSI": ("rsi.ch", " rsi ", "source_identity: rsi"),
        "NZZ": ("nzz.ch", " nzz ", "neue zürcher zeitung"),
        "SWI": ("swissinfo.ch", " swissinfo ", " swi "),
    }.items():
        if re.search(rf"(?<![a-z]){outlet.casefold()}(?![a-z])", plan) and not any(
            cue in f" {evidence} " for cue in evidence_cues
        ):
            unsupported.append(f"kanıtta bulunmayan {outlet} kaynak atfı")
    return tuple(unsupported)


def _license_evidence_lines(record: dict | None) -> list[str]:
    rows = (((record or {}).get("artifact") or {}).get("scene_provenance") or [])
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("success") is not True:
            continue
        evidence = row.get("quality_evidence") if isinstance(row.get("quality_evidence"), dict) else {}
        license_name = str(evidence.get("license") or "belirtilmedi")
        source = str(evidence.get("source_url") or "yerel özgün üretim")
        lines.append(
            f"- {row.get('scene_id')}: {row.get('provider')} · {license_name} · {source}"
        )
    return lines


def _looks_predominantly_english(text: str) -> bool:
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]+", text or "")
    if not words:
        return False
    english = {"the", "and", "with", "this", "that", "how", "from", "every", "into", "use", "traditional"}
    turkish = {"ve", "ile", "bu", "nasıl", "için", "bir", "olarak", "güncel", "görsel", "anlatım"}
    lowered = [word.casefold() for word in words]
    return sum(word in english for word in lowered) >= 5 and sum(word in turkish for word in lowered) < 3


def _normalize_plan_headings(text: str) -> str:
    """Accept common provider spelling variants of required Turkish headings."""
    normalized = text or ""
    replacements = {
        "GÖRSEL/VIDEO PLANI": "GÖRSEL/VİDEO PLANI",
        "GORSEL/VIDEO PLANI": "GÖRSEL/VİDEO PLANI",
        "GÖRSEL / VİDEO PLANI": "GÖRSEL/VİDEO PLANI",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


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
        from src.media.channel_store import ChannelScopedStore, normalize_youtube_learning
        base = ControlCenterStore()
        channel = (base.snapshot().get("channels") or {}).get(channel_id)
        if not isinstance(channel, dict):
            raise KeyError(f"YouTube channel state missing for {channel_id!r}")
        normalized = normalize_youtube_learning(channel.get("youtube_learning"))
        if channel.get("youtube_learning") != normalized:
            base.update(lambda state: state["channels"][channel_id].update(youtube_learning=normalized))
            channel["youtube_learning"] = normalized
        self.channel_id = channel_id
        self.channel_market = str(channel.get("market") or "Switzerland")
        language = str(channel.get("language") or "tr-TR")
        self.channel_language = "tr-TR" if language == "CHANNEL_CONFIG" else language
        self.learning = YouTubeLearningAgent(ChannelScopedStore(base, channel_id))
        self.learning.refresh_character_memory()

    def plan(
        self,
        topic: str,
        duration_seconds: int = 60,
        preferred_provider: str | None = None,
        produce_artifact: bool = False,
        stage_sink: dict | None = None,
        research_opportunity: dict | None = None,
        standing_permission: bool = False,
        free_only: bool = True,
        request_text: str | None = None,
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
                          and not _unsupported_research_claims(
                              " ".join((
                                  str((row.get("creative") or {}).get("script") or ""),
                                  str((row.get("titles") or {}).get("selected") or ""),
                                  str((row.get("titles") or {}).get("description") or ""),
                              )), research_opportunity,
                          )
                          and (not free_only or _license_evidence_lines(row))
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
        full_request = (request_text or topic).strip()
        if (
            topic_wants_current_information(full_request)
            and research_opportunity is None
            and prior is None
        ):
            if stage_sink is not None:
                stage_sink["last_stage"] = "research_gap_stop"
            return (
                "RESEARCH_GAP\nGüncel/trend bilgisi istendi ancak doğrulanmış araştırma kanıtı yok. "
                "Eski bir yılı veya uydurma bir trendi güncelmiş gibi sunmamak için içerik planı hazırlanmadı."
            )
        # Round 5 repair (real live-mission evidence): an explicitly-passed,
        # ALREADY-SELECTED research opportunity (see
        # MediaAgent.execute()/src.research.opportunity) is authoritative
        # over the ``prior`` lookup above. That lookup is a best-effort
        # convenience for callers with no explicit research dependency --
        # a real live mission proved it can silently miss (media's own
        # re-derived topic string was a DIFFERENT string than research's
        # actual query, so the KnowledgeBase containment-match never hit),
        # which is exactly why the explicit data dependency exists now.
        if research_opportunity is not None:
            evidence_rows = []
            for ref in research_opportunity.get("supporting_evidence") or []:
                evidence_rows.append(
                    "- Başlık: " + str(ref.get("title") or "Başlıksız kaynak")[:220]
                    + "\n  Kaynak özeti: " + str(ref.get("summary") or "Özet yok")[:1200]
                    + "\n  Yayın tarihi: " + str(ref.get("published_at") or "belirtilmedi")
                    + "\n  URL: " + str(ref.get("url") or "")
                )
            evidence_context = (
                "\nDoğrulanmış haber kanıtı (olgular için yalnızca bunu esas al):\n"
                + "\n".join(evidence_rows[:5]) + "\n"
                if evidence_rows else ""
            )
            format_rows = []
            for ref in research_opportunity.get("format_references") or []:
                format_rows.append(
                    "- " + str(ref.get("title") or "Başlıksız video")[:180]
                    + f" | yayıncı: {ref.get('publisher') or ref.get('provider') or 'belirtilmedi'}"
                    + f" | süre: {ref.get('duration') or 'belirtilmedi'}"
                    + f" | etkileşim: {ref.get('statistics') or {}}"
                    + f" | URL: {ref.get('url') or ''}"
                )
            format_context = (
                "\nFormat referansları (YALNIZ soyut hook/tempo/hikâye/başlık kalıbı için; "
                "başlık, metin, kapak, ses ve görüntü kopyalanamaz):\n"
                + "\n".join(format_rows[:3]) + "\n"
                if format_rows else ""
            )
            context_block = (
                "Araştırma tarafından SEÇİLMİŞ, güncel bir içerik fırsatı VAR "
                f"(konum/pazar: {research_opportunity.get('location_or_market', '')}, "
                f"güncellik: {research_opportunity.get('why_current', '')}):\n"
                f"{str(research_opportunity.get('selected_topic', ''))[:800]}\n"
                f"{evidence_context}"
                f"{format_context}"
            )
        elif prior is not None:
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
            "FFmpeg/ffprobe, anahtarsız ve lisans kanıtlı Wikimedia Commons görsel/video araması, "
            "yerel özgün kapak/altyazı/müzik kompozisyonu ve Windows System.Speech TTS. "
            "Onay yokken ücretli görsel sağlayıcısı kullanılmaz; yayınlama capability'si kullanılmaz."
            if find_ffmpeg()
            else "FFmpeg/video encoder bulunamadı; gerçek MP4 üretimi BLOCKED."
        )
        learning_plan = self.learning.production_plan(topic)
        requested_turkish = any(
            cue in full_request.casefold() for cue in ("türkçe", "turkce", "türkçe anlatım", "türkçe ses")
        )
        production_language = "tr-TR" if requested_turkish else self.channel_language

        request_block = (
            f"Kullanıcının tam isteği: {full_request}\n"
            if full_request and full_request != topic else ""
        )
        prompt = f"""
Sen JARVIS YouTube İçerik Üretim Departmanı yapımcısısın.

Konu: {topic}
Hedef süre: {duration_seconds} saniye (YouTube Shorts)
Bugünün sistem tarihi: {datetime.now().date().isoformat()}
{request_block}
ZORUNLU ÇIKTI DİLİ: {"Türkçe" if requested_turkish else production_language}.
Senaryo, anlatım, ekran yazıları, altyazı, başlık ve açıklamanın tamamı bu dilde olmalıdır.

{context_block}

Ortam durumu (dikkate al, plan bunu yansıtsın):
{capability_note}

Kalıcı production memory (exact script/scene/config tekrar etme; bounded variation kullan):
{learning_plan}

FORMAT PATERNLERİ (öğrenilmiş; KOPYALAMA DEĞİL):
Yukarıdaki "format_patterns" yalnızca SOYUT format kategorileridir (hook yapısı, tempo,
merak açığı, başlık yapısı, görsel değişim sıklığı). Belirli bir rakibin BİREBİR
script'ini, başlığını, kapağını veya izinsiz video dosyasını KOPYALAMA. Yalnızca
soyut hikâye/tempo yapısını öğren. Görsel ham madde olarak sadece manifestte
kaynak+lisans kanıtı tutulabilen Public Domain, CC0 veya CC BY Commons
klipleri/görselleri kullanılabilir; bunları yeni anlatım, kurgu, altyazı, özgün
kapak ve özgün müzikle dönüştür.

{TURKISH_OUTPUT_POLICY}

Görev: Aşağıdaki 9 başlığın HEPSİNİ, TAM OLARAK bu isimlerle ve bu sırayla üret:

Kullanıcının tam isteği birden fazla video fikri/başlığı istiyorsa, önce
"VİDEO FİKİRLERİ VE BAŞLIKLARI" bölümü altında istenen sayıda özgün seçenek ver;
ardından aşağıdaki 9 bölümde en güçlü seçenek için uygulanabilir üretim planını yaz.

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
(Kısa, çarpıcı kapak metni ve kompozisyonu; sistem bunu seçilen lisanslı/özgün kare üzerinde yerelde tasarlayacak.)

BAŞLIK
(60 karakteri geçmeyen bir YouTube Shorts başlığı.)

AÇIKLAMA
(2-3 cümlelik video açıklaması.)

ETİKETLER
(5-8 etiket, virgülle ayrılmış.)

Kurallar:
- Uydurma istatistik/rakam/tarih kullanma, emin değilsen belirt.
- Kaynak özetinde bulunmayan meslek, takım, kişi rolü veya olay türü UYDURMA.
- Çok anlamlı bir başlık kelimesinden çıkarım yapma; kaynak özetindeki somut olguları esas al.
- Güncel/trend iddialarını yalnızca yukarıdaki araştırma bağlamı destekliyorsa yaz;
  eski bir yılı güncelmiş gibi sunma.
- Kesin yatırım tavsiyesi verme.
- Var olmayan bir aracı kurulu/kullanılabilirmiş gibi anlatma.
- Başka bir üreticinin videosunu, kapağını veya telifli müziğini kopyalama/yeniden yükleme.
- Görsel planında doğrulanabilir Public Domain, CC0 veya CC BY kaynakları tercih et.
"""

        if stage_sink is not None:
            stage_sink["last_stage"] = "planning"

        provider_name = self._resolve_provider(preferred_provider)
        # The desktop installer already detects Claude Code. When it is
        # installed/authenticated, use the user's subscription-backed local
        # CLI worker for media planning before Ollama/AIML. A quota/login
        # failure still falls through the existing bounded provider chain.
        claude_code = self.router.manager.get("claude_code")
        if claude_code is not None and claude_code.is_available():
            provider_name = "claude_code"

        # Sprint 40: Research'ün (Summarizer) zaten kullandığı
        # ``route_and_generate``'e geçildi -- otomatik Ollama fallback'i
        # ve çağrı geçmişi kaydını (bkz. src.providers.execution_history)
        # ÜCRETSİZ kazanır, yeni bir fallback mantığı İCAT EDİLMEDİ.
        route_result = self.router.manager.route_and_generate(
            prompt=prompt, task_type="planning", preferred_provider=provider_name,
            allowed_cost_classes=("free", "plan") if free_only else None,
        )
        plan_text = route_result.output

        if requested_turkish and not is_llm_failure(plan_text) and _looks_predominantly_english(plan_text):
            correction = self.router.manager.route_and_generate(
                prompt=(
                    "Aşağıdaki üretim planı yanlışlıkla İngilizce yazılmış. Hiçbir olgu eklemeden, "
                    "aynı dokuz bölüm başlığını ve sahne sürelerini koruyarak planın tamamını Türkçe "
                    "yeniden yaz. Yalnızca düzeltilmiş planı döndür.\n\n" + plan_text
                ),
                task_type="planning", preferred_provider=route_result.provider_used,
                allowed_cost_classes=("free", "plan") if free_only else None,
            )
            if correction.success and not is_llm_failure(correction.output):
                plan_text = correction.output
                route_result = correction
            if _looks_predominantly_english(plan_text):
                return (
                    "VIDEO RENDER: BLOCKED_LANGUAGE\n"
                    "Kullanıcı Türkçe istedi ancak sağlayıcı Türkçe üretim planı veremedi. "
                    "Yanlış dilde video oluşturulmadı; hiçbir şey yayınlanmadı."
                )

        if is_llm_failure(plan_text) and produce_artifact:
            plan_text = self._deterministic_fallback_plan(topic, duration_seconds)
            plan_text += "\n\nPROVIDER RECOVERY\nYerel deterministik üretim planı kullanıldı."

        if is_llm_failure(plan_text):
            return (
                "İçerik planı üretilemedi (model yanıt vermedi).\n"
                f"Hata: {plan_text}\n\n"
                "Gerçek bir plan uydurulmadı -- bu, boş/başarısız bir sonuçtur."
            )

        plan_text = _normalize_plan_headings(plan_text)

        drift_reason = _research_domain_drift(plan_text, research_opportunity)
        if drift_reason:
            correction = self.router.manager.route_and_generate(
                prompt=(
                    "Aşağıdaki video planı doğrulanmış haber kaynağının alanından sapmış. "
                    "Hiçbir yeni olgu eklemeden, dokuz bölüm başlığını ve istenen dili koruyarak "
                    "planı yalnızca aşağıdaki kaynak kanıtına göre düzelt. Çok anlamlı başlık "
                    "kelimelerinden meslek veya olay türü çıkarma.\n\n"
                    "DOĞRULANMIŞ KAYNAK KANITI:\n"
                    + _research_evidence_text(research_opportunity)[:5000]
                    + "\n\nYANLIŞ PLAN:\n" + plan_text
                ),
                task_type="planning", preferred_provider=route_result.provider_used,
                allowed_cost_classes=("free", "plan") if free_only else None,
            )
            if correction.success and not is_llm_failure(correction.output):
                plan_text = correction.output
                route_result = correction
            drift_reason = _research_domain_drift(plan_text, research_opportunity)
            if drift_reason:
                return (
                    "VIDEO RENDER: BLOCKED_RESEARCH_DRIFT\n"
                    f"{drift_reason} Yanlış bilgiyle video oluşturulmadı; hiçbir şey yayınlanmadı."
                )

        unsupported_claims = _unsupported_research_claims(plan_text, research_opportunity)
        if unsupported_claims:
            correction = self.router.manager.route_and_generate(
                prompt=(
                    "Aşağıdaki haber videosu planında kaynakların söylemediği iddialar var: "
                    + ", ".join(unsupported_claims)
                    + ". Bu iddiaları tamamen çıkar. Yeni olgu, sağlık yorumu veya yer bilgisi ekleme; "
                    "dokuz bölüm başlığını ve Türkçe dili koru. Yalnızca düzeltilmiş planı döndür.\n\n"
                    "DOĞRULANMIŞ KAYNAK KANITI:\n"
                    + _research_evidence_text(research_opportunity)[:5000]
                    + "\n\nDÜZELTİLECEK PLAN:\n" + plan_text
                ),
                task_type="planning", preferred_provider=route_result.provider_used,
                allowed_cost_classes=("free", "plan") if free_only else None,
            )
            if correction.success and not is_llm_failure(correction.output):
                plan_text = _normalize_plan_headings(correction.output)
                route_result = correction
            unsupported_claims = _unsupported_research_claims(plan_text, research_opportunity)
            if unsupported_claims:
                if stage_sink is not None:
                    stage_sink["last_stage"] = "unsupported_claims_stop"
                return (
                    "VIDEO RENDER: BLOCKED_UNSUPPORTED_CLAIMS\n"
                    "Kaynakların doğrulamadığı ifadeler: " + ", ".join(unsupported_claims)
                    + ". Yanlış bilgiyle video oluşturulmadı; hiçbir şey yayınlanmadı."
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
            # Round 5 repair: an explicit ``research_opportunity`` (see above)
            # is the authoritative grounding signal when present -- it is
            # already truthfulness-checked (market coverage + freshness,
            # see ``build_selected_opportunity``) BEFORE ever reaching here
            # (MediaAgent.execute() never calls ``plan()`` with an
            # insufficient one), so it grounds production exactly like a
            # KnowledgeBase hit does, just sourced explicitly instead of an
            # internal lookup that can silently miss.
            if research_opportunity is not None:
                research_grounded = True
                research_evidence_ref = {
                    "location_or_market": research_opportunity.get("location_or_market"),
                    "freshness_status": research_opportunity.get("freshness_status"),
                    "source_count": len(research_opportunity.get("supporting_evidence") or []),
                    "selected_topic": str(research_opportunity.get("selected_topic") or "")[:500],
                    "format_reference_count": len(research_opportunity.get("format_references") or []),
                    "supporting_evidence": [
                        {
                            "title": str(item.get("title") or "")[:300],
                            "summary": str(item.get("summary") or "")[:1200],
                            "url": str(item.get("url") or ""),
                            "published_at": str(item.get("published_at") or ""),
                        }
                        for item in (research_opportunity.get("supporting_evidence") or [])[:5]
                        if isinstance(item, dict)
                    ],
                }
            else:
                research_grounded = prior is not None
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
                    channel_language=production_language,
                    research_grounded=research_grounded,
                    research_evidence_ref=research_evidence_ref,
                    stage_sink=stage_sink,
                    standing_permission=standing_permission,
                    free_only=free_only,
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

            # A discovered headline can be German/French/Italian while the
            # requested channel output is Turkish. Comparing that foreign
            # headline token-for-token with the translated Turkish script
            # creates a false visual_relevance failure even when every scene
            # matches the selected story. For a truthfulness-checked research
            # opportunity, validate the rendered scenes against the parsed
            # output title (the semantic subject actually given to viewers).
            # Explicit-topic productions keep the original user topic as the
            # anti-drift target.
            quality_goal = topic
            if research_opportunity is not None:
                parsed_for_quality = parse_plan_text(plan_text)
                if parsed_for_quality is not None and parsed_for_quality.title.strip():
                    quality_goal = parsed_for_quality.title.strip()
            artifact_block = self._produce_with_bounded_repair(
                topic, plan_text, duration_seconds, _build_production,
                stage_sink=stage_sink, quality_goal=quality_goal,
            )

        production_note = (
            "Gerçek video taslağı yerel olarak üretildi; YouTube'a yüklenmedi."
            if self.last_artifact_path else
            "Gerçek video artifact üretilemedi; hiçbir şey YouTube'a yüklenmedi."
        )
        license_block = ""
        if self.last_artifact_path:
            lines = _license_evidence_lines(self.last_production_record)
            license_block = (
                "\n\nMEDYA LİSANS KANITI\n" + "\n".join(lines)
                if lines else "\n\nMEDYA LİSANS KANITI\nEKSİK"
            )
        return (
            f"YouTube içerik planı tamamlandı (hedef: {duration_seconds} sn).\n\n"
            f"{plan_text}\n\n"
            f"KALİTE KONTROL\n{quality.summary}\n\n"
            f"ORTAM DURUMU\n{capability_note}\n\n{production_note}\n\n"
            f"Rapor kaydedildi:\n{report_path}{artifact_block}{license_block}"
        )

    def _produce_with_bounded_repair(
        self, topic: str, plan_text: str, duration_seconds: int, rebuild, *,
        stage_sink: dict | None = None, quality_goal: str | None = None,
    ) -> str:
        """Render, self-check against the real quality gates, and bounded-retry
        the *repairable* failures (Sprint: real-production quality-gate audit,
        Phase 8 -- "repair loop"). A repairable gate failure (audio/timing/
        motion-repetition/Shorts-format) triggers a full regenerate-and-rerender
        (there is no isolated per-stage regeneration API yet, so the retry unit
        is coarse: a whole new build+render, not a single patched scene) up to
        ``MAX_REPAIR_ATTEMPTS`` times. A non-repairable failure (research
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

            # Round 4 repair (real live-mission evidence: render completed,
            # quality_check then hit the outer 75s department timeout, and
            # the final mission report claimed "ARTIFACT STATUS: MISSING"
            # even though a real file existed on disk). ROOT CAUSE:
            # ``self.last_artifact_path`` -- the ONLY signal
            # ``MediaAgent.execute()`` reads to record ``task.metadata
            # ["artifact_path"]`` -- used to be assigned AFTER the quality
            # check call below returned. If that call never returns in
            # time, the assignment never runs and the real rendered file
            # is reported as if it never existed. Fix: record the artifact
            # the moment it's known to exist -- BEFORE the (potentially
            # slow/blocking) quality check -- and also write it directly
            # into the shared ``stage_sink`` dict (== ``task.metadata``),
            # the SAME live-write pattern already used for "last_stage" (see
            # ``MediaAgent.execute``'s comment) so it survives even if this
            # whole call is later killed by an outer timeout before
            # returning. This does NOT change completion semantics: a
            # failing/timed-out quality check still keeps the mission
            # incomplete (see ``src.mission.completion._valid_artifact``,
            # which still requires the artifact to PASS validation) -- it
            # only stops a truthful, already-rendered artifact from being
            # reported as missing.
            self.last_artifact_path = render.artifact_path
            if stage_sink is not None:
                stage_sink["artifact_path"] = render.artifact_path
                stage_sink["last_stage"] = "quality_check_start"
            check = validate_media_goal_artifact(
                Path(render.artifact_path), quality_goal or topic, stage_sink=stage_sink,
            )
            failing = [name for name in check.critical_failures if name != "publication_readiness"]
            # Preserve the exact result of the quality gate that decided
            # whether this render may leave the media pipeline.  Mission
            # completion used to re-run the same validator against the much
            # broader *original command* (for example: "find current Swiss
            # news, make a Short...") rather than the selected story title
            # used here.  A genuinely approved render could therefore be
            # reported as RENDERED_NOT_APPROVED even though this method had
            # just returned ``GERÇEK VIDEO ARTIFACT``.  The shared stage sink
            # is task.metadata, so this records a path-bound, non-transferable
            # approval without weakening or skipping any gate.
            if stage_sink is not None:
                stage_sink["artifact_quality_validation"] = {
                    "artifact_path": render.artifact_path,
                    "validation_goal": quality_goal or topic,
                    "passed": not failing,
                    "technical_passed": check.technical_passed,
                    "semantic_passed": check.semantic_passed,
                    "critical_failures": list(failing),
                }
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
            if non_repairable or attempts >= MAX_REPAIR_ATTEMPTS:
                reason = (
                    f"non-repairable quality gate failure(s): {', '.join(non_repairable)}"
                    if non_repairable else
                    f"repair attempts exhausted ({MAX_REPAIR_ATTEMPTS}) for: {', '.join(repairable)}"
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
