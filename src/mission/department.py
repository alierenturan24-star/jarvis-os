from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.mission.models import MissionType


@dataclass
class Department:
    """Bir departmanın kaydı: adı, açıklaması ve seçim için anahtar
    kelimeleri. Gerçek işi YAPMAZ — yalnızca ne zaman seçileceğini ve
    hangi alt sistemi temsil ettiğini tanımlar."""

    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    # 0.0-1.0: bu departmanın arkasında GERÇEKTEN çalışan, test edilmiş
    # bir JARVIS alt sistemi olup olmadığının kaba göstergesi
    # (confidence/risk hesaplamasında kullanılır).
    maturity: float = 0.5


# Sprint 9-12'de inşa edilen, GERÇEKTEN var olan alt sistemlere karşılık
# gelen departmanlar yüksek maturity alır; henüz karşılığı olmayanlar
# (media, social_media, youtube, security, learning, automation) düşük
# maturity ile kaydedilir — bu, Mission.confidence/risk_level'a dürüstçe
# yansır.
DEFAULT_DEPARTMENTS: tuple[Department, ...] = (
    Department("research", "Genel web/haber araştırması (src.research)", ["araştır", "incele", "haber", "keşfet", "bul"], maturity=1.0),
    Department("finance", "Finans/kripto/piyasa analizi (src.finance)", [
        "coin", "borsa", "finans", "finance engine", "yatırım", "kripto", "trading", "hisse",
        "stratej", "strategy lab", "backtest", "out-of-sample", "oos", "paper",
    ], maturity=1.0),
    Department("github", "GitHub Intelligence: repo arama/değerlendirme (src.github)", ["github", "repo", "açık kaynak"], maturity=1.0),
    Department("evaluation", "Repo uygunluk/risk değerlendirmesi (src.evaluation)", ["değerlendir", "evaluation", "puanla"], maturity=1.0),
    Department("sandbox", "İzole statik repo analizi (src.sandbox)", ["sandbox", "izole", "güvenli çalıştır"], maturity=1.0),
    Department("integration", "Entegrasyon planlama (src.integration)", ["entegre", "entegrasyon", "birleştir"], maturity=1.0),
    Department(
        "browser",
        "Tarayıcı otomasyonu (src.agents.browser_agent)",
        [
            "web sitesi", "tarayıcıda aç", "google'da ara", "aç",
            # Sprint 21 düzeltmesi: kullanıcı açıkça "browser/web/internette
            # araştır" dediğinde de bu departman tetiklenmeli. "i̇nternette"
            # varyantı KASITLI: Python'da "İ".lower() düz "i" değil, "i" +
            # birleşen nokta (U+0307) üretir -- bu yüzden cümle başı büyük
            # "İnternette" düz "internette" ile EŞLEŞMEZ; ikisi de eklendi.
            "browser kullan", "web'de araştır", "internette araştır",
            "i̇nternette araştır", "site aç",
        ],
        maturity=0.8,
    ),
    Department("coding", "Kod yazma/hata ayıklama (src.agents.coding_agent)", ["kod yaz", "debug", "hata ayıkla", "hatayı bul", "bug fix", "fonksiyon"], maturity=0.8),
    # Sprint 39: "otomasyon kurulumu" (gerçek zamanlama/hesap/pipeline
    # kurulumu) hâlâ YOK -- yalnızca yayın-öncesi kontrol listesi ÜRETİR
    # (src.automation), bu yüzden maturity ORTA düzeyde tutuldu (0.3'ten
    # yükseltildi ama "tam otomasyon" seviyesine değil).
    Department("automation", "Yayın-öncesi kontrol listesi üretimi (src.automation) -- gerçek kurulum/zamanlama YAPMAZ", ["otomasyon kur", "otomatikleştir", "pipeline kur"], maturity=0.5),
    # Sprint 39: gerçek video/ses DOSYASI üretimi hâlâ YOK (bu ortamda
    # FFmpeg/TTS/görsel aracı kurulu değil) -- yalnızca senaryo/sahne/
    # seslendirme-planı/görsel-planı/altyazı/thumbnail/başlık ÜRETİR
    # (src.media, gerçek bir LLM çağrısıyla). maturity bu yüzden 1.0
    # DEĞİL, kısmi (0.6) -- dürüstçe "planlama var, üretim yok" yansıtır.
    Department("media", "YouTube içerik planlama ve güvenli yerel video render (src.media)", ["video üret", "görsel oluştur", "ses oluştur", "içerik üret"], maturity=0.8),
    Department("social_media", "Sosyal medya paylaşımı (henüz özel modül yok)", ["sosyal medya", "twitter", "instagram", "tiktok", "paylaşım"], maturity=0.1),
    Department("security", "Güvenlik/risk denetimi (henüz özel modül yok)", ["güvenlik", "zafiyet", "penetrasyon", "audit"], maturity=0.3),
    Department("learning", "Öğrenme/eğitim kaynağı toplama (henüz özel modül yok)", ["öğren", "eğitim al", "kurs", "öğret"], maturity=0.2),
    # Sprint 17: GitHub dışındaki AI ekosistemini (yeni model/araç/agent
    # framework duyuruları -- HuggingFace, Ollama, OpenRouter, Anthropic,
    # OpenAI, Gemini, DeepSeek, Qwen, Mistral, NVIDIA, Reddit, ...) GERÇEK
    # web araması ile tarayan departman. Yeni bir arama/puanlama sistemi
    # İCAT ETMEZ -- zaten var olan src.evolution.collector.EvolutionCollector
    # (WebSearchTool tabanlı gerçek arama) ve src.evolution.scorer.EvolutionScorer
    # (mevcut sezgisel puanlama) üzerine kurulu (bkz. department_adapters.py).
    Department(
        "ai_discovery",
        "Yeni AI model/araç/agent-framework keşfi (src.evolution -- gerçek web araması)",
        [
            "ai araçları", "ai aracı", "yeni model", "yeni ai modeli", "ai modelleri",
            "ücretsiz ai", "ai agent framework", "mcp server", "browser agent projesi",
            "coding assistant", "yapay zeka aracı", "yapay zeka modeli",
        ],
        maturity=0.7,
    ),
)


