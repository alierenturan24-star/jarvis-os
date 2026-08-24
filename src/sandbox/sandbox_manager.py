from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from typing import Optional

from src.evaluation.models import RepoEvaluation
from src.github.models import RepoData
from src.sandbox.errors import SandboxLimitExceeded
from src.sandbox.fs_utils import SANDBOX_ROOT, iter_files, safe_rmtree
from src.sandbox.manifest_detection import detect_commands, detect_license, detect_manifests
from src.sandbox.models import SandboxMode, SandboxResult, SandboxStatus
from src.sandbox.security_scan import scan_security

_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

_LANGUAGE_BY_EXTENSION = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".rb": "Ruby", ".php": "PHP", ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cs": "C#",
}

RELEVANCE_LOW_THRESHOLD = 60.0


class SandboxManager:
    """GitHub Intelligence + Evaluation Engine tarafından uygun bulunan
    repoları, ana JARVIS projesinden TAMAMEN AYRI, geçici bir dizinde
    (sistem geçici klasörü altında) statik olarak inceler.

    Bu sınıf hiçbir harici kodu ÇALIŞTIRMAZ, hiçbir bağımlılık KURMAZ ve
    hiçbir dosyayı ana proje klasörüne KOPYALAMAZ — yalnızca klonlar,
    tarar ve raporlar. ``ISOLATED_EXECUTION`` modu bu sprint kapsamında
    UYGULANMAMIŞTIR (yalnızca mod çözümleme mantığı vardır); Docker
    mevcut olsa ve onaylansa bile pipeline yalnızca statik analiz yapar.
    """

    def __init__(
        self,
        max_repo_size_mb: float = 50.0,
        max_files: int = 5000,
        clone_timeout_seconds: int = 60,
        subprocess_env: Optional[dict[str, str]] = None,
    ) -> None:
        self.max_repo_size_mb = max_repo_size_mb
        self.max_files = max_files
        self.clone_timeout_seconds = clone_timeout_seconds
        self.subprocess_env = subprocess_env
        self._max_bytes = int(max_repo_size_mb * 1024 * 1024)

    # --- 1) Oluşturma ----------------------------------------------------------

    def create(self, repository_url: str) -> SandboxResult:
        """URL'yi doğrular ve ANA PROJENİN DIŞINDA, sistem geçici klasörü
        altında benzersiz bir sandbox dizini ayırır. URL geçersizse
        ``status=FAILED`` (istisna FIRLATILMAZ — kontrollü hata)."""

        parsed = self._parse_github_url(repository_url)

        if parsed is None:
            return SandboxResult(
                repository_name=repository_url or "(boş)",
                repository_url=repository_url or "",
                status=SandboxStatus.FAILED,
                error=f"Geçersiz GitHub URL: {repository_url!r}. Beklenen biçim: https://github.com/<owner>/<repo>",
                recommended_action="REDDEDİLDİ — geçersiz repo adresi.",
            )

        owner, repo_name = parsed
        sandbox_path = str(SANDBOX_ROOT / f"{repo_name}-{uuid.uuid4().hex[:12]}")

        return SandboxResult(
            repository_name=f"{owner}/{repo_name}",
            repository_url=repository_url,
            sandbox_path=sandbox_path,
            status=SandboxStatus.CREATED,
        )

    @staticmethod
    def _parse_github_url(url: str) -> Optional[tuple[str, str]]:
        if not url or not isinstance(url, str):
            return None
        match = _GITHUB_URL_RE.match(url.strip())
        if not match:
            return None
        return match.group("owner"), match.group("repo")

    # --- 2) Klonlama -------------------------------------------------------------

    def clone_repository(self, result: SandboxResult, size_hint_mb: Optional[float] = None) -> SandboxResult:
        """``git clone --depth 1`` ile YALNIZCA ``result.sandbox_path``'e
        (sandbox kökü altında) klonlar. Süre/boyut/dosya sınırları
        aşılırsa ``BLOCKED``; git hatası/timeout'ta ``FAILED`` olur.
        Symlink'ler ``-c core.symlinks=false`` ile düz metin olarak
        checkout edilir (OS-seviyesi link OLUŞTURULMAZ)."""

        if result.status in (SandboxStatus.FAILED, SandboxStatus.BLOCKED):
            return result

        if size_hint_mb is not None and size_hint_mb > self.max_repo_size_mb:
            return self._block(
                result,
                f"Repo boyutu (API tahmini: {size_hint_mb:.1f} MB) sınırı "
                f"({self.max_repo_size_mb:.0f} MB) aşıyor — klonlama başlatılmadı.",
            )

        result.status = SandboxStatus.CLONING

        try:
            os.makedirs(result.sandbox_path, exist_ok=False)
        except OSError as error:
            result.status = SandboxStatus.FAILED
            result.error = f"Sandbox dizini oluşturulamadı: {error}"
            return result

        command = [
            "git", "-c", "credential.helper=", "-c", "core.symlinks=false", "-c", "core.longpaths=true",
            "clone", "--depth", "1", "--single-branch", "--no-tags",
            result.repository_url, result.sandbox_path,
        ]

        try:
            options = {"capture_output": True, "text": True, "timeout": self.clone_timeout_seconds}
            if self.subprocess_env is not None:
                options["env"] = self.subprocess_env
            proc = subprocess.run(command, **options)
        except subprocess.TimeoutExpired:
            safe_rmtree(result.sandbox_path)
            result.status = SandboxStatus.FAILED
            result.error = f"Clone zaman aşımına uğradı ({self.clone_timeout_seconds} sn)."
            return result
        except FileNotFoundError:
            result.status = SandboxStatus.FAILED
            result.error = "git komutu bulunamadı (sistem PATH'inde git yok)."
            return result

        if proc.returncode != 0:
            safe_rmtree(result.sandbox_path)
            result.status = SandboxStatus.FAILED
            result.error = f"git clone başarısız (kod {proc.returncode}): {proc.stderr.strip()[:400]}"
            return result

        # Klon sonrası GERÇEK boyut/dosya sınırı kontrolü (defans-in-derinlik) —
        # API tahmini yoksa/yanlışsa dahi sandbox asla sınırı aşamaz.
        try:
            total_bytes = 0
            file_count = 0
            for _path, size in iter_files(result.sandbox_path, self.max_files, self._max_bytes):
                total_bytes += size
                file_count += 1
        except SandboxLimitExceeded as limit_error:
            safe_rmtree(result.sandbox_path)
            return self._block(result, f"Klonlanan repo sınırı aştı: {limit_error}")

        result.status = SandboxStatus.ANALYZING
        return result

    def _block(self, result: SandboxResult, reason: str) -> SandboxResult:
        result.status = SandboxStatus.BLOCKED
        result.findings.append(reason)
        result.recommended_action = f"REDDEDİLDİ — {reason}"
        return result

    # --- 3) İnceleme -----------------------------------------------------------

    def inspect(self, result: SandboxResult) -> SandboxResult:
        """Dosya sayısı, toplam boyut ve baskın dili ölçer (klonlanmış
        içeriği yalnızca OKUR — hiçbir şey çalıştırmaz)."""

        if result.status != SandboxStatus.ANALYZING or not result.sandbox_path:
            return result

        extension_counts: dict[str, int] = {}
        total_bytes = 0
        file_count = 0

        try:
            for path, size in iter_files(result.sandbox_path, self.max_files, self._max_bytes):
                total_bytes += size
                file_count += 1
                ext = os.path.splitext(path)[1].lower()
                if ext in _LANGUAGE_BY_EXTENSION:
                    language = _LANGUAGE_BY_EXTENSION[ext]
                    extension_counts[language] = extension_counts.get(language, 0) + 1
        except SandboxLimitExceeded as limit_error:
            safe_rmtree(result.sandbox_path)
            return self._block(result, f"İnceleme sırasında sınır aşıldı: {limit_error}")

        result.files_scanned = file_count
        result.total_size_mb = round(total_bytes / (1024 * 1024), 2)
        if extension_counts:
            result.detected_language = max(extension_counts, key=lambda lang: extension_counts[lang])

        return result

    # --- 4) Manifest tespiti -----------------------------------------------------

    def detect_manifests(self, result: SandboxResult) -> SandboxResult:
        if result.status != SandboxStatus.ANALYZING or not result.sandbox_path:
            return result
        result.detected_manifests = detect_manifests(result.sandbox_path)
        result.license_detected = detect_license(result.sandbox_path)
        return result

    # --- 5) Komut önerisi tespiti --------------------------------------------------

    def detect_commands(self, result: SandboxResult) -> SandboxResult:
        if result.status != SandboxStatus.ANALYZING or not result.sandbox_path:
            return result
        install_cmds, test_cmds = detect_commands(result.sandbox_path, result.detected_manifests)
        result.detected_install_commands = install_cmds
        result.detected_test_commands = test_cmds
        return result

    # --- 6) Güvenlik taraması ------------------------------------------------------

    def scan_security(self, result: SandboxResult) -> SandboxResult:
        if result.status != SandboxStatus.ANALYZING or not result.sandbox_path:
            return result

        scan = scan_security(result.sandbox_path, self.max_files, self._max_bytes)
        result.suspicious_files = scan.suspicious_files
        result.suspicious_patterns = scan.suspicious_patterns
        result.network_risk = scan.network_risk
        result.execution_risk = scan.execution_risk
        result.dependency_risk = scan.dependency_risk
        return result

    # --- 7) Risk değerlendirmesi / nihai öneri --------------------------------------

    def evaluate_risk(self, result: SandboxResult) -> SandboxResult:
        if result.status != SandboxStatus.ANALYZING:
            return result

        concerns: list[str] = []

        if result.network_risk == "HIGH":
            concerns.append("ağ üzerinden indir-ve-çalıştır kalıpları bulundu")
        if result.execution_risk == "HIGH":
            concerns.append("kod çalıştırma/sistem değişikliği kalıpları bulundu")
        if result.dependency_risk == "HIGH":
            concerns.append("bağımlılık kurulum betiklerinde (preinstall/postinstall) veya kimlik bilgisi erişiminde risk bulundu")

        license_unclear = not result.license_detected.strip()
        if license_unclear:
            concerns.append("lisans belirsiz")

        if result.mode == SandboxMode.ISOLATED_EXECUTION and (concerns or license_unclear):
            result.mode = SandboxMode.STATIC_ANALYSIS
            result.findings.append(
                "ISOLATED_EXECUTION modu, güvenlik/lisans endişeleri nedeniyle STATIC_ANALYSIS'e düşürüldü."
            )

        if concerns:
            result.recommended_action = (
                "ÇALIŞTIRMA/KURULUM ÖNERİLMEZ — " + "; ".join(concerns) +
                ". Yalnızca STATIC_ANALYSIS ile manuel inceleme yapılabilir."
            )
        else:
            result.recommended_action = (
                "STATIC_ANALYSIS tamamlandı; belirgin bir risk sinyali bulunamadı. "
                "Yine de kurulum/çalıştırma bu sprint kapsamında YAPILMADI ve otomatik yapılmamalıdır."
            )

        result.findings.append(
            f"{result.files_scanned} dosya, {result.total_size_mb} MB tarandı "
            f"(dil: {result.detected_language or 'bilinmiyor'})."
        )
        if result.detected_manifests:
            result.findings.append("Bulunan manifestler: " + ", ".join(result.detected_manifests))
        if result.suspicious_patterns:
            result.findings.append("Şüpheli kalıplar: " + ", ".join(result.suspicious_patterns))

        result.status = SandboxStatus.READY_FOR_REVIEW
        return result

    # --- 8) Temizleme -------------------------------------------------------------

    def cleanup(self, result: SandboxResult) -> SandboxResult:
        """YALNIZCA bu sonucun kendi ``sandbox_path``'ini siler — başka
        HİÇBİR yola (özellikle ana proje klasörüne) dokunmaz.
        ``fs_utils.safe_rmtree`` bunu ek bir güvenlik katmanıyla
        garanti eder (sandbox kökü dışındaki yollar için istisna
        fırlatır)."""

        if result.sandbox_path:
            safe_rmtree(result.sandbox_path)

        result.status = SandboxStatus.CLEANED
        return result

    # --- 9) Uçtan uca pipeline ------------------------------------------------------

    def run_pipeline(
        self,
        repository_url: str,
        evaluation: RepoEvaluation,
        repo: Optional[RepoData] = None,
        mode: SandboxMode = SandboxMode.STATIC_ANALYSIS,
        approved_for_isolated_execution: bool = False,
    ) -> SandboxResult:
        """Uçtan uca: Evaluation Engine kapıları (klonlama ÖNCESİ) →
        create → clone_repository → inspect → detect_manifests →
        detect_commands → scan_security → evaluate_risk.

        ``cleanup()`` OTOMATİK ÇAĞRILMAZ — çağıran, sonucu inceledikten
        sonra açıkça çağırmalıdır (bkz. ``README_FOR_REVIEW`` durumu).
        """

        gate_rejection = self._check_evaluation_gates(evaluation)
        if gate_rejection is not None:
            return SandboxResult(
                repository_name=(repo.full_name if repo else repository_url),
                repository_url=repository_url,
                status=SandboxStatus.BLOCKED,
                mode=SandboxMode.STATIC_ANALYSIS,
                findings=[gate_rejection],
                recommended_action=f"REDDEDİLDİ — {gate_rejection}",
            )

        result = self.create(repository_url)
        if result.status == SandboxStatus.FAILED:
            return result

        result.mode = self._resolve_mode(mode, approved_for_isolated_execution)

        # NOT: RepoData bir boyut (KB) alanı taşımıyor, bu yüzden burada
        # bir ön-klonlama boyut ipucu VERİLMİYOR; boyut/dosya sınırları
        # yalnızca klon SONRASI gerçek ölçümle uygulanıyor (bkz.
        # clone_repository — defans-in-derinlik, ama gerçek). Bilinen bir
        # boyut varsa çağıran ``clone_repository(result, size_hint_mb=...)``'i
        # doğrudan çağırarak ön-kontrolden yararlanabilir.
        result = self.clone_repository(result)
        if result.status in (SandboxStatus.FAILED, SandboxStatus.BLOCKED):
            return result

        result = self.inspect(result)
        if result.status == SandboxStatus.BLOCKED:
            return result

        if repo is not None and repo.language:
            result.detected_language = repo.language

        result = self.detect_manifests(result)
        result = self.detect_commands(result)
        result = self.scan_security(result)

        if repo is not None and repo.license and not result.license_detected:
            result.license_detected = repo.license

        result = self.evaluate_risk(result)
        return result

    def _resolve_mode(self, requested: SandboxMode, approved: bool) -> SandboxMode:
        if requested != SandboxMode.ISOLATED_EXECUTION:
            return SandboxMode.STATIC_ANALYSIS

        if not approved:
            return SandboxMode.STATIC_ANALYSIS

        if shutil.which("docker") is None:
            return SandboxMode.STATIC_ANALYSIS

        # Docker mevcut VE onaylandı — mod ISOLATED_EXECUTION olarak
        # işaretlenir AMA bu sprintte gerçek izole çalıştırma
        # UYGULANMAMIŞTIR; pipeline yine yalnızca statik analiz yapar
        # (evaluate_risk() bunu bulgu olarak da not düşer).
        return SandboxMode.ISOLATED_EXECUTION

    @staticmethod
    def _check_evaluation_gates(evaluation: RepoEvaluation) -> Optional[str]:
        if not evaluation.suitable_for_jarvis:
            return f"Evaluation Engine bu repoyu uygun bulmadı (suitable_for_jarvis=False): {evaluation.recommendation}"
        if evaluation.risk_level == "HIGH":
            return f"Risk seviyesi HIGH — sandbox klonlama öncesinde reddedildi: {evaluation.recommendation}"
        if evaluation.relevance_score < RELEVANCE_LOW_THRESHOLD:
            return f"relevance_score ({evaluation.relevance_score}) eşiğin ({RELEVANCE_LOW_THRESHOLD}) altında — sandbox başlatılmadı."
        return None
