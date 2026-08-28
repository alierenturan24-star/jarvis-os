from __future__ import annotations

import re
from typing import Optional

from src.core.plan_executor import PlanExecutionReport, PlanExecutor
from src.core.task_plan import TaskPlan
from src.github.github_intelligence import GitHubIntelligence
from src.jobs.job_manager import JobManager
from src.jobs.task import Task
from src.mission.department import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_DEPARTMENTS_BY_MISSION_TYPE,
    Department,
    classify_mission_type,
    keyword_matches, routing_text,
)
from src.mission.department_adapters import (
    GITHUB_REPORT_SEARCH_LIMIT,
    DepartmentAdapterRegistry,
    search_target_repositories,
)
from src.mission.models import Mission, MissionStatus, MissionType
from src.mission.target_resolver import (
    Target, TargetKind, TargetResolver, has_acquisition_signal, target_matches_repo,
)
# Sprint 45: yalnızca "coding" departmanının dış görev timeout'unu, bu iki
# CLI worker'ın GERÇEK iç timeout'larına göre hesaplamak için (bkz. aşağıdaki
# ``CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS``). Döngüsel import riski YOK --
# ``department_adapters`` (yukarıda, satır 18) zaten ``src.agents.coding_agent``
# üzerinden ``src.providers.provider_manager``'ı (ve dolayısıyla bu iki
# modülü) import ETMİŞ durumda; bu yalnızca ZATEN yüklü modüllerden isim
# alır, yeni bir import döngüsü İCAT ETMEZ.
from src.providers.claude_code_provider import DEFAULT_TIMEOUT_SECONDS as _CLAUDE_CODE_TIMEOUT_SECONDS
from src.providers.codex_provider import DEFAULT_TIMEOUT_SECONDS as _CODEX_TIMEOUT_SECONDS
from src.config.settings import Settings
from src.research.collector import MAX_SEARCH_STEPS

# Sprint 33B: "AI Validation Pipeline" (evaluation/sandbox/integration)
# tetiklenmesi gereken görevler için -- bkz. ``_wants_repo_validation_pipeline``.
_VALIDATION_DEPARTMENTS = ("evaluation", "sandbox", "integration")

# Sprint 15: gerçek modüle bağlı görevler için (ağ/klon içeren, sınırsız
# beklemeye BIRAKILMAMASI gereken) üst sınır. Handler'sız (henüz
# bağlanmamış) departmanları ETKİLEMEZ -- onlar zaten anında "handler
# tanımlı değil" ile başarısız olur.
#
# Sprint 19 (Beta Stabilization) düzeltmesi: 45 sn, research/finance gibi
# gerçek bir Ollama LLM çağrısı içeren departmanlar için YETERSİZDİ --
# ölçüldü (bkz. Sprint 19 raporu): tek bir yerel Ollama çağrısı bu
# donanımda 45-100+ saniye sürebiliyor (gereksiz/kaldırılabilir bir
# bekleme DEĞİL -- gerçek model çıkarım süresi). 45 sn'nin YETERSİZ
# olduğu ölçüldükten sonra üst sınır, gözlenen en kötü durumu (~100 sn)
# güvenli bir marjla karşılayacak şekilde yükseltildi.
DEPARTMENT_TASK_TIMEOUT_SECONDS = 75.0

# Sprint 45 (CLAUDE CODE TIMEOUT FIX): "coding" tek başına, ProviderManager'ın
# KENDİ sıralı fallback zincirini (bkz. ``ProviderManager.route_and_generate``
# -- ``PlanExecutor.run()`` görevleri SIRALI/bloklayan ``future.result()``
# ile çalıştırır, bkz. job_manager.py) TEK bir Task.handler çağrısı İÇİNDE
# çalıştırabilen tek departman: bir gerçek abonelik-CLI worker'ı (Claude
# Code) dener, başarısız olursa BİR SONRAKİ gerçek CLI worker'ını (Codex)
# dener. 2026-08-23 canlı smoke testinde bu paylaşılan 75 sn'lik üst sınır
# (o zaman claude_code 60 sn + codex ~11 sn = ~71 sn) yalnızca ~4 sn marjla
# ZATEN geçmişti -- ClaudeCodeWorker'ın kendi timeout'u eskisinden daha
# gerçekçi bir değere (bkz. ``Settings.CLAUDE_CODE_TIMEOUT_SECONDS``)
# yükseltilince, PAYLAŞILAN sabiti değiştirmeden bırakmak dış (JobManager)
# timeout'unun iç (subprocess) timeout'undan ÖNCE ateşlenmesine -- yani
# arka planda öldürülemeyen bir subprocess bırakan, Sprint 41'in Ollama için
# zaten belgelediği YARIŞ hatasının AYNISINA -- yol açardı.
#
# Çözüm Sprint 41'deki İLE AYNI desen (paylaşılan dış sınırı KORU, yalnızca
# gerçekten ihtiyacı olan tarafı ayarla) -- burada "taraf" tersine döndü:
# Ollama'da İÇ timeout küçültüldü, burada yalnızca "coding" departmanının
# DIŞ bütçesi -- claude_code + codex'in TAM ardışık en-kötü-durum toplamı +
# güvenlik marjı kadar -- büyütüldü. Paylaşılan ``DEPARTMENT_TASK_TIMEOUT_
# SECONDS`` KASITLI OLARAK değiştirilmedi: github/evaluation/sandbox/
# integration hiçbir CLI subprocess'e dokunmaz, gereksiz yere daha uzun bir
# üst sınır almamalılar.
CODING_DEPARTMENT_TASK_TIMEOUT_MARGIN_SECONDS = 15.0

# Ardışık en-kötü-durum: claude_code dener VE zaman aşımına uğrar, ardından
# codex dener VE zaman aşımına uğrar, artı sabit bir güvenlik marjı. Her
# iki iç timeout da yapılandırılabilir olduğundan (``Settings.
# CLAUDE_CODE_TIMEOUT_SECONDS``) bu dış bütçe OTOMATİK olarak onlarla
# ölçeklenir -- iki ayrı yerde birbirinden bağımsız güncellenmesi gereken
# ikinci bir sabit İCAT EDİLMEDİ.
CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS = (
    _CLAUDE_CODE_TIMEOUT_SECONDS + _CODEX_TIMEOUT_SECONDS + CODING_DEPARTMENT_TASK_TIMEOUT_MARGIN_SECONDS
)

