from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.config.settings import PROJECT_ROOT, Settings
from src.providers.base_provider import BaseProvider

if TYPE_CHECKING:
    # Yalnızca statik tip kontrolü için -- ``from __future__ import
    # annotations`` sayesinde çalışma zamanında hiç değerlendirilmez.
    # Modül seviyesinde GERÇEKTEN import EDİLMEZ: ``src.mission.
    # failure_classification`` kendisi zararsız (src.* bağımlılığı yok)
    # olsa da, onu import etmek ``src.mission`` PAKETİNİN ``__init__.py``'sini
    # (department_orchestrator -> department_adapters -> finance/media/
    # research agent'ları -> ``src.providers.router`` -> BU dosyanın ait
    # olduğu ``src.providers.provider_manager``) TETİKLER -- bu da tam bir
    # DAİRESEL import oluşturur (``execution_planner.py``'nin ``tools_for_
    # department`` için kullandığı fonksiyon-yerel import deseniyle AYNI
    # sebep/çözüm, bkz. o dosyadaki not). Bu yüzden ``classify_failure``/
    # ``FailureClass`` her kullanıldığı fonksiyonun İÇİNDE import edilir.
    from src.mission.failure_classification import FailureClass

# Sprint 44 (CLAUDE CODE WORKER BRIDGE): JARVIS'in kullanabileceği kontrollü
# bir WORKER olarak, yerelde kurulu ve GİRİŞ YAPILMIŞ ``claude`` komut
# satırı aracını çağıran köprü. ``anthropic_provider.py``'DEN (Anthropic
# Messages API'sine doğrudan HTTP/API-anahtarı ile bağlanan AYRI bir
# sağlayıcı) TAMAMEN FARKLIDIR -- burada yeni bir API anahtarı/hesap/ödeme
# OLUŞTURULMAZ, yalnızca zaten kimlik doğrulanmış CLI oturumu ÇAĞRILIR.
#
# GÜVENLİK KURALLARI (Sprint 44 bölüm 4/16, KASITLI olarak sabit):
#   - ``shell=True`` KULLANILMAZ -- argüman LİSTESİ ile çağrılır.
#   - ``--dangerously-skip-permissions``/``--allow-dangerously-skip-permissions``
#     ASLA kullanılmaz -- varsayılan ``--permission-mode plan`` (salt-okunur/
#     planlama modu, dosya değiştirmez) ile çağrılır.
#   - commit/push/credential/API-key/ödeme/hesap işlemleri bu worker'ın
#     KAPSAMI DIŞINDADIR -- JARVIS bu worker'ı bu amaçla asla ÇAĞIRMAZ
#     (mevcut ``DecisionEngine`` onay sınırları DEĞİŞTİRİLMEDİ).

CLAUDE_CODE_EXECUTABLE_NAME = "claude"

# Sprint 38'in Ollama/JobManager "inner < outer" timeout yarışı dersi:
# subprocess'in KENDİ timeout'u, Task Engine'in dış timeout'undan HER ZAMAN
# daha KISA olmalı -- aksi halde dış timeout tetiklendiğinde subprocess
# arka planda ÇALIŞMAYA DEVAM eder (Python'da zorla durdurma yoktur), aynı
# yarış hatası TEKRAR EDER.
#
# Sprint 45 (CLAUDE CODE TIMEOUT FIX): sabit ``60.0`` yerine
# ``Settings.CLAUDE_CODE_TIMEOUT_SECONDS`` (bkz. src/config/settings.py --
# ortam değişkeniyle yapılandırılabilir ama [30, 600] sn ile SINIRLI, bozuk
# değer güvenli varsayılana düşer). "coding" departmanının KENDİ dış
# timeout'u (``CODING_DEPARTMENT_TASK_TIMEOUT_SECONDS``, bkz.
# ``src/mission/department_orchestrator.py``) bu değere GÖRE hesaplanır --
# paylaşılan ``DEPARTMENT_TASK_TIMEOUT_SECONDS`` (github/evaluation/sandbox/
# integration gibi CLI'ye hiç dokunmayan departmanlar için) KASITLI OLARAK
# değiştirilmedi, yalnızca "coding" departmanı daha geniş bir bütçe alır.
DEFAULT_TIMEOUT_SECONDS = Settings.CLAUDE_CODE_TIMEOUT_SECONDS