# Sınıflandırma için ÖNCELİK sırası: daha SPESİFİK alan sinyalleri
# (ör. "coin"), daha GENEL fiillerden (ör. "araştır") ÖNCE kontrol
# edilir — aksi halde "yeni coin araştır" gibi bir istek yanlışlıkla
# RESEARCH'e düşerdi (hem FINANCE hem RESEARCH anahtar kelimesi içerir).
_MISSION_TYPE_PRIORITY: tuple[MissionType, ...] = (
    MissionType.YOUTUBE,
    MissionType.FINANCE,
    MissionType.SECURITY,
    MissionType.AI_DISCOVERY,
    MissionType.CODE,
    MissionType.GITHUB,
    MissionType.MEDIA,
    MissionType.SOCIAL_MEDIA,
    MissionType.LEARNING,
    MissionType.AUTOMATION,
    MissionType.BROWSER,
    MissionType.RESEARCH,
)

# Sprint 21 düzeltmesi: kısa/yaygın kripto sembolleri ("btc","eth","sol",...)
# düz alt-dize (substring) olarak eklenirse ciddi yanlış-pozitif riski taşır
# ("link" -> "bu linki aç", "sol" -> Türkçe "sol/left" kelimesi). Bu yüzden
# AYRI bir sözlükte, KELİME SINIRI (\b) ile eşleştirilirler -- mevcut
# ``_MISSION_TYPE_KEYWORDS`` alt-dize mekanizması DEĞİŞTİRİLMEDİ, yalnızca
# bu az sayıdaki riskli anahtar kelime için ek bir kontrol katmanı eklendi.
# "sol"/"link" gibi gerçekten çok yaygın Türkçe/İngilizce kelimelerle
# çakışma riski kelime-sınırıyla AZALTILDI ama tamamen SIFIRLANAMAZ (ör.
# "sol parti" ifadesi de "sol" kelimesini tek başına içerir) -- bilinen,
# kabul edilmiş bir sınırlamadır (bkz. Sprint 21 raporu).
_MISSION_TYPE_WORD_KEYWORDS: dict[MissionType, tuple[str, ...]] = {
    MissionType.FINANCE: ("btc", "eth", "sol", "bnb", "xrp", "doge", "link", "avax"),
    # ``bul`` is an imperative research verb only as a complete word.  A
    # substring match also catches unrelated inflections such as ``bulunma``
    # ("do not claim"), routing local runtime/status questions to RESEARCH.
    MissionType.RESEARCH: ("bul",),
}


