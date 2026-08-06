from __future__ import annotations

import os

from src.sandbox.errors import SandboxLimitExceeded
from src.sandbox.fs_utils import is_link, iter_files, read_text_safe
from src.sandbox.manifest_detection import read_package_json
from src.sandbox.security_patterns import LIFECYCLE_SCRIPT_KEYS, SUSPICIOUS_PATTERNS


class SecurityScanResult:
    __slots__ = (
        "suspicious_files", "suspicious_patterns", "network_risk",
        "execution_risk", "dependency_risk",
    )

    def __init__(self) -> None:
        self.suspicious_files: list[str] = []
        self.suspicious_patterns: list[str] = []
        self.network_risk = "LOW"
        self.execution_risk = "LOW"
        self.dependency_risk = "LOW"


def scan_security(sandbox_path: str, max_files: int, max_bytes: int) -> SecurityScanResult:
    """Sandbox'taki dosyaları TARAR (çalıştırmadan) ve şüpheli kalıpları
    (bkz. ``security_patterns.SUSPICIOUS_PATTERNS``) işaretler.

    Symlink/junction'lar takip edilmez (``fs_utils.iter_files``).
    """

    result = SecurityScanResult()
    categories_hit: set[str] = set()
    pattern_hits: set[str] = set()

    # 1) package.json yaşam-döngüsü betikleri (preinstall/postinstall) —
    # klasik tedarik-zinciri saldırı vektörü; yapısal (JSON) kontrol.
    package_json = read_package_json(sandbox_path)
    if package_json:
        scripts = package_json.get("scripts")
        if isinstance(scripts, dict):
            for key in LIFECYCLE_SCRIPT_KEYS:
                script_body = scripts.get(key)
                if isinstance(script_body, str) and script_body.strip():
                    pattern_hits.add(f"package.json '{key}' betiği")
                    categories_hit.add("dependency")
                    result.suspicious_files.append("package.json")
                    for name, regex, category in SUSPICIOUS_PATTERNS:
                        if regex.search(script_body):
                            pattern_hits.add(name)
                            categories_hit.add(category)

    # 2) Symlink/junction envanteri (takip edilmiyor ama raporlanıyor).
    try:
        for dirpath, dirnames, filenames in os.walk(sandbox_path, followlinks=False):
            dirnames[:] = [d for d in dirnames if not is_link(os.path.join(dirpath, d))]
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                if is_link(full_path):
                    rel = os.path.relpath(full_path, sandbox_path)
                    result.suspicious_files.append(f"{rel} (symlink — takip edilmedi)")
    except OSError:
        pass

    # 3) Dosya içeriği taraması (metin dosyaları, boyut/sayı sınırlı).
    try:
        for full_path, _size in iter_files(sandbox_path, max_files=max_files, max_bytes=max_bytes):
            text = read_text_safe(full_path)
            if not text:
                continue

            file_flagged = False
            for name, regex, category in SUSPICIOUS_PATTERNS:
                if regex.search(text):
                    pattern_hits.add(name)
                    categories_hit.add(category)
                    file_flagged = True

            if file_flagged:
                rel = os.path.relpath(full_path, sandbox_path)
                result.suspicious_files.append(rel)
    except SandboxLimitExceeded:
        # Boyut/sayı siniri clone/inspect asamasinda zaten BLOCKED'a
        # cevrilir; guvenlik taramasi kismi sonucla devam eder.
        pass

    result.suspicious_patterns = sorted(pattern_hits)
    result.network_risk = "HIGH" if "network" in categories_hit else "LOW"
    result.execution_risk = "HIGH" if "execution" in categories_hit else "LOW"
    result.dependency_risk = "HIGH" if "dependency" in categories_hit else "LOW"

    return result