# "plan" -- Claude Code'un kendi ``--permission-mode`` seçeneklerinden biri
# (bkz. ``claude --help``): araç kullanımını salt-okunur/planlama ile
# sınırlar, dosya DEĞİŞTİRMEZ. İlk sürümün amacı (Sprint 44 bölüm 4) analiz/
# kod inceleme/çözüm önerisi olduğu için GÜVENLİ varsayılan budur.
DEFAULT_PERMISSION_MODE = "plan"

# JARVIS PRIORITY (Claude Code repo-edit delegation, Mode B): ``run_edit``'in
# kullandığı, dosya DEĞİŞTİRMESİNE izin veren AYRI mod. ``--allowedTools``
# bilinçli olarak bir İZİN LİSTESİDİR (deny-list DEĞİL) -- ``claude --help``
# ile doğrulanmış GERÇEK bir bayrak; yalnızca dosya okuma/düzenleme
# araçlarını içerir, Bash/WebFetch/Task/MCP KATEGORİK olarak dışarıda
# bırakılır. Bu sayede alt süreç git/shell komutlarını KENDİSİ hiçbir zaman
# çalıştıramaz (destructive git action'lar mimari olarak İMKANSIZ hale
# gelir, yalnızca ActionPolicy'ye güvenilmez).
EDIT_PERMISSION_MODE = "acceptEdits"
EDIT_ALLOWED_TOOLS = "Read,Edit,Write,Glob,Grep"

# Savunma derinliği: ``run_edit`` çağıranın ZORUNLU olarak verdiği ``cwd``
# gerçekten var olan bir dizin olmalı VE bu iyi bilinen tehlikeli köklerden
# biri OLMAMALI. Bu, ActionPolicy onayının YERİNE geçmez -- onun ÜZERİNE
# eklenen ikinci bir sınırdır.
_DANGEROUS_CWD_NAMES = {"windows", "system32", "program files", "program files (x86)"}

# Claude Code'un GERÇEK kullanım/session-limit hata metninin TAM biçimi bu
# ortamda doğrulanamadı (gerçek kotayı tüketmeden test edilemez, Sprint 44
# bölüm 13 bunu YASAKLIYOR). Bu yüzden yaygın İngilizce limit ifadelerini
# tanıyan, dürüstçe GENİŞ bir sezgisel kullanılıyor -- ikinci bir
# sınıflandırma sözlüğü İCAT EDİLMEDİ, yalnızca ZATEN VAR OLAN
# ``classify_failure``'ın tanıdığı Türkçe metne ÇEVRİLİYOR.
_LIMIT_SIGNALS = ("usage limit", "rate limit", "quota", "too many requests", "429")

# CANLI TESTTE BULUNAN GERÇEK HATA (Sprint 44): ``subprocess.run`` varsayılan
# olarak TÜM ebeveyn ortam değişkenlerini miras alır. JARVIS'in ``.env``
# dosyası ``anthropic_provider.py`` (AYRI, HTTP tabanlı Anthropic API
# sağlayıcısı) için ``ANTHROPIC_MODEL=claude-sonnet-4`` tanımlıyor --
# ``src.config.settings`` import edildiğinde (``PROJECT_ROOT`` için, bkz.
# ``ClaudeCodeWorker.__init__``) bu ``load_dotenv()`` ile ``os.environ``'a
# YAZILIYOR. Claude Code CLI'nin KENDİSİ de ``ANTHROPIC_MODEL`` ortam
# değişkenini okuyor ve "claude-sonnet-4" CLI için geçerli bir model
# olmadığından HER ÇAĞRIDA 404 ile başarısız oluyordu (canlı testte
# yakalandı). Çözüm: subprocess'e JARVIS'in kendi Anthropic-API'ye özgü
# ortam değişkenleri OLMADAN temiz bir ortam kopyası verilir -- CLI'nin
# KENDİ kimlik doğrulaması/model seçimi (zaten giriş yapılmış oturum)
# ETKİLENMEZ.
_ENV_VARS_TO_STRIP = ("ANTHROPIC_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")