# Sprint: research/production pipeline audit -- SAME pattern as
# CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS above: research's outer department
# budget is sized FROM its own real inner worst-case (never the reverse). A
# real Swiss Insider mission run hit "Task timed out (20.0 sec)" -- the
# actual bug was mission/recovery.py's retry shrink (see there), but the
# FIRST attempt's own budget deserves the same honest accounting the coding
# department already gets: up to ``MAX_SEARCH_STEPS`` sequential web
# searches at ``Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS`` each (self-
# bounded via ResearchManager.research()'s deadline, see there), PLUS one
# summarization LLM call -- reusing DEPARTMENT_TASK_TIMEOUT_SECONDS's own
# already-justified real-world local-Ollama worst-case budget (its docstring
# above: a single call can take 45-100+s) instead of inventing a second,
# independent "how slow can Ollama be" constant -- PLUS a safety margin.
RESEARCH_DEPARTMENT_TASK_TIMEOUT_MARGIN_SECONDS = 15.0
RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS = (
    Settings.RESEARCH_PROVIDER_TIMEOUT_SECONDS * MAX_SEARCH_STEPS
    + DEPARTMENT_TASK_TIMEOUT_SECONDS + RESEARCH_DEPARTMENT_TASK_TIMEOUT_MARGIN_SECONDS
)

# Departments whose outer task timeout differs from the shared
# DEPARTMENT_TASK_TIMEOUT_SECONDS default -- each sized FROM its own real
# inner worst-case above, never an arbitrary override.
_DEPARTMENT_TASK_TIMEOUTS: dict[str, float] = {
    "coding": CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS,
    "research": RESEARCH_DEPARTMENT_TASK_TIMEOUT_SECONDS,
}

# Sprint 19 düzeltmesi: "browser" departmanının task action'ı hep sabit
# "dispatch" kalıyordu -- BrowserAgent bu action'ı TANIMADIĞI için gerçek
# BrowserTool eylemi hiçbir zaman tetiklenmiyor, hep zararsız ama YANLIŞ
# bir "desteklenmeyen işlem" mesajı dönüyordu (bkz. Sprint 18 canlı test
# raporu).
#
# Sprint 28B düzeltmesi: Sprint 19'un "her zaman search" çözümü kendi
# başına YENİ bir kök sebep oldu (bkz. Sprint 28A analizi) -- "browser"
# departmanı, mission içeriği ne olursa olsun HER ZAMAN ham mission
# metnini Google'da arıyordu; bu yüzden BrowserAgent'ın ZATEN desteklediği
# open/list_elements/click_index (DOM Engine) action'ları hiçbir zaman
# seçilemiyordu. "browser" artık bu sabit eşlemeden ÇIKARILDI ve kendi
# özel görev-üretim mantığına (bkz. ``_plan_browser_steps`` /
# ``_create_browser_tasks``) devredildi -- DOM Engine/BrowserAgent/
# BrowserTool koduna DOKUNULMADI, yalnızca onların ZATEN tanıdığı
# action'lar arasından hangisinin/hangilerinin seçileceğine karar
# veriliyor. Diğer departmanlar (github/evaluation/sandbox/integration)
# eskisi gibi ``DEFAULT_DEPARTMENT_ACTION``'a düşmeye devam eder.
DEPARTMENT_ACTIONS: dict[str, str] = {}
DEFAULT_DEPARTMENT_ACTION = "dispatch"

# --- Sprint 28B: "browser" departmanı için action seçim sinyalleri ----------
#
# Bu sabitler/yardımcılar hiçbir yeni Mission/Department/Agent/Tool/
# Provider İCAT ETMEZ -- yalnızca BrowserAgent.TOOL_ACTIONS'ın ZATEN
# desteklediği ("open", "search", "list_elements", "click_index") eylemler
# arasından, kullanıcının mesajındaki AÇIK sinyallere göre seçim yapar.
#
# Sprint 31A: "hedef NE?" (URL/repo/kategori çıkarımı) artık burada
# DEĞİL -- TEK bir yerde, ``target_resolver.py``'de çözülüyor (bkz.
# ``Mission.target`` / ``_create_browser_tasks``). Burada yalnızca
# "bununla NE YAPILACAK?" (aç/listele/tıkla/ara fiil-tespiti) kalıyor --
# eski URL/repo-slug regex'leri (``_URL_PATTERN``,
# ``_GITHUB_REPO_SLUG_PATTERN``, ``_extract_target_url``) KALDIRILDI.

_SEARCH_VERB_PATTERN = re.compile(r"\bara\b", re.IGNORECASE)
_OPEN_CUE_KEYWORDS = ("aç",)
_LIST_ELEMENTS_NOUNS = ("element", "eleman", "öğe", "oge", "dom")
_LIST_ELEMENTS_VERBS = ("listele", "göster")
_INDEX_PATTERNS = (
    re.compile(r"index\s*[:=]?\s*(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*numaral[ıi]", re.IGNORECASE),
)