def _contains_word(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)


# Sprint 42 (NEGATION BUG): Sprint 41 canlı testinde yakalandı -- "internette
# araştır" anahtar kelimesi, "internette araştırMA yapMA" (kullanıcı AÇIKÇA
# İNTERNETİ KULLANMA dedi) içindeki "araştır" ön-ekiyle YANLIŞLIKLA eşleşiyordu.
# Genel bir Türkçe morfoloji çözümleyici İCAT EDİLMEZ -- yalnızca bu somut
# kalıbı (fiil kökü + "-ma"/"-me" olumsuzluk eki, ardından "yap"/"et" gibi
# GERÇEK pozitif bir devam kelimesi YOKSA) hedefleyen dar bir kontrol.
_NEGATION_SUFFIX_PATTERN = re.compile(r"^(ma|me)\b")
# DİKKAT: "yap" ile başlayan bir kelime olumlu OLMAYABİLİR -- "yapma"
# (yapMAYIN) da "yap" ile BAŞLAR. Bu yüzden yalnızca TAM kelime eşleşmesi
# (bir sonraki kelimenin TAMAMI) kontrol edilir, ``startswith`` DEĞİL.
_POSITIVE_CONTINUATION_WORDS = ("yap", "yapın", "yapalım", "yapıyor", "et", "edin", "edelim", "ediyor")
_NEGATIVE_CONTINUATION_PREFIXES = ("yapma", "etme")
_NEGATION_LOOKAHEAD_CHARS = 30


def keyword_matches(lowered_text: str, keyword: str) -> bool:
    """``keyword`` metinde geçiyor mu -- ama HEMEN ardından bir olumsuzluk
    eki geliyorsa (ör. "araştırma yapMA") ve bunu "yap"/"et" gibi GERÇEK
    pozitif bir kelime İZLEMİYORSA (ör. "araştırma YAP"), o geçiş
    reddedilir. Metinde AYNI kelimenin başka (olumsuzlanmamış) bir geçişi
    varsa YİNE DE ``True`` döner -- yalnızca İLK geçiş kontrol edilip
    atlanmaz."""

    if keyword not in lowered_text:
        return False

    for match in re.finditer(re.escape(keyword), lowered_text):
        remainder = lowered_text[match.end():match.end() + _NEGATION_LOOKAHEAD_CHARS]
        negation = _NEGATION_SUFFIX_PATTERN.match(remainder)
        if not negation:
            return True  # bu geçişte olumsuzluk eki yok -- normal eşleşme

        after_suffix = remainder[negation.end():].lstrip(" .,!?")
        first_word_match = re.match(r"\w+", after_suffix)
        first_word = first_word_match.group(0) if first_word_match else ""
        if first_word.startswith(_NEGATIVE_CONTINUATION_PREFIXES):
            continue  # "...araştırma yapMA..." -- çifte olumsuzluk, KESİN olumsuz
        if first_word in _POSITIVE_CONTINUATION_WORDS:
            return True  # "...araştırma yap..." -- gerçek pozitif kullanım

        # Bu geçiş olumsuzlanmış (ör. "araştırma yapma") -- diğer
        # geçişlere bak, hiçbiri pozitif değilse en sonunda False dönülür.

    return False


