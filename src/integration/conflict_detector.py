from __future__ import annotations

from src.integration.jarvis_scanner import JarvisIndex
from src.integration.models import Conflict

_DEFAULT_SEVERITY = {
    "same_class_name": "MEDIUM",
    "same_module_name": "LOW",
    "provider_conflict": "MEDIUM",
    "tool_conflict": "MEDIUM",
    "duplicate_functionality": "HIGH",
    "license_problem": "HIGH",
    "dependency_conflict": "MEDIUM",
}


def find_conflicts(
    external_modules: dict[str, str],
    external_classes: dict[str, list[str]],
    jarvis_index: JarvisIndex,
    target_module_exists: bool,
    target_module_path: str,
    license_detected: str,
    external_dependencies: dict[str, str],
    jarvis_dependencies: dict[str, str],
) -> list[Conflict]:
    """JARVIS mimarisiyle (``jarvis_index``) harici repo (``external_*``)
    arasındaki 7 çakışma türünü tespit eder. Salt-okunur karşılaştırma —
    hiçbir dosya değiştirilmez/birleştirilmez."""

    conflicts: list[Conflict] = []

    for class_name, ext_paths in external_classes.items():
        existing = jarvis_index.classes.get(class_name)
        if not existing:
            continue

        # src/core'daki bir sınıfla çakışma, mimarinin omurgasını
        # etkileyebileceği için daha ciddi kabul edilir.
        severity = "HIGH" if any(p.startswith("src/core/") for p in existing) else _DEFAULT_SEVERITY["same_class_name"]
        conflicts.append(Conflict(
            type="same_class_name",
            description=f"'{class_name}' sınıfı JARVIS'te zaten mevcut: {', '.join(existing)} (repoda: {', '.join(ext_paths)}).",
            severity=severity,
        ))

        if class_name in jarvis_index.provider_names:
            conflicts.append(Conflict(
                type="provider_conflict",
                description=f"'{class_name}' mevcut bir provider adıyla/sınıfıyla çakışıyor (src/providers).",
                severity=_DEFAULT_SEVERITY["provider_conflict"],
            ))
        if class_name in jarvis_index.tool_names:
            conflicts.append(Conflict(
                type="tool_conflict",
                description=f"'{class_name}' mevcut bir tool adıyla/sınıfıyla çakışıyor (src/tools).",
                severity=_DEFAULT_SEVERITY["tool_conflict"],
            ))

    for module_name, ext_path in external_modules.items():
        existing_path = jarvis_index.modules.get(module_name)
        if existing_path:
            conflicts.append(Conflict(
                type="same_module_name",
                description=f"'{module_name}.py' modülü JARVIS'te zaten mevcut: {existing_path} (repoda: {ext_path}).",
                severity=_DEFAULT_SEVERITY["same_module_name"],
            ))

    if target_module_exists:
        conflicts.append(Conflict(
            type="duplicate_functionality",
            description=f"Hedef modül zaten mevcut ve muhtemelen benzer bir işlevi sağlıyor: {target_module_path}.",
            severity=_DEFAULT_SEVERITY["duplicate_functionality"],
        ))

    if not license_detected.strip():
        conflicts.append(Conflict(
            type="license_problem",
            description="Lisans tespit edilemedi/belirsiz — entegrasyon için hukuki netlik gerekiyor.",
            severity=_DEFAULT_SEVERITY["license_problem"],
        ))

    for name, ext_version in external_dependencies.items():
        jarvis_version = jarvis_dependencies.get(name)
        if jarvis_version and ext_version and jarvis_version != ext_version:
            conflicts.append(Conflict(
                type="dependency_conflict",
                description=f"'{name}' için versiyon çakışması: JARVIS={jarvis_version!r}, repo={ext_version!r}.",
                severity=_DEFAULT_SEVERITY["dependency_conflict"],
            ))

    return conflicts
