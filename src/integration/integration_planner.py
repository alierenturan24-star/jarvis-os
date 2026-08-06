from __future__ import annotations

import os
import re
from typing import Optional

from src.evaluation.models import RepoEvaluation
from src.integration.conflict_detector import find_conflicts as _find_conflicts
from src.integration.jarvis_scanner import PROJECT_ROOT, JarvisIndex, scan_jarvis_architecture
from src.integration.models import Conflict, IntegrationPlan
from src.integration.risk_calculator import breaking_change_probability, estimate_risk, is_merge_ready
from src.sandbox.code_index import extract_python_symbols
from src.sandbox.errors import SandboxLimitExceeded
from src.sandbox.fs_utils import iter_files
from src.sandbox.models import SandboxResult

SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb"}


class IntegrationPlanner:
    """Sandbox statik analizi (Sprint 11) ve Evaluation Engine sonucundan
    (Sprint 10/10.1) yola çıkarak, bir reponun JARVIS mimarisine
    ENTEGRE EDİLMEDEN ÖNCE ayrıntılı bir plan üretir.

    Bu sınıf hiçbir kod DEĞİŞTİRMEZ, hiçbir dosyayı ana projeye
    KOPYALAMAZ, hiçbir MERGE yapmaz — yalnızca ``IntegrationPlan``
    üretir. JARVIS'in kendi mimarisini (``jarvis_scanner``) yalnızca
    OKUR; hiçbir dosyasını değiştirmez.
    """

    def __init__(self) -> None:
        self._jarvis_index: Optional[JarvisIndex] = None

    def _get_jarvis_index(self) -> JarvisIndex:
        # JARVIS'in kendi mimarisinin AST taraması pahalıdır; bir
        # IntegrationPlanner örneği ömrü boyunca bir kez yapılır.
        if self._jarvis_index is None:
            self._jarvis_index = scan_jarvis_architecture()
        return self._jarvis_index

    # --- Uçtan uca --------------------------------------------------------------

    def analyze(self, sandbox_result: SandboxResult, evaluation: RepoEvaluation) -> IntegrationPlan:
        target_module, target_package, strategy, target_exists = self.detect_target(evaluation)

        external_modules, external_classes = self._extract_external_symbols(sandbox_result)

        conflicts = self.find_conflicts(
            sandbox_result, external_modules, external_classes, target_exists, target_module,
        )

        estimated_files, estimated_changes = self.estimate_changes(sandbox_result, external_modules)

        plan = self.build_plan(
            sandbox_result=sandbox_result,
            evaluation=evaluation,
            target_module=target_module,
            target_package=target_package,
            integration_strategy=strategy,
            target_module_exists=target_exists,
            conflicts=conflicts,
            estimated_files=estimated_files,
            estimated_changes=estimated_changes,
        )

        plan.summary = self.generate_summary(plan)
        return plan

    # --- Hedef tespiti -----------------------------------------------------------

    def detect_target(self, evaluation: RepoEvaluation) -> tuple[str, str, str, bool]:
        """``evaluation.target_module``'ü ( Sprint 10.1'in
        ``module_map.py``'ından gelir) somut bir ``target_package``'e ve
        entegrasyon stratejisine dönüştürür. Dönen 4'lü:
        ``(target_module, target_package, integration_strategy, target_module_exists)``."""

        target_module = evaluation.target_module

        if target_module.startswith("Yeni modül") or target_module.startswith("Bilinmiyor"):
            if "media" in target_module:
                package_hint = "src/media"
            elif "voice" in target_module:
                package_hint = "src/voice"
            else:
                package_hint = "src/<yeni-paket>"
            strategy = (
                f"Yeni bağımsız modül/paket olarak ekle — mevcut mimaride "
                f"doğrudan karşılığı yok (öneri: {package_hint})."
            )
            return target_module, package_hint, strategy, False

        first_token = target_module.split(" ")[0].rstrip("/")
        target_path = PROJECT_ROOT / first_token
        exists = target_path.exists()

        match = re.match(r"^src/([A-Za-z0-9_]+)", first_token)
        package = f"src/{match.group(1)}" if match else first_token

        if exists:
            strategy = f"Mevcut modülü genişlet veya yanına yeni dosya olarak ekle: {first_token}."
        else:
            strategy = f"{package} altında yeni bir dosya olarak ekle: {first_token}."

        return target_module, package, strategy, exists

    # --- Çakışma analizi -----------------------------------------------------------

    def find_conflicts(
        self,
        sandbox_result: SandboxResult,
        external_modules: dict[str, str],
        external_classes: dict[str, list[str]],
        target_module_exists: bool,
        target_module_path: str,
    ) -> list[Conflict]:
        jarvis_index = self._get_jarvis_index()
        jarvis_deps = self._parse_requirements(str(PROJECT_ROOT / "requirements.txt"))
        external_deps = self._read_external_dependencies(sandbox_result)

        return _find_conflicts(
            external_modules=external_modules,
            external_classes=external_classes,
            jarvis_index=jarvis_index,
            target_module_exists=target_module_exists,
            target_module_path=target_module_path,
            license_detected=sandbox_result.license_detected,
            external_dependencies=external_deps,
            jarvis_dependencies=jarvis_deps,
        )

    # --- Değişiklik tahmini -----------------------------------------------------

    def estimate_changes(
        self,
        sandbox_result: SandboxResult,
        external_modules: dict[str, str],
    ) -> tuple[int, int]:
        """``estimated_files``: repoda bulunan KAYNAK KODU dosyası sayısı
        (belge/config değil). ``estimated_changes``: dosya sayısı +
        eklenecek bağımlılık sayısı + önerilen test sayısı + 1 (manifest
        güncellemesi) — kaba bir "dokunma noktası" tahminidir, gerçek
        satır sayısı DEĞİLDİR (kod hiç çalıştırılmadığı için ölçülemez)."""

        estimated_files = 0

        if sandbox_result.sandbox_path and os.path.isdir(sandbox_result.sandbox_path):
            try:
                for path, _size in iter_files(sandbox_result.sandbox_path, max_files=20000, max_bytes=10**9):
                    if os.path.splitext(path)[1].lower() in SOURCE_EXTENSIONS:
                        estimated_files += 1
            except SandboxLimitExceeded:
                pass
        else:
            estimated_files = len(external_modules)

        estimated_changes = (
            estimated_files
            + len(sandbox_result.detected_install_commands)
            + len(sandbox_result.detected_test_commands)
            + 1
        )
        return estimated_files, estimated_changes

    # --- Plan derleme ------------------------------------------------------------

    def build_plan(
        self,
        sandbox_result: SandboxResult,
        evaluation: RepoEvaluation,
        target_module: str,
        target_package: str,
        integration_strategy: str,
        target_module_exists: bool,
        conflicts: list[Conflict],
        estimated_files: int,
        estimated_changes: int,
    ) -> IntegrationPlan:
        risk = estimate_risk(evaluation, sandbox_result, conflicts)
        breaking_prob = breaking_change_probability(conflicts, target_module_exists)
        merge_ready = is_merge_ready(evaluation, sandbox_result, conflicts, risk)

        return IntegrationPlan(
            repository_name=sandbox_result.repository_name,
            repository_url=sandbox_result.repository_url,
            target_module=target_module,
            target_package=target_package,
            integration_strategy=integration_strategy,
            estimated_files=estimated_files,
            estimated_changes=estimated_changes,
            estimated_risk=risk,
            breaking_change_probability=breaking_prob,
            dependencies_required=list(sandbox_result.detected_install_commands),
            license_notes=self._build_license_notes(sandbox_result.license_detected),
            merge_ready=merge_ready,
            conflicts=conflicts,
            required_tests=self._build_required_tests(target_module, sandbox_result),
            migration_steps=self._build_migration_steps(target_package, conflicts, sandbox_result, target_module_exists),
            rollback_plan=self._build_rollback_plan(target_module_exists, target_package),
            summary="",
        )

    # --- Özet -------------------------------------------------------------------

    def generate_summary(self, plan: IntegrationPlan) -> str:
        conflict_note = f"{len(plan.conflicts)} çakışma bulundu" if plan.conflicts else "çakışma bulunamadı"
        merge_note = "merge'e HAZIR" if plan.merge_ready else "merge'e HAZIR DEĞİL"
        return (
            f"{plan.repository_name} → {plan.target_package} "
            f"({plan.integration_strategy}) "
            f"Risk: {plan.estimated_risk}, kırıcı değişiklik olasılığı: %{plan.breaking_change_probability:.0f}. "
            f"{conflict_note}. {merge_note}."
        )

    # --- Dahili yardımcılar --------------------------------------------------------

    @staticmethod
    def _extract_external_symbols(sandbox_result: SandboxResult) -> tuple[dict[str, str], dict[str, list[str]]]:
        if sandbox_result.sandbox_path and os.path.isdir(sandbox_result.sandbox_path):
            return extract_python_symbols(sandbox_result.sandbox_path)
        return {}, {}

    @staticmethod
    def _parse_requirements(path: str) -> dict[str, str]:
        deps: dict[str, str] = {}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(==\s*[A-Za-z0-9_.\-]+)?", line)
                    if match:
                        name = match.group(1).lower()
                        version = match.group(2).replace(" ", "") if match.group(2) else ""
                        deps[name] = version
        except OSError:
            pass
        return deps

    def _read_external_dependencies(self, sandbox_result: SandboxResult) -> dict[str, str]:
        if not sandbox_result.sandbox_path or "requirements.txt" not in sandbox_result.detected_manifests:
            return {}
        return self._parse_requirements(os.path.join(sandbox_result.sandbox_path, "requirements.txt"))

    @staticmethod
    def _build_license_notes(license_detected: str) -> str:
        if not license_detected.strip():
            return "Lisans tespit edilemedi — entegrasyondan önce reponun lisans durumu manuel olarak doğrulanmalı."
        lowered = license_detected.lower()
        if any(k in lowered for k in ("mit", "apache", "bsd", "isc", "mpl")):
            return f"İzinli lisans tespit edildi: {license_detected!r}. JARVIS'e entegrasyon için uygun görünüyor."
        if "gpl" in lowered:
            return f"Copyleft lisans tespit edildi: {license_detected!r}. Entegrasyon öncesi hukuki inceleme ÖNERİLİR (kaynak açma yükümlülüğü olabilir)."
        return f"Tanınan bir SPDX kalıbına uymayan lisans metni: {license_detected!r}. Manuel inceleme gerekir."

    @staticmethod
    def _build_required_tests(target_module: str, sandbox_result: SandboxResult) -> list[str]:
        tests = ["Yeni/genişletilen modül için birim testleri yaz."]
        if sandbox_result.detected_test_commands:
            tests.append(
                "Reponun kendi test takımını referans al: "
                + ", ".join(sandbox_result.detected_test_commands)
                + " (öneri — bu sprintte ÇALIŞTIRILMADI)."
            )
        if not target_module.startswith("Yeni modül") and not target_module.startswith("Bilinmiyor"):
            tests.append(f"{target_module} için mevcut regresyon testlerinin tekrar çalıştırılması.")
        tests.append("Tüm mevcut JARVIS test paketinin (pytest) regresyonsuz geçtiğini doğrula.")
        return tests

    @staticmethod
    def _build_migration_steps(
        target_package: str,
        conflicts: list[Conflict],
        sandbox_result: SandboxResult,
        target_module_exists: bool,
    ) -> list[str]:
        steps = [
            "Sandbox'ın statik analiz bulgularını (şüpheli kalıplar dahil) insan gözden geçirmesiyle doğrula.",
            "Lisans uyumluluğunu hukuki/politika açısından teyit et.",
        ]
        if target_module_exists:
            steps.append(f"{target_package} altındaki mevcut kodla işlevsel örtüşmeyi değerlendir (duplicate functionality riski).")
        steps.append(f"{target_package} altında yeni dosya(lar) oluştur (veya mevcut dosyayı genişlet).")
        if sandbox_result.detected_install_commands:
            steps.append("Gerekli bağımlılıkları requirements.txt'ye ekle: " + ", ".join(sandbox_result.detected_install_commands) + ".")
        if conflicts:
            types = sorted({c.type for c in conflicts})
            steps.append("Şu çakışma türlerini çöz: " + ", ".join(types) + ".")
        steps.append("Gerekli testleri yaz ve mevcut test paketini regresyon için çalıştır.")
        steps.append("Küçük, gözden geçirilebilir bir PR ile entegre et (bu araç PR açmaz veya merge yapmaz).")
        return steps

    @staticmethod
    def _build_rollback_plan(target_module_exists: bool, target_package: str) -> str:
        if target_module_exists:
            return (
                f"{target_package} altındaki mevcut dosyalar değiştirileceği için geri alma "
                "git revert/checkout ile yapılmalı; değişiklik öncesi bir yedek dal alınması önerilir."
            )
        return (
            f"Yeni eklenen {target_package} dosyaları/dizini silinir, requirements.txt'ye "
            "eklenen bağımlılıklar geri alınır, ilgili import/registration satırları kaldırılır. "
            "Mevcut modüller değiştirilmediği için geri alma riski düşüktür."
        )