_MISSION_TYPE_KEYWORDS: dict[MissionType, tuple[str, ...]] = {
    MissionType.RESEARCH: ("araştır", "incele", "haber", "keşfet"),
    MissionType.AI_DISCOVERY: (
        "ai araçları", "ai aracı", "yeni model", "yeni ai modeli", "ai modelleri",
        "ücretsiz ai", "ai agent framework", "mcp server", "browser agent projesi",
        "coding assistant", "yapay zeka aracı", "yapay zeka modeli",
    ),
    # Bare "para" is commonly a safety constraint ("para harcama"), not
    # a market-analysis goal. Concrete finance domains remain authoritative.
    MissionType.FINANCE: (
        "coin", "borsa", "finans", "finance engine", "yatırım", "kripto", "trading", "hisse",
        "bitcoin", "ethereum", "stratej", "strategy lab", "backtest", "out-of-sample", "oos", "paper",
    ),
    # Sprint 35 düzeltmesi: "100 Shorts fikri üret." / "Shorts içerik
    # fikirleri üret." / "Video fikirleri üret." gibi açık YouTube İÇERİK
    # ÜRETİMİ istekleri metinde "youtube" kelimesi GEÇMEDİĞİ için
    # RESEARCH'e düşüyordu (canlı doğrulandı, bkz. Sprint 34 canlı test
    # raporu). "shorts"/"video fikri"/"video fikirleri" eklendi -- bu üçü,
    # MEDIA'nın ("video üret") tetiklediği TAM ifadelerle ÇAKIŞMAZ (bkz.
    # Sprint 34/35 analizi), bu yüzden mevcut MEDIA sınıflandırması
    # BOZULMAZ. YOUTUBE zaten en yüksek öncelikli tür olduğu için
    # (bkz. ``_MISSION_TYPE_PRIORITY``) bu ek kesin, dar kapsamlı sinyal
    # yalnızca gerçekten YouTube içerik fikri isteyen metinleri yakalar.
    MissionType.YOUTUBE: (
        "youtube", "video kanalı", "kanal aç", "shorts", "video fikri", "video fikirleri",
    ),
    MissionType.SOCIAL_MEDIA: ("sosyal medya", "twitter", "instagram", "tiktok", "paylaşım"),
    MissionType.CODE: ("jarvis'i geliştir", "jarvisi geliştir", "kendini geliştir", "kod yaz", "python", "debug", "geliştir", "hatayı bul", "bug fix"),
    MissionType.GITHUB: ("github", "repo bul", "açık kaynak proje"),
    MissionType.BROWSER: (
        "web sitesi", "tarayıcıda aç", "google'da ara",
        "browser kullan", "web'de araştır", "internette araştır",
        "i̇nternette araştır", "site aç",
    ),
    MissionType.SECURITY: ("güvenlik", "zafiyet", "penetrasyon", "audit"),
    MissionType.LEARNING: ("öğren", "eğitim al", "kurs", "öğret"),
    MissionType.AUTOMATION: ("otomasyon kur", "otomatikleştir", "pipeline kur"),
    MissionType.MEDIA: ("video üret", "görsel oluştur", "ses oluştur", "içerik üret"),
}


_ROUTING_CONSTRAINT_PATTERNS = (
    r"\bpara\s+harcama\w*",
    r"\bücretli\s+(?:api\w*\s+)?(?:kullanma\w*|aktive\s+etme\w*)",
    r"\b(?:commit|push|commit/push)\s+yapma\w*",
    r"\b(?:kurma|yükleme|dosya\w*\s+değiştirme)\w*",
)