def _clean_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _ENV_VARS_TO_STRIP:
        env.pop(key, None)
    return env


@dataclass
class ClaudeCodeResult:
    """``RouteResult`` (bkz. ``src/providers/provider_manager.py``) ile AYNI
    ruhtaki, Claude Code'a özgü yapılandırılmış sonuç. ``src.jobs.task_result.
    TaskResult``'ın YERİNE GEÇMEZ (Task Engine hâlâ onu kullanır) -- yalnızca
    ham subprocess çağrısının gözlenebilir ayrıntılarını (Sprint 44 bölüm 5:
    success/output/stderr/exit_code/duration/failure_class/session) taşıyan,
    üçüncü bir "sonuç sistemi" DEĞİL, dar kapsamlı tek bir dataclass."""

    success: bool
    output: str  # başarıda GERÇEK cevap, başarısızlıkta HATA METNİ (mevcut provider konvansiyonu)
    stderr: str
    exit_code: Optional[int]
    duration_seconds: float
    failure_class: FailureClass
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None


@dataclass
class ClaudeCodeEditResult:
    """``ClaudeCodeResult`` ile AYNI alanlar + ``run_edit``'e ÖZGÜ
    ``files_changed`` (salt-okunur ``git status --porcelain`` ile tespit
    edilen, düzenleme sonrası değişen dosya YOLLARI -- Claude Code'un
    KENDİSİ raporlamıyor, JARVIS ayrıca ve salt-okunur şekilde tespit
    ediyor). Onay/test-çalıştırma gibi POLİTİKA kavramları BİLEREK burada
    YOKTUR -- bunlar ``src.agents.claude_code_edit_adapter``'ın
    sorumluluğudur (bkz. o modülün docstring'i)."""

    success: bool
    output: str
    stderr: str
    exit_code: Optional[int]
    duration_seconds: float
    failure_class: FailureClass
    files_changed: tuple[str, ...] = ()
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None


def _validate_edit_cwd(cwd: Path) -> Optional[str]:
    """``run_edit``'in çalışma dizini için savunma-derinliği kontrolü.
    Sorun yoksa ``None``, varsa insan-okur bir hata metni döner (çağıran
    bunu ``ClaudeCodeEditResult(success=False, ...)`` içine koyar)."""

    resolved = cwd.resolve()

    if not resolved.is_dir():
        return f'Geçersiz çalışma dizini: "{resolved}" bir dizin değil veya mevcut değil.'

    if resolved == resolved.anchor or resolved.parent == resolved:
        return f'Güvenlik: kök dizinde ("{resolved}") düzenleme YAPILMAZ.'

    if resolved == Path.home().resolve():
        return "Güvenlik: kullanıcı ana dizininin KÖKÜNDE düzenleme yapılmaz."

    if resolved.name.casefold() in _DANGEROUS_CWD_NAMES:
        return f'Güvenlik: sistem dizininde ("{resolved}") düzenleme YAPILMAZ.'

    return None


def _git_status_files_changed(cwd: Path, timeout_seconds: float = 10.0) -> tuple[str, ...]:
    """``cwd`` sınırlı, SALT-OKUNUR ``git status --porcelain`` -- hiçbir
    dosyayı DEĞİŞTİRMEZ/COMMIT ETMEZ, yalnızca hangi dosyaların değiştiğini
    okur. Git deposu değilse veya komut başarısız olursa (repo yok, git
    kurulu değil vb.) sessizce boş tuple döner -- ``run_edit``'in BAŞARI
    durumunu bu tespit etkilemez (dürüst-ama-en-iyi-çaba raporlama)."""

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout_seconds, cwd=str(cwd), shell=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ()

    if proc.returncode != 0:
        return ()

    files: list[str] = []
    for line in (proc.stdout or "").splitlines():
        stripped = line[3:].strip() if len(line) > 3 else line.strip()
        if stripped:
            files.append(stripped)

    return tuple(files[:50])