def _extract_explicit_index(lowered_text: str) -> Optional[int]:
    """Metinde ``index 3`` / ``index=3`` / ``3 numaralı`` gibi AÇIK bir
    tam sayı index'i varsa döndürür; yoksa ``None`` (tahmin YÜRÜTÜLMEZ)."""

    for pattern in _INDEX_PATTERNS:
        match = pattern.search(lowered_text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _target_open_url(target: Target) -> Optional[str]:
    """Sprint 31A: ``Target``'tan (TargetResolver'ın Mission oluşturulurken
    BİR KEZ ürettiği, tüm departmanlarca paylaşılan hedef) "browser"
    departmanının açabileceği bir URL çıkarır -- kendi başına YENİDEN
    URL/repo çözümlemesi YAPMAZ (eski ``_extract_target_url`` KALDIRILDI)."""

    if target is None:
        return None
    if target.kind in (TargetKind.REPOSITORY, TargetKind.OWNER):
        return target.url
    if target.kind == TargetKind.FREE_TEXT and target.text:
        stripped = target.text.strip()
        if stripped.startswith(("http://", "https://")):
            return stripped
    return None


def _has_list_elements_cue(lowered_text: str) -> bool:
    has_noun = any(noun in lowered_text for noun in _LIST_ELEMENTS_NOUNS)
    has_verb = any(verb in lowered_text for verb in _LIST_ELEMENTS_VERBS)
    return has_noun and has_verb


def _has_search_cue(lowered_text: str) -> bool:
    return bool(_SEARCH_VERB_PATTERN.search(lowered_text))


# Sprint 33B: "en uygun/en iyi repoyu SEÇ/BUL" gibi somut bir repo seçme/
# karşılaştırma niyeti + GitHub'ın zaten dahil olması -> AI Validation
# Pipeline'ın TAMAMI (evaluation/sandbox/integration) otomatik dahil
# edilir. Sade "X hakkında araştır"/"X nedir" gibi isteklerde bu sinyal
# YOKTUR -- bu yüzden gereksiz yere tetiklenmez (bkz. Sprint 33B kabul
# kriteri: "basit görevlerde gereksiz Validation Pipeline çalıştırma").
_REPO_SELECTION_CUES = (
    "en uygun", "en iyi", "reposunu seç", "repo seç", "hangi repo",
    "hangisini seç", "reposunu bul", "repo bul", "hangi repoyu",
)


def _wants_repo_validation_pipeline(lowered_text: str) -> bool:
    return any(cue in lowered_text for cue in _REPO_SELECTION_CUES) or any(
        cue in lowered_text for cue in ("evaluation", "sandbox", "integration", "lisans", "güvenli mi")
    )


def _required_goal_departments(lowered_text: str) -> tuple[str, ...]:
    named_tool_goal = bool(re.search(r"\b[a-z0-9]+-[a-z0-9-]+\b", lowered_text)) and any(
        cue in lowered_text for cue in ("araştır", "incele", "değerlendir")
    )
    repo_goal = named_tool_goal or any(cue in lowered_text for cue in ("repo", "github", "açık kaynak proje"))
    if not repo_goal:
        return ()
    required = ["github"]
    if named_tool_goal or any(cue in lowered_text for cue in ("araştır", "incele")):
        required.insert(0, "research")
    if named_tool_goal or any(cue in lowered_text for cue in ("readme", "dokümantasyon", "documentation")):
        required.append("browser")
    if any(cue in lowered_text for cue in ("değerlendir", "evaluation", "lisans", "güvenli mi")):
        required.append("evaluation")
    if "sandbox" in lowered_text:
        required.append("sandbox")
    if any(cue in lowered_text for cue in ("integration", "entegrasyon")):
        required.append("integration")
    return tuple(required)


# --- Sprint 41: SIMPLE TASK OVER-ROUTING ----------------------------------------
#
# YOUTUBE mission türünün kanonik demeti (research/github/browser/media/
# automation, bkz. department.py) HER YouTube isteğine -- "10 Shorts
# başlığı üret." gibi saf üretim istekleri DAHİL -- körü körüne
# uygulanıyordu (Sprint 40 canlı test kanıtı: TEST C). ``media``
# departmanının KENDİ ZATEN VAR OLAN "video üret"/"görsel oluştur"/"ses
# oluştur"/"içerik üret" deseninin DEVAMI olan (yeni bir cümle listesi
# İCAT EDİLMEDEN) dar bir "üretim fiili" kalıp kümesi -- yalnızca bu
# sinyal VARSA VE enrichment hiçbir EK departman EKLEMEDİYSE (yani
# metinde başka hiçbir gerçek konu/güncel-bilgi sinyali YOKSA, bkz.
# ``select_departments``'ın enrichment taraması) araştırma/repo/browser
# departmanları çıkarılır. "Bitcoin neden düştü" gibi istekler finance
# enrichment'ını (mevcut "coin" davranışı) tetiklediği için DOKUNULMAZ.
_PURE_GENERATION_SIGNALS = (
    "başlık üret", "başlığı üret", "fikri üret", "fikirleri üret", "fikir üret",
    "isim üret", "senaryo üret", "script üret", "video üret", "çizgi film üret",
)
_YOUTUBE_INVESTIGATIVE_DEPARTMENTS = ("research", "github", "browser")
_AUDIENCE_RESEARCH_CUES = ("çocuk", "hedef kitle", "audience", "ülke", "almanya", "türkiye")
_FINANCE_STRATEGY_LAB_CUES = (
    "strategy lab", "backtest", "out-of-sample", "oos", "paper",
    "qualified stratej", "strateji aday",
)


# Mission repair (real "Jarvis İsviçre için video üret." failure, FIX 4):
# a bare MEDIA production command (market/context given, no concrete
# topic) needs CONTENT/TOPIC research first -- but "Bu hazır videoya
# altyazı ekle." (edit an asset that already exists) does NOT. Generic,
# no hardcoded market/topic -- the presence of an "existing asset" cue is
# what turns research OFF, not the presence/absence of any specific place
# name.
_EXISTING_ASSET_EDIT_CUES = (
    "bu video", "bu hazır video", "bu hazir video", "mevcut video", "var olan video",
    "bu görsele", "bu sese", "bu klibe", "bu kliple", "altyazı ekle", "altyazi ekle",
    "seslendirme ekle", "to this video", "add subtitles", "existing video",
)


def _media_needs_topic_research(lowered_text: str) -> bool:
    return not any(cue in lowered_text for cue in _EXISTING_ASSET_EDIT_CUES)


def _narrow_media_topic_research(lowered_text: str, bundle: list[str]) -> list[str]:
    if "research" in bundle or not _media_needs_topic_research(lowered_text):
        return bundle
    return [*bundle, "research"]


# FIX 2 (real "Jarvis İsviçre için video üret." failure): the raw command
# used to be sent to research/web-search VERBATIM (research task's
# ``target`` is normally the shared, unmodified mission text, same as
# every other department). Generic transform, no hardcoded search phrase:
# strip the bot address ("Jarvis,") and the recognized production-verb
# phrase ("video üret"/"video hazırla"/...), keep WHATEVER context/market
# text remains (never hardcoded), then append a generic freshness+purpose
# qualifier so the query reads as a content-opportunity research request,
# not a video-production command.
_MEDIA_ADDRESS_PREFIX_PATTERN = re.compile(r"^\s*jarvi?s[,:]?\s*", re.IGNORECASE)
_MEDIA_PRODUCTION_VERB_PATTERN = re.compile(
    r"\b(?:video|içerik|short|shorts)\w*\s+(?:üret\w*|hazırla\w*|oluştur\w*)\b"
    r"|\b(?:üret\w*|hazırla\w*|oluştur\w*)\b",
    re.IGNORECASE,
)


def _media_research_query(source_text: str) -> str:
    stripped = _MEDIA_ADDRESS_PREFIX_PATTERN.sub("", source_text or "")
    stripped = _MEDIA_PRODUCTION_VERB_PATTERN.sub("", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip(" .,:;-")
    context = stripped or "genel"
    return f"{context} güncel YouTube Shorts içerik fırsatı araştır"


def _narrow_pure_generation_youtube(
    lowered_text: str, bundle: list[str], enriched_additions: list[str],
) -> list[str]:
    persisted_production = any(cue in lowered_text for cue in (
        "youtube learning plan", "production memory", "önceki script", "onceki script",
    ))
    explicit_media_production = (
        any(signal in lowered_text for signal in _PURE_GENERATION_SIGNALS)
        or ("üret" in lowered_text and any(cue in lowered_text for cue in ("youtube", "video", "çizgi film")))
    )
    if persisted_production and explicit_media_production:
        return [name for name in bundle if name not in _YOUTUBE_INVESTIGATIVE_DEPARTMENTS]
    if enriched_additions:
        # Enrichment gerçek bir konu/domain sinyali buldu (ör. finance) --
        # araştırma/repo/browser'a HALA ihtiyaç olabilir, DOKUNMA.
        return bundle
    if not any(signal in lowered_text for signal in _PURE_GENERATION_SIGNALS):
        # Açık bir "yalnızca üret" sinyali yok -- eski davranış AYNEN korunur.
        return bundle
    removable = {"github", "browser"}
    if persisted_production or not any(cue in lowered_text for cue in _AUDIENCE_RESEARCH_CUES):
        removable.add("research")
    return [name for name in bundle if name not in removable]


# Mission repair (real Swiss-Insider-Shorts failure, ROOT CAUSE A): a plain
# YouTube content/topic-research goal ("bugünün en güçlü fırsatını
# araştır"/"research today's highest-potential opportunity") was ALWAYS
# dispatching github/evaluation/sandbox/integration purely because
# ``DEFAULT_DEPARTMENTS_BY_MISSION_TYPE[YOUTUBE]`` includes "github"
# unconditionally -- there was no distinction between DOMAIN/CONTENT
# research and CAPABILITY/ACQUISITION research. This narrows the bundle
# back down UNLESS the text carries an explicit acquisition signal (repo/
# github/kur/tool/provider/..., see ``has_acquisition_signal`` -- the same
# generic vocabulary check used by ``TargetResolver`` for its own GitHub-
# category fallback, so department selection and target resolution agree).
# An explicit repo/tool ask (handled earlier by ``_required_goal_
# departments``/keyword enrichment) always contains one of these cues, so
# nothing genuinely requested by the user is removed here.
def _narrow_pure_content_research_youtube(lowered_text: str, bundle: list[str]) -> list[str]:
    if has_acquisition_signal(lowered_text):
        return bundle
    removable = {"github", *_VALIDATION_DEPARTMENTS}
    return [name for name in bundle if name not in removable]


def _plan_browser_steps(text: str, target: Target) -> list[tuple[str, dict]]:
    """"browser" departmanı için, ham metni KOŞULSUZ search sorgusu
    yapmak yerine, metindeki AÇIK sinyallere göre sıralı
    ``(action, extra_metadata)`` adımları üretir.

    Kurallar (Sprint 28B gereksinimleri):
      1. Yalnızca index verilmiş, açma/listeleme sinyali YOKSA ->
         tek başına ``click_index``.
      2. Açık bir URL/GitHub repo'su VE listeleme isteği birlikteyse ->
         sıralı ``open`` -> ``list_elements`` (-> yalnızca index açıkça
         verilmişse ``click_index``).
      3. Yalnızca URL/açma sinyali -> tek başına ``open``.
      4. Yalnızca listeleme sinyali -> tek başına ``list_elements``.
      5. Gerçek bir arama sinyali (`` ara``) -> ``search``.
      6. Hiçbir yeni sinyal yoksa -> ESKİ davranış DEĞİŞTİRİLMEDEN korunur
         (``search``, ham metinle) -- geriye dönük uyumluluk için.

    Sprint 31A: hangi URL'nin açılacağı artık BURADA yeniden
    hesaplanmıyor -- Mission oluşturulurken bir kez çözümlenmiş ``target``
    parametresinden (``_target_open_url``) okunuyor.
    """

    lowered = text.lower()

    explicit_index = _extract_explicit_index(lowered)
    target_url = _target_open_url(target)
    has_open_cue = any(keyword in lowered for keyword in _OPEN_CUE_KEYWORDS)
    has_list_cue = _has_list_elements_cue(lowered)

    if explicit_index is not None and not target_url and not has_list_cue:
        return [("click_index", {"index": explicit_index})]

    steps: list[tuple[str, dict]] = []

    if target_url and has_open_cue:
        steps.append(("open", {"url": target_url}))

    if has_list_cue:
        steps.append(("list_elements", {}))
        if explicit_index is not None:
            steps.append(("click_index", {"index": explicit_index}))

    if steps:
        return steps

    if _has_search_cue(lowered):
        return [("search", {})]

    return [("search", {})]


class DepartmentOrchestrator:
    """CEO katmanının, işi KENDİSİ yapmadan departmanlara DAĞITAN parçası.

    Bu sınıf hiçbir görevi doğrudan çalıştırmaz: ``dispatch()`` gerçek
    Execution Engine'e (``src.core.task_plan.TaskPlan`` +
    ``src.core.plan_executor.PlanExecutor``, Sprint 8'de sertleştirilmiş
    mevcut sistem) devreder. Yeni bir yürütme motoru İCAT ETMEZ.
    """

    def __init__(
        self,
        adapters: DepartmentAdapterRegistry | None = None,
        github_intelligence: GitHubIntelligence | None = None,
    ) -> None:
        self.departments: dict[str, Department] = {}
        for department in DEFAULT_DEPARTMENTS:
            self.register_department(
                department.name, department.description, department.keywords, department.maturity,
            )
        # Sprint 15: department -> gerçek modül bağlantısı (bkz.
        # ``department_adapters.py``). ``create_tasks()`` bunu kullanarak
        # her görevin ``handler``'ını GERÇEK bir sınıfa bağlar.
        self.adapters = adapters or DepartmentAdapterRegistry()
        # Sprint 32: CATEGORY hedefinde "browser" departmanının Google'a
        # DÜŞMEDEN gerçek bir GitHub adayı bulabilmesi için -- yeni bir
        # Tool/Agent İCAT ETMEZ, github/evaluation/sandbox/integration
        # adaptörlerinin ZATEN kullandığı AYNI ``GitHubIntelligence``
        # sınıfını (kendi bağımsız örneğiyle, mevcut DI deseniyle) kullanır.
        self.github_intelligence = github_intelligence or GitHubIntelligence()

    # --- Kayıt -----------------------------------------------------------------

    def register_department(
        self,
        name: str,
        description: str = "",
        keywords: Optional[list[str]] = None,
        maturity: float = 0.5,
    ) -> Department:
        department = Department(
            name=name, description=description, keywords=list(keywords or []), maturity=maturity,
        )
        self.departments[name] = department
        return department

    # --- Seçim -----------------------------------------------------------------

    def select_departments(self, text: str) -> list[str]:
        """Kullanıcı isteğini önce bir ``MissionType``'a sınıflandırır,
        o türün KANONİK departman demetini taban alır, sonra metindeki
        ek departman-özel anahtar kelimelerle (varsa) zenginleştirir."""

        mission_type = classify_mission_type(text)
        bundle = list(DEFAULT_DEPARTMENTS_BY_MISSION_TYPE.get(mission_type, ()))

        lowered = routing_text(text)
        enriched_additions: list[str] = []
        for name, department in self.departments.items():
            if name in bundle:
                continue
            if mission_type == MissionType.CODE and name in {"research", "github"}:
                continue
            if any(keyword_matches(lowered, keyword) for keyword in department.keywords):
                bundle.append(name)
                enriched_additions.append(name)

        if mission_type != MissionType.CODE:
            for name in _required_goal_departments(lowered):
                if name not in bundle:
                    bundle.append(name)

        # Learning is a required persisted outcome for Finance autonomy
        # goals even when the user says English "learning" or Turkish
        # "hafıza" instead of the legacy "öğren" keyword.
        #
        # Mission repair (real Swiss-Insider-Shorts failure, ROOT CAUSE --
        # FINANCE LEARNING IN YOUTUBE REPORT): this used to ALSO fire for
        # "media" alone (any YouTube mission whose text merely contained
        # "learning"/"memory"/"hafıza" -- e.g. "Kalıcı YouTube learning
        # planını uygula") -- but the ONLY implementation ever wired to the
        # "learning" department is ``FinanceLearningAgent`` (see
        # ``department_adapters.DepartmentAdapterRegistry``), which reads/
        # reports the FINANCE-only ``finance_exploration`` store bucket.
        # Dispatching it for a pure-YouTube mission produced a truthful-
        # looking but completely unrelated "Finance learning persisted: N
        # candidates..." line in a YouTube report. YouTube's OWN learning
        # persistence is already handled inside the "media" task itself
        # (``YouTubeLearningAgent``, scoped to the ``youtube_learning``
        # store bucket -- see ``src.media.manager``/``src.agents.media_
        # agent``'s ``learning_persisted`` metadata flag) -- a separate
        # "learning" department task is only meaningful when "finance" is
        # ALSO present (combined Finance+YouTube autonomy goals).
        if "finance" in bundle and any(
            cue in lowered for cue in ("learning", "hafıza", "memory", "öğrendik")
        ) and "learning" not in bundle:
            bundle.append("learning")

        # Safety net: the keyword-enrichment loop above can ALSO add
        # "learning" independent of the finance-gated block just above --
        # the "learning" ``Department`` entry's own keywords
        # ("öğren"/"öğret"/"kurs"/"eğitim al") match e.g. a plain YouTube
        # "öğretici bir video üret" (educational-video) request with no
        # finance signal at all. Since "learning" only ever resolves to the
        # FINANCE-only ``FinanceLearningAgent`` (see the docstring above),
        # it must not be dispatched for a mission that isn't genuinely
        # about finance. ``MissionType.LEARNING`` itself is EXCLUDED from
        # this guard -- its canonical default bundle already includes
        # "learning" unconditionally (a separate, pre-existing design, out
        # of scope for this fix).
        if "learning" in bundle and "finance" not in bundle and mission_type != MissionType.LEARNING:
            bundle = [name for name in bundle if name != "learning"]

        # Finance Strategy Lab is itself the bounded candidate discovery,
        # comparative backtest, OOS and qualification worker. The generic
        # FINANCE bundle's web-research/browser helpers are useful for news
        # and asset-analysis goals, but are not prerequisites for this
        # evidence chain and must not turn a valid fail-closed lab verdict
        # into a provider/browser failure.
        if mission_type == MissionType.FINANCE and any(
            cue in lowered for cue in _FINANCE_STRATEGY_LAB_CUES
        ):
            bundle = [name for name in bundle if name not in {"research", "browser"}]

        # Sprint 41: saf üretim istekleri (ör. "10 Shorts başlığı üret.")
        # için gereksiz araştırma/repo/browser zincirini açma -- bkz.
        # ``_narrow_pure_generation_youtube`` (yalnızca YOUTUBE türünde ve
        # yalnızca açık bir "yalnızca üret" sinyali VE hiçbir ek konu
        # sinyali YOKSA etkilenir; diğer tüm mission türleri/istekler
        # AYNEN eskisi gibi kalır).
        if mission_type == MissionType.YOUTUBE:
            bundle = _narrow_pure_generation_youtube(lowered, bundle, enriched_additions)
            bundle = _narrow_pure_content_research_youtube(lowered, bundle)

        # FIX 4 (see helper docstring above): MEDIA's canonical bundle is
        # just ("media",) -- add "research" when the goal needs topic/
        # content discovery. "browser"/"automation" are NOT added here;
        # they remain available only via their own existing keyword
        # enrichment (e.g. an explicit "web'de araştır"/"otomasyon kur"
        # ask), never automatically for a plain produce_video request.
        if mission_type == MissionType.MEDIA:
            bundle = _narrow_media_topic_research(lowered, bundle)

        # Sprint 33B: repo seçme/karşılaştırma niyeti + GitHub zaten
        # seçiliyse, AI Validation Pipeline'ın tamamı eksiksiz çalışsın.
        if "github" in bundle and _wants_repo_validation_pipeline(lowered):
            for name in _VALIDATION_DEPARTMENTS:
                if name not in bundle:
                    bundle.append(name)

        return bundle

    # --- Görev üretimi -------------------------------------------------------------

    def create_tasks(self, mission: Mission) -> list[Task]:
        """Mission'ın seçilmiş her departmanı için görev(ler) üretir.
        Departmanlar birbirinden BAĞIMSIZDIR (aralarında depends_on yok —
        paralel çalışırlar). Sprint 15: her görevin ``handler``'ı, o
        departmanın arkasında GERÇEK bir alt sistemi olup olmadığına göre
        ``DepartmentAdapterRegistry`` üzerinden bağlanır (varsa gerçek
        modül; yoksa ``None`` -- ``JobManager`` bunu önceki davranışla
        AYNI şekilde "handler tanımlı değil" ile raporlar).

        Sprint 28B: "browser" departmanı artık TEK bir sabit görev değil,
        mesajdaki sinyale göre 1-3 SIRALI (``depends_on`` ile birbirine
        bağlı) görev üretebilir (bkz. ``_create_browser_tasks``) -- diğer
        departmanların üretim mantığı DEĞİŞMEDİ.

        Sprint 31A: her görevin ``metadata``'sına, Mission oluşturulurken
        BİR KEZ çözümlenmiş ortak ``target`` (bkz. ``target_resolver.py``)
        eklenir -- böylece HİÇBİR departman kendi başına tekrar
        kategori/URL çözümlemesi yapmak zorunda kalmaz."""

        tasks: list[Task] = []
        # Handlers need the complete original request. GoalSpec.goal is the
        # leading semantic clause; its context/constraints must not erase
        # later execution cues such as bounded exploration and timeframes.
        source_text = mission.title or mission.goal or mission.description
        # Geriye dönük uyumluluk: ``mission.target`` zaten ``MissionEngine.
        # create_mission()`` içinde BİR KEZ dolduruluyor; Mission'ı
        # doğrudan (MissionEngine'i atlayarak) oluşturan eski/test kodu
        # için burada YALNIZCA eksikse anlık olarak çözümlenir -- gerçek
        # akışta bu dal hiç tetiklenmez.
        target = mission.target or TargetResolver().resolve(source_text, mission_type=mission.mission_type)

        # Sprint 33B: AI Validation Pipeline (evaluation/sandbox/integration)
        # çalışıyorsa VE hedef henüz somut bir repoya çözümlenmediyse
        # (CATEGORY), github/evaluation/sandbox/integration'ın (ve README
        # özetinin) AYNI repoyu değerlendirebilmesi için TEK bir "kanıt
        # reposu" (sahip/repo adı -- Target DEĞİL, her departman kendi
        # search()/get_repository() çağrısını ve REPOSITORY/CATEGORY
        # dallanma mantığını KORUR) belirlenir. Yeni bir çözümleme
        # mekanizması İCAT ETMEZ -- ``_resolve_evidence_repo``,
        # Sprint 32'nin ``_resolve_category_repo_target``'ı ile AYNI
        # güvenli-düşme desenini kullanır.
        evidence_repo: Optional[str] = None
        if (
            target.kind == TargetKind.CATEGORY
            and target.category_hint
            and any(name in mission.departments for name in _VALIDATION_DEPARTMENTS)
        ):
            evidence_repo = self._resolve_evidence_repo(target)

        # Sprint 35: AI Strategy Engine'in (Sprint 34) Mission oluşturulurken
        # seçtiği provider'ı (varsa) her görevin metadata'sına ekler -- LLM
        # çağrısı yapan departmanlar (research/finance/media, bkz.
        # ``src.agents.research_agent``/``finance_agent``/``media_agent``)
        # bunu okuyup ZATEN VAR OLAN ``ProviderManager``/``CostOptimizer``
        # üzerinden KULLANIR; yeni bir provider routing İCAT EDİLMEZ.
        # ``mission.ai_strategy`` ``None``'sa (planlama başarısız oldu ya da
        # Mission doğrudan/eski kodla oluşturuldu) hiçbir şey eklenmez -- LLM
        # çağıran departmanlar kendi mevcut varsayılan davranışlarına düşer.
        #
        # Sprint 40 (TASK-LEVEL ROUTING): "tek mission = tek provider"
        # KALDIRILDI -- ``mission.ai_strategy.department_ai_choices`` (ZATEN
        # VAR, bkz. strategy_engine.py) departman başına AYRI hesaplanmış
        # bir karar taşıyorsa ÖNCE o kullanılır; yoksa (ör. LLM
        # gerektirmeyen departman, veya harita boşsa) eski mission-seviyesi
        # ``ai_choice.provider``'a düşülür -- geriye dönük uyumluluk BOZULMAZ.
        fallback_ai_provider: Optional[str] = None
        department_ai_choices: dict = {}
        if mission.ai_strategy is not None:
            fallback_ai_provider = mission.ai_strategy.ai_choice.provider
            department_ai_choices = mission.ai_strategy.department_ai_choices or {}

        for department_name in mission.departments:
            department = self.departments.get(department_name)
            description = department.description if department else "Kayıtlı olmayan departman."
            handler = self.adapters.resolve(department_name)

            if department_name == "browser":
                tasks.extend(
                    self._create_browser_tasks(
                        mission=mission,
                        department_name=department_name,
                        description=description,
                        handler=handler,
                        source_text=source_text,
                        target=target,
                    )
                )
                continue

            metadata = {
                "mission_id": mission.id,
                "department": department_name,
                "department_description": description,
                # Sprint 21 düzeltmesi: GitHub kategori tespiti serbest
                # metin eşleşmesine güvenince hep "ai agent"a düşüyordu
                # (Türkçe metin İngilizce kategori adlarını nadiren
                # içerir). Adaptörlerin (bkz. department_adapters.py)
                # MissionType'a göre daha isabetli bir kategori
                # seçebilmesi için mission türü de veriliyor.
                "mission_type": mission.mission_type,
                # Sprint 31A: TEK, paylaşılan hedef (bkz. yukarısı).
                "target": target,
                # Generic repository Evaluation can support a Finance lab,
                # but Finance's deterministic qualification evidence is the
                # goal-critical gate. Explicit evaluation goals remain critical.
                "goal_critical": not (
                    mission.mission_type == MissionType.FINANCE
                    and department_name == "evaluation"
                    and not any(req.name == "evaluation" for req in mission.completion_requirements)
                ),
            }
            if evidence_repo and department_name in ("github",) + _VALIDATION_DEPARTMENTS:
                metadata["evidence_repo"] = evidence_repo

            department_choice = department_ai_choices.get(department_name)
            preferred_ai_provider = (
                department_choice.provider if department_choice is not None else fallback_ai_provider
            )
            if preferred_ai_provider:
                metadata["preferred_ai_provider"] = preferred_ai_provider

            # JARVIS PRIORITY (Control Center explicit delegation hints):
            # ``mission.execution_hints`` is an ALREADY-VALIDATED (see
            # ``ControlCenterService._validate_execution_hints``), narrow
            # dict -- only ever contains ``preferred_ai_provider`` (a real,
            # registered ``ProviderManager`` name) and/or ``coding_mode`` (an
            # explicit allowlisted value). Applied ONLY to the "coding"
            # department/task -- other departments are completely
            # unaffected, and an explicit hint here deliberately OVERRIDES
            # the AI Strategy Engine's automatic choice (matches existing
            # routing priority: explicit request beats automatic selection).
            if department_name == "coding" and mission.execution_hints:
                hinted_provider = mission.execution_hints.get("preferred_ai_provider")
                if hinted_provider:
                    metadata["preferred_ai_provider"] = hinted_provider
                hinted_coding_mode = mission.execution_hints.get("coding_mode")
                if hinted_coding_mode:
                    metadata["coding_mode"] = hinted_coding_mode

            if department_name == "media":
                from src.media.renderer import has_production_media_capability
                from src.mission.completion import has_youtube_production_intent
                if has_youtube_production_intent(source_text):
                    metadata["artifact_recovery_available"] = True
                if has_production_media_capability(source_text):
                    metadata.update({
                        "provides_capabilities": ("media_artifact",),
                        "safe_use_action": "video_draft",
                    })

            task_target = source_text
            if department_name == "research" and mission.mission_type == MissionType.MEDIA:
                research_department = self.departments.get("research")
                explicit_research_ask = research_department is not None and any(
                    keyword_matches(routing_text(source_text), keyword)
                    for keyword in research_department.keywords
                )
                if not explicit_research_ask:
                    # Research was added FOR the user (topic discovery,
                    # see ``_narrow_media_topic_research``), not explicitly
                    # asked for -- an explicit ask keeps its own wording
                    # (existing ResearchAgent._clean_query behavior).
                    task_target = _media_research_query(source_text)

            department_timeout = _DEPARTMENT_TASK_TIMEOUTS.get(department_name, DEPARTMENT_TASK_TIMEOUT_SECONDS)
            tasks.append(Task(
                title=f"[{department_name}] {mission.title}",
                agent=department_name,
                action=DEPARTMENT_ACTIONS.get(department_name, DEFAULT_DEPARTMENT_ACTION),
                target=task_target,
                priority=mission.priority,
                handler=handler,
                timeout_seconds=department_timeout if handler is not None else None,
                metadata=metadata,
            ))

        # Media must remain runnable when optional opportunity research is
        # unavailable. It can consume persisted KnowledgeBase context and
        # safely produce/block on its own capability gate.

        finance_ids = [task.id for task in tasks if task.agent == "finance"]
        if finance_ids:
            for task in tasks:
                if task.agent == "learning":
                    task.depends_on = list(dict.fromkeys((*task.depends_on, *finance_ids)))

        return tasks

    def _resolve_evidence_repo(self, target: Target) -> Optional[str]:
        """Sprint 33B: bir CATEGORY hedefinin GitHub'daki en kaliteli
        (``GitHubDepartmentAgent``'ın kendi top-listesindeki #1 sırayla
        AYNI ``GitHubIntelligence.score()`` sıralamasını kullanan)
        adayının ``sahip/repo`` adını döndürür -- evaluation/sandbox/
        integration/README özetinin AYNI repoyu değerlendirmesi için TEK
        bir referans noktası üretir. Ağ hatası/sonuç yokluğunda sessizce
        ``None`` döner (``_resolve_category_repo_target`` ile AYNI
        güvenli-düşme deseni) -- çağıranlar bu durumda mevcut (eski)
        davranışlarına (kendi bağımsız arama/seçim mantıkları) düşer."""

        try:
            repos, _ = search_target_repositories(
                self.github_intelligence, target,
                max_results=GITHUB_REPORT_SEARCH_LIMIT,
            )
        except Exception:
            return None

        if not repos:
            return None

        try:
            ranked = sorted(
                repos,
                key=lambda repo: (
                    -self.github_intelligence.score(repo)[0],
                    self.github_intelligence.score(repo)[1],
                ),
            )
        except Exception:
            return None

        return ranked[0].full_name or None

    def _create_browser_tasks(
        self,
        *,
        mission: Mission,
        department_name: str,
        description: str,
        handler,
        source_text: str,
        target: Target,
    ) -> list[Task]:
        """"browser" departmanı için ``_plan_browser_steps`` ile belirlenen
        1-3 adımı, birbirine ``depends_on`` ile bağlı SIRALI görevlere
        çevirir (aynı ``BrowserAgent`` örneği/handler'ı paylaşıldığı için
        ``open`` tamamlanmadan ``list_elements``'ın, o tamamlanmadan
        ``click_index``'in başlamaması gerekir -- ``TaskPlan``/
        ``PlanExecutor`` bu sırayı KENDİSİ zaten uyguluyor, burada
        DEĞİŞTİRİLMEDİ, yalnızca ``depends_on`` kuruluyor).

        Sprint 32: hedef CATEGORY ise (açık bir repo/URL YOKSA), browser
        artık ham metni Google'da aramaz -- ``github``/``evaluation``/vb.
        departmanların ZATEN kullandığı ``GitHubIntelligence.search()``
        ile kategori için GERÇEK ilk adayı bulur ve doğrudan onun GitHub
        sayfasını açıp DOM Engine ile listeler (bkz. ``_resolve_category_
        repo_target``). "Bul/incele/karşılaştır" gibi bir kategori
        araştırması isteğinin doğası gereği açma/listeleme niyeti zaten
        açık olduğundan, bu yolda ayrıca "aç" fiiline gerek YOKTUR."""

        # Önce, ZATEN VAR OLAN mantıkla (URL/liste/index/arama sinyalleri)
        # adımlar hesaplanır -- bu, açık bir "ara"/"listele"/"tıkla"
        # niyetini asla ezmez.
        steps = _plan_browser_steps(source_text, target)

        # Sprint 32: yalnızca bu, GERÇEKTEN sinyalsiz kaldığı için ham
        # metni Google'da aramaya düşecek OLAN CATEGORY hedefinde
        # (ör. "en iyi X reposunu bul/incele/karşılaştır" gibi kategori
        # araştırması istekleri) -- ve kullanıcı açıkça "ara" DEMEDİYSE --
        # bu düşüş, GERÇEK bir GitHub adayını açıp DOM Engine ile
        # listelemekle DEĞİŞTİRİLİR.
        would_fall_back_to_blind_search = steps == [("search", {})]
        if (
            would_fall_back_to_blind_search
            and target.kind == TargetKind.CATEGORY
            and target.category_hint
            and not _has_search_cue(source_text.lower())
        ):
            resolved = self._resolve_category_repo_target(target)
            if resolved is not None:
                steps = [
                    ("open", {"url": resolved.url}),
                    ("list_elements", {}),
                ]

        base_metadata = {
            "mission_id": mission.id,
            "department": department_name,
            "department_description": description,
            "mission_type": mission.mission_type,
            "target": target,
        }

        # Kullanıcı index vermeden listeleme istediyse: click_index
        # ÜRETİLMEZ (kural 5) -- bunun yerine list_elements görevinin
        # başlığına, sistem raporunda görünecek kısa bir not eklenir.
        has_list_step = any(action == "list_elements" for action, _ in steps)
        has_click_step = any(action == "click_index" for action, _ in steps)
        needs_index_selection_note = has_list_step and not has_click_step

        tasks: list[Task] = []
        previous_task: Optional[Task] = None

        for action, extra_metadata in steps:
            title = f"[{department_name}] {mission.title}"
            if action == "list_elements" and needs_index_selection_note:
                title += " (elementler listelendi — devam etmek için kullanıcıdan index seçimi istenmeli)"

            task_metadata = dict(base_metadata)
            task_metadata.update(extra_metadata)

            browser_query = (
                f"{target.requested_name} GitHub"
                if action == "search" and target.requested_name else source_text
            )
            task = Task(
                title=title,
                agent=department_name,
                action=action,
                target=extra_metadata.get("url", browser_query),
                priority=mission.priority,
                handler=handler,
                timeout_seconds=DEPARTMENT_TASK_TIMEOUT_SECONDS if handler is not None else None,
                metadata=task_metadata,
                depends_on=[previous_task.id] if previous_task is not None else [],
            )
            tasks.append(task)
            previous_task = task

        return tasks

    def _resolve_category_repo_target(self, target: Target) -> Optional[Target]:
        """Sprint 32: bir CATEGORY hedefini, GERÇEK bir GitHub aramasıyla
        somut bir REPOSITORY adayına çözer -- "browser Google'a gidiyor"
        sorununu kökten çözer. Yeni bir Tool/Agent İCAT ETMEZ; yalnızca
        github/evaluation/sandbox/integration'ın ZATEN kullandığı
        ``GitHubIntelligence.search()``'ü çağırır ve ilk (en kaliteli)
        sonucu alır. Ağ hatası/sonuç yokluğunda sessizce ``None`` döner
        -- çağıran, mevcut (eski) davranışa (``_plan_browser_steps``)
        güvenli şekilde düşer."""

        try:
            repos, _ = search_target_repositories(
                self.github_intelligence, target, max_results=5,
            )
        except Exception:
            return None

        if not repos:
            return None

        top = repos[0]
        if "/" not in top.full_name:
            return None
        owner, repo = top.full_name.split("/", 1)

        return Target(
            kind=TargetKind.REPOSITORY,
            owner=owner,
            repo=repo,
            full_name=top.full_name,
            url=top.url,
            category_hint=target.category_hint,
        )

    # --- Dağıtım (gerçek Execution Engine'e devir) --------------------------------

    def dispatch(
        self,
        mission: Mission,
        plan: TaskPlan,
        *,
        cancel_on_failure: bool = False,
    ) -> PlanExecutionReport:
        """Görevleri KENDİSİ ÇALIŞTIRMAZ — ``plan``'ı gerçek Execution
        Engine'e (``PlanExecutor`` + ``JobManager``) devreder.

        Sprint 15: ``create_tasks()`` artık her görevin ``handler``'ını
        (varsa) gerçek bir modüle bağlıyor (bkz. ``department_adapters.py``).
        Arkasında GERÇEK bir alt sistemi olan departmanlar (github,
        evaluation, sandbox, integration, research, finance, browser)
        gerçekten çalışır; hâlâ karşılığı olmayanlar (ör. automation,
        media, social_media, security, learning, coding) öncekiyle AYNI
        şekilde "handler tanımlı değil" ile başarısız tamamlanır — yeni
        bir AI/worker İCAT EDİLMEDİ (bkz. rapor).
        """

        mission.status = MissionStatus.DISPATCHED
        executor = PlanExecutor(JobManager(), cancel_on_failure=cancel_on_failure)
        report = executor.run(plan)
        from src.mission.task_criticality import critical_failures
        report.success = not critical_failures(plan)
        mission.status = MissionStatus.COMPLETED if report.success else MissionStatus.FAILED
        mission.progress = self._compute_progress(plan)

        from src.mission.completion import collect_valid_artifact_paths, evaluate_goal_completion, evidence_progress
        mission.artifact_paths = collect_valid_artifact_paths(mission)
        mission.progress = evidence_progress(mission, mission.progress)
        if report.success and evaluate_goal_completion(mission).missing:
            mission.status = MissionStatus.INCOMPLETE
            report.success = False

        return report

    # --- Sonuç toplama --------------------------------------------------------------

    def collect_results(self, plan: TaskPlan) -> dict:
        return {
            "summary": plan.summary(),
            "results": [
                {
                    "department": task.agent,
                    "status": (
                        "SUPPORTING TASK TIMEOUT"
                        if (task.metadata or {}).get("goal_critical") is False
                        and task.status.value == "failed"
                        and any(cue in (task.error or "").casefold() for cue in ("timeout", "zaman aÅŸ"))
                        else task.status.value
                    ),
                    "attempts": task.attempts,
                    "result": task.result,
                    "error": task.error,
                }
                for task in plan.all_tasks()
            ],
        }

    # --- Rapor -------------------------------------------------------------------

    def build_report(
        self,
        mission: Mission,
        plan: TaskPlan,
        execution_report: PlanExecutionReport,
    ) -> dict:
        collected = self.collect_results(plan)

        return {
            "mission_id": mission.id,
            "title": mission.title,
            "mission_type": mission.mission_type.value,
            "status": mission.status.value,
            "departments": mission.departments,
            "progress": mission.progress,
            "domain_progress": __import__(
                "src.mission.completion", fromlist=["domain_completion"]
            ).domain_completion(mission),
            "confidence": mission.confidence,
            "risk_level": mission.risk_level,
            "task_summary": collected["summary"],
            "department_results": collected["results"],
            "execution_success": execution_report.success,
            "executed_count": len(execution_report.executed),
            "cancelled_count": len(execution_report.cancelled),
            "supporting_task_timeouts": [
                {"department": task.agent, "error": task.error, "status": "SUPPORTING TASK TIMEOUT"}
                for task in plan.all_tasks()
                if (task.metadata or {}).get("goal_critical") is False
                and task.status.value == "failed" and "timeout" in (task.error or "").casefold()
            ],
        }

    # --- Dahili --------------------------------------------------------------------

    @staticmethod
    def _compute_progress(plan: TaskPlan) -> float:
        summary = plan.summary()
        total = sum(summary.values())
        if total == 0:
            return 0.0
        finished = summary.get("completed", 0) + summary.get("failed", 0) + summary.get("cancelled", 0)
        return round(100.0 * finished / total, 1)
