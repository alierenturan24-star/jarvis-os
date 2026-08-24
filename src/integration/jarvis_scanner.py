from __future__ import annotations

from pathlib import Path

from src.sandbox.code_index import extract_python_symbols

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Planner'ın taramaya YETKİLİ olduğu tek klasör kümesi. Bunların dışına
# ASLA çıkılmaz ve hiçbir dosya bu taramada DEĞİŞTİRİLMEZ — yalnızca
# okunur (AST ile ayrıştırma, import/çalıştırma YOK).
#
# Sprint 41 (LOCAL CODE INTELLIGENCE): "src/strategy" (AIStrategyEngine/
# CostOptimizer'ın tier mantığı) ve "src/mission" (Mission/Department
# orchestration) eklendi -- bu iki paket Sprint 34-40'ta oluşturuldu,
# önceki liste bunlardan HABERSİZDİ. Yeni bir tarayıcı İCAT EDİLMEDİ,
# yalnızca ZATEN VAR OLAN taramanın yetki alanı genişletildi.
JARVIS_SCAN_FOLDERS = (
    "src/core", "src/providers", "src/tools", "src/agents",
    "src/github", "src/evaluation", "src/sandbox",
    "src/strategy", "src/mission",
)


class JarvisIndex:
    """JARVIS'in kendi mimarisinin salt-okunur bir anlık görüntüsü."""

    def __init__(self) -> None:
        self.modules: dict[str, str] = {}
        self.classes: dict[str, list[str]] = {}
        self.provider_names: set[str] = set()
        self.tool_names: set[str] = set()


def scan_jarvis_architecture() -> JarvisIndex:
    """``JARVIS_SCAN_FOLDERS``'ı salt-okunur şekilde tarar ve bir
    ``JarvisIndex`` döndürür. Hiçbir dosyayı DEĞİŞTİRMEZ."""

    index = JarvisIndex()

    for folder in JARVIS_SCAN_FOLDERS:
        full_path = PROJECT_ROOT / folder
        if not full_path.is_dir():
            continue

        modules, classes = extract_python_symbols(str(full_path))

        for name, rel_path in modules.items():
            index.modules.setdefault(name, f"{folder}/{rel_path}".replace("\\", "/"))
        for name, rel_paths in classes.items():
            index.classes.setdefault(name, [])
            index.classes[name].extend(f"{folder}/{p}".replace("\\", "/") for p in rel_paths)

        if folder == "src/providers":
            index.provider_names.update(modules.keys())
            index.provider_names.update(classes.keys())
        if folder == "src/tools":
            index.tool_names.update(modules.keys())
            index.tool_names.update(classes.keys())

    return index