class ClaudeCodeWorker:
    """``claude`` CLI'sini kontrollü bir subprocess olarak çalıştırır.

    Deseni ``src.sandbox.sandbox_manager.SandboxManager.clone_repository``
    ile BİREBİR AYNIDIR (``capture_output=True, text=True, timeout=...``,
    ``TimeoutExpired``/``FileNotFoundError``/sıfır-olmayan ``returncode``
    AYRI ele alınır, hiçbir hata dışarı FIRLATILMAZ) -- yeni bir subprocess
    deseni İCAT EDİLMEDİ.
    """

    def __init__(
        self,
        *,
        executable: Optional[str] = None,
        cwd: Optional[Path] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        permission_mode: str = DEFAULT_PERMISSION_MODE,
    ) -> None:
        self._executable_override = executable
        # Sprint 44 bölüm 3: proje root'u HARD-CODE EDİLMEDİ -- mevcut
        # ``src.config.settings.PROJECT_ROOT`` (``Path(__file__).resolve().
        # parents[2]``, ``jarvis_scanner.py``'nin de kullandığı AYNI desen)
        # yeniden kullanıldı.
        self.cwd = cwd or PROJECT_ROOT
        self.timeout_seconds = timeout_seconds
        self.permission_mode = permission_mode

    def _resolve_executable(self) -> Optional[str]:
        if self._executable_override:
            return self._executable_override
        return shutil.which(CLAUDE_CODE_EXECUTABLE_NAME)

    def is_available(self) -> bool:
        return self._resolve_executable() is not None

    def run(
        self,
        prompt: str,
        *,
        resume_session_id: Optional[str] = None,
        permission_mode: Optional[str] = None,
    ) -> ClaudeCodeResult:
        """Sprint 44 bölüm 6 (SESSION CONTINUATION): ``resume_session_id``
        verilirse ``--resume <id>`` eklenir (CLI'nin GERÇEK, ``claude
        --help`` ile doğrulanmış ``-r/--resume`` seçeneği). Task/Mission
        kimliğiyle OTOMATİK ilişkilendirme YAPILMAZ -- ``BaseProvider.
        generate(prompt, model=None)`` sözleşmesinde görev/mission kimliği
        HİÇ YOKTUR; bunu değiştirmek TÜM sağlayıcıları etkileyecek büyük bir
        değişiklik olurdu (Sprint 44 bölüm 15: minimal blast radius).
        Çağıran, dönen ``session_id``'yi kendi ``task.metadata``'sına
        yazıp bir SONRAKİ çağrıda ``resume_session_id`` olarak geçebilir --
        mekanizma BURADA sağlanıyor, otomatik bağlama bilinçli olarak
        bırakıldı (dürüstçe raporlanıyor, bkz. Sprint 44 final rapor)."""

        from src.mission.failure_classification import classify_failure

        executable = self._resolve_executable()

        if executable is None:
            text = f'Claude Code CLI bulunamadı (PATH\'te "{CLAUDE_CODE_EXECUTABLE_NAME}" yok).'
            return ClaudeCodeResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=0.0, failure_class=classify_failure(text),
            )

        command = [
            executable, "-p", prompt,
            "--output-format", "json",
            "--permission-mode", permission_mode or self.permission_mode,
        ]
        if resume_session_id:
            command.extend(["--resume", resume_session_id])

        started = time.monotonic()

        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout_seconds, cwd=str(self.cwd), shell=False,
                env=_clean_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            text = f"Claude Code zaman aşımına uğradı ({self.timeout_seconds:.0f} sn)."
            return ClaudeCodeResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=round(time.monotonic() - started, 2),
                failure_class=classify_failure(text),
            )
        except FileNotFoundError:
            text = f'Claude Code CLI bulunamadı ("{executable}" çalıştırılamadı).'
            return ClaudeCodeResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=round(time.monotonic() - started, 2),
                failure_class=classify_failure(text),
            )

        return self._parse_result(proc, round(time.monotonic() - started, 2))

    def run_edit(
        self,
        prompt: str,
        *,
        cwd: Path,
        resume_session_id: Optional[str] = None,
    ) -> ClaudeCodeEditResult:
        """Mode B (repo-edit) -- ``run()``'ın salt-okunur ``plan`` modunun
        AKSİNE, dosya DEĞİŞTİRMESİNE izin verir. ``cwd`` BİLEREK ZORUNLU
        keyword-only argümandır (``self.cwd``'ye sessizce DÜŞMEZ) -- her
        çağıranın sınırı AÇIKÇA belirtmesini zorunlu kılar. Onay/politika
        kontrolü BURADA YAPILMAZ -- çağıran (``src.agents.
        claude_code_edit_adapter``) bu metodu çağırmadan ÖNCE
        ``ActionPolicy`` onayını ZATEN almış olmalıdır.

        Güvenlik (bkz. modül-üstü not): ``--allowedTools`` bir İZİN
        LİSTESİDİR (Read/Edit/Write/Glob/Grep) -- Bash/WebFetch/Task/MCP
        KATEGORİK olarak dışarıda, alt süreç git/shell komutu ÇALIŞTIRAMAZ.
        ``--dangerously-skip-permissions`` yine ASLA kullanılmaz.
        """

        from src.mission.failure_classification import classify_failure

        boundary_error = _validate_edit_cwd(cwd)
        if boundary_error is not None:
            return ClaudeCodeEditResult(
                success=False, output=boundary_error, stderr="", exit_code=None,
                duration_seconds=0.0, failure_class=classify_failure(boundary_error),
            )

        executable = self._resolve_executable()

        if executable is None:
            text = f'Claude Code CLI bulunamadı (PATH\'te "{CLAUDE_CODE_EXECUTABLE_NAME}" yok).'
            return ClaudeCodeEditResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=0.0, failure_class=classify_failure(text),
            )

        resolved_cwd = cwd.resolve()
        command = [
            executable, "-p", prompt,
            "--output-format", "json",
            "--permission-mode", EDIT_PERMISSION_MODE,
            "--allowedTools", EDIT_ALLOWED_TOOLS,
        ]
        if resume_session_id:
            command.extend(["--resume", resume_session_id])

        started = time.monotonic()

        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout_seconds, cwd=str(resolved_cwd), shell=False,
                env=_clean_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            text = f"Claude Code zaman aşımına uğradı ({self.timeout_seconds:.0f} sn)."
            return ClaudeCodeEditResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=round(time.monotonic() - started, 2),
                failure_class=classify_failure(text),
            )
        except FileNotFoundError:
            text = f'Claude Code CLI bulunamadı ("{executable}" çalıştırılamadı).'
            return ClaudeCodeEditResult(
                success=False, output=text, stderr="", exit_code=None,
                duration_seconds=round(time.monotonic() - started, 2),
                failure_class=classify_failure(text),
            )

        return self._parse_edit_result(proc, round(time.monotonic() - started, 2), resolved_cwd)

    def _parse_edit_result(
        self, proc: "subprocess.CompletedProcess[str]", duration: float, cwd: Path,
    ) -> ClaudeCodeEditResult:
        base = self._parse_result(proc, duration)
        files_changed = _git_status_files_changed(cwd) if base.success else ()
        return ClaudeCodeEditResult(
            success=base.success, output=base.output, stderr=base.stderr,
            exit_code=base.exit_code, duration_seconds=base.duration_seconds,
            failure_class=base.failure_class, files_changed=files_changed,
            session_id=base.session_id, cost_usd=base.cost_usd,
        )

    def _parse_result(self, proc: "subprocess.CompletedProcess[str]", duration: float) -> ClaudeCodeResult:
        from src.mission.failure_classification import FailureClass, classify_failure

        stderr = (proc.stderr or "").strip()

        if proc.returncode != 0:
            detail = stderr[:400] or "(stderr boş)"
            text = f"claude_code sağlayıcı hatası (kod {proc.returncode}): {detail}"
            return ClaudeCodeResult(
                success=False, output=text, stderr=stderr, exit_code=proc.returncode,
                duration_seconds=duration,
                failure_class=self._classify_cli_error(f"{stderr} {proc.stdout or ''}", text),
            )

        try:
            data = json.loads(proc.stdout or "{}")
        except (ValueError, TypeError) as error:
            text = f"claude_code sağlayıcı hatası: JSON çıktısı ayrıştırılamadı ({error})."
            return ClaudeCodeResult(
                success=False, output=text, stderr=stderr, exit_code=proc.returncode,
                duration_seconds=duration, failure_class=classify_failure(text),
            )

        is_error = bool(data.get("is_error"))
        result_text = str(data.get("result") or "")
        session_id = data.get("session_id")
        cost_usd = data.get("total_cost_usd")

        if is_error or not result_text:
            detail = result_text or str(data.get("subtype") or "bilinmeyen hata")
            text = f"claude_code sağlayıcı hatası: {detail}"
            return ClaudeCodeResult(
                success=False, output=text, stderr=stderr, exit_code=proc.returncode,
                duration_seconds=duration,
                failure_class=self._classify_cli_error(f"{result_text} {stderr}", text),
                session_id=session_id, cost_usd=cost_usd,
            )

        return ClaudeCodeResult(
            success=True, output=result_text, stderr=stderr, exit_code=proc.returncode,
            duration_seconds=duration, failure_class=FailureClass.UNKNOWN,
            session_id=session_id, cost_usd=cost_usd,
        )

    @staticmethod
    def _classify_cli_error(raw_text: str, fallback_text: str) -> "FailureClass":
        from src.mission.failure_classification import classify_failure

        lowered = raw_text.casefold()
        if any(signal in lowered for signal in _LIMIT_SIGNALS):
            return classify_failure(f"Claude Code kullanım kotası aşıldı (limit aşıldı): {raw_text[:200]}")
        return classify_failure(fallback_text)