def routing_text(text: str) -> str:
    """Remove narrow safety/negative constraints from routing signals only.

    The original prompt remains untouched on Mission/Task; this normalized
    view is used solely for intent and department selection.
    """

    lowered = (text or "").casefold()
    for pattern in _ROUTING_CONSTRAINT_PATTERNS:
        lowered = re.sub(pattern, " ", lowered, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", lowered).strip()

# "Mission ↓ Doğru departmanlar" — mission türüne göre KANONİK departman
# demeti. select_departments() bunu taban alır, sonra metindeki ek
# departman anahtar kelimeleriyle (varsa) ZENGİNLEŞTİRİR.
DEFAULT_DEPARTMENTS_BY_MISSION_TYPE: dict[MissionType, tuple[str, ...]] = {
    MissionType.RESEARCH: ("research",),
    # Sprint 17: AI Discovery -- genel web araması (ai_discovery) +
    # GitHub'daki karşılığını arayıp değerlendirmek (github, evaluation).
    # Kabul testinin beklediği "Mission -> Research -> GitHub ->
    # Evaluation -> CEO Report" zincirini karşılar.
    MissionType.AI_DISCOVERY: ("ai_discovery", "github", "evaluation"),
    MissionType.FINANCE: ("finance", "research", "browser"),
    MissionType.YOUTUBE: ("research", "github", "browser", "media", "automation"),
    MissionType.SOCIAL_MEDIA: ("research", "browser", "media", "automation"),
    MissionType.CODE: ("coding", "github", "evaluation", "sandbox", "integration"),
    MissionType.GITHUB: ("github", "evaluation", "sandbox", "integration"),
    MissionType.BROWSER: ("browser", "research"),
    MissionType.SECURITY: ("security", "sandbox", "research"),
    MissionType.LEARNING: ("research", "learning"),
    MissionType.AUTOMATION: ("automation", "browser"),
    MissionType.MEDIA: ("media", "browser", "automation"),
}


def detect_mission_type(text: str) -> MissionType | None:
    """Öncelik sıralı ilk-eşleşme ile bir mission türü arar; hiçbir
    departman-özel/alan-özel anahtar kelime eşleşmezse ``None`` döner.

    Bu, ``classify_mission_type``'ın (her zaman bir tür döndüren, asla
    ``None`` dönmeyen) TEMEL taşıdığı fonksiyondur; Sprint 14'te canlı
    sohbet köprüsünün "bu mesaj gerçekten bir Mission mü, yoksa normal
    sohbet mi?" ayrımını yapabilmesi için (ör. "Merhaba" hiçbir anahtar
    kelimeyle eşleşmez → ``None`` → Mission TETİKLENMEZ) ayrı bir
    fonksiyon olarak açığa çıkarıldı.
    """

    lowered = routing_text(text)

    for mission_type in _MISSION_TYPE_PRIORITY:
        keywords = _MISSION_TYPE_KEYWORDS.get(mission_type, ())
        if any(keyword_matches(lowered, keyword) for keyword in keywords):
            return mission_type

        word_keywords = _MISSION_TYPE_WORD_KEYWORDS.get(mission_type, ())
        if word_keywords and _contains_word(lowered, word_keywords):
            return mission_type

    return None


# Sprint 37: AUTONOMOUS RESEARCH & SELF-IMPROVEMENT LOOP -- kullanıcının
# "araştırma yöntemini kullanıcı tek tek tarif etmek zorunda kalmaması"
# (bkz. Sprint 37 HEDEF) için, "bu istek tek seferlik bir Mission değil,
# çok turlu bir kendi kendine geliştirme/araştırma döngüsü olmalı" sinyalini
# tanıyan DAR bir anahtar kelime kümesi. KASITLI OLARAK dar tutuldu (yalnızca
# açık "daha iyi ol"/"kendini geliştir" ifadeleri) -- ``detect_mission_type``
# gibi geniş bir sınıflandırma İCAT ETMEZ; ``detect_mission_type(text) is
# None`` olduğu sürece (düz sohbet) hiçbir zaman tetiklenmez, bu yüzden
# mevcut tek-seferlik Mission akışının 297 testi ETKİLENMEZ.
_RESEARCH_LOOP_CUES = (
    "daha iyi ol",
    "kendini geliştir",
    "kendini nasıl geliştir",
    "self improvement",
    "self-improvement",
)


def detect_research_loop_intent(text: str) -> bool:
    """``True`` ise istek tek bir Mission yerine sınırlı-turlu bir
    Autonomous Research Loop (bkz. ``src.research_loop``) ile
    çalıştırılmalı. Düz sohbet ya da bilinen hiçbir Mission sinyali
    içermeyen metinlerde HER ZAMAN ``False`` -- bu döngü yalnızca ZATEN
    bir Mission olarak sınıflandırılabilecek isteklere EKLENİR, onların
    yerine YENİ bir sınıflandırma İCAT ETMEZ."""

    if detect_mission_type(text) is None:
        return False

    lowered = (text or "").strip().lower()
    return any(cue in lowered for cue in _RESEARCH_LOOP_CUES)


def classify_mission_type(text: str) -> MissionType:
    """Kullanıcı isteğini 11 mission türünden birine sınıflandırır.
    Öncelik sıralı ilk-eşleşme; hiçbiri eşleşmezse ``RESEARCH``'e
    (en güvenli/genel varsayılan) düşer. Davranışı Sprint 13'teki ile
    BİREBİR aynıdır (bkz. ``detect_mission_type``)."""

    return detect_mission_type(text) or MissionType.RESEARCH