class ClaudeCodeProvider(BaseProvider):
    """``BaseProvider`` sözleşmesine uyan ince bir uyumluluk katmanı --
    ``ProviderManager._providers`` içine ZATEN VAR OLAN diğer 8 sağlayıcıyla
    AYNI şekilde ``"claude_code"`` anahtarıyla kaydedilir (``"claude"``
    DEĞİL -- o zaten ``ALIASES`` üzerinden ``anthropic``'e (HTTP API)
    eşleniyor, çakışma OLMAMASI için farklı ad kullanıldı). Bu kayıt tek
    başına task-type routing/``CostOptimizer``/``ProviderExecutionHistory``/
    Sprint 42-43 recovery merdivenine katılımı SAĞLAR -- ``ceo.py``'ye
    HİÇ dokunulmadı."""

    def __init__(self, worker: Optional[ClaudeCodeWorker] = None) -> None:
        super().__init__("claude_code")
        self.worker = worker or ClaudeCodeWorker()
        # Sprint 44 bölüm 5: ``generate()`` sözleşmesi yalnızca ``str``
        # döndürdüğü için (TÜM provider'larla AYNI, DEĞİŞTİRİLMEDİ),
        # yapılandırılmış ayrıntılar (stderr/exit_code/session_id/cost_usd)
        # burada AYRICA saklanır -- ihtiyaç duyan çağıranlar (ör. canlı
        # test/rapor) okuyabilir, provider arayüzü BOZULMAZ.
        self.last_result: Optional[ClaudeCodeResult] = None

    def is_available(self) -> bool:
        return self.worker.is_available()

    def generate(self, prompt: str, model: str | None = None) -> str:
        result = self.worker.run(prompt)
        self.last_result = result
        return result.output
