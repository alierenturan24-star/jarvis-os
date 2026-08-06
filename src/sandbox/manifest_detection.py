from __future__ import annotations

import json
import os
from typing import Optional

# Sprint 11'in açıkça istediği 4 manifest + yaygın ekosistem eşdeğerleri.
# Yalnızca TESPİT edilir; hiçbiri okunup ÇALIŞTIRILMAZ.
MANIFEST_FILES = (
    "requirements.txt", "pyproject.toml", "package.json", "Dockerfile",
    "setup.py", "Pipfile", "poetry.lock", "Gemfile", "go.mod", "Cargo.toml",
)


def detect_manifests(sandbox_path: str) -> list[str]:
    """Sandbox kök dizininde bilinen bağımlılık/derleme manifestlerini
    arar (yalnızca dosya varlığı kontrolü — içerik ÇALIŞTIRILMAZ)."""

    try:
        entries = set(os.listdir(sandbox_path))
    except OSError:
        return []

    return [name for name in MANIFEST_FILES if name in entries]


def read_package_json(sandbox_path: str) -> Optional[dict]:
    path = os.path.join(sandbox_path, "package.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def detect_commands(sandbox_path: str, manifests: list[str]) -> tuple[list[str], list[str]]:
    """Bulunan manifestlere göre KURULUM ve TEST komut ÖNERİLERİ üretir.

    Bu komutlar YALNIZCA ÖNERİDİR — ``SandboxManager`` bu sprint
    kapsamında hiçbirini çalıştırmaz (bkz. kural #10).
    """

    install_commands: list[str] = []
    test_commands: list[str] = []

    if "requirements.txt" in manifests:
        install_commands.append("pip install -r requirements.txt")
        test_commands.append("pytest")

    if "pyproject.toml" in manifests:
        install_commands.append("pip install .")
        test_commands.append("pytest")

    if "Pipfile" in manifests:
        install_commands.append("pipenv install")

    if "package.json" in manifests:
        install_commands.append("npm install")
        package_json = read_package_json(sandbox_path)
        scripts = package_json.get("scripts") if package_json else None
        if isinstance(scripts, dict) and "test" in scripts:
            test_commands.append("npm test")
        else:
            test_commands.append("npm test (package.json'da 'test' script'i bulunamadı — tahmini)")

    if "Dockerfile" in manifests:
        install_commands.append("docker build -t <sandbox-image> .")

    if "Gemfile" in manifests:
        install_commands.append("bundle install")
        test_commands.append("bundle exec rspec")

    if "go.mod" in manifests:
        install_commands.append("go mod download")
        test_commands.append("go test ./...")

    if "Cargo.toml" in manifests:
        install_commands.append("cargo build")
        test_commands.append("cargo test")

    # Sırayı koruyarak tekrarları temizle.
    install_commands = list(dict.fromkeys(install_commands))
    test_commands = list(dict.fromkeys(test_commands))

    return install_commands, test_commands


def detect_license(sandbox_path: str) -> str:
    """Kök dizindeki bir LICENSE dosyasının varlığını (ve mümkünse
    ilk satırından türü) tespit eder. Bulunamazsa boş dize döner
    (``license_detected=""`` → "belirsiz" olarak yorumlanır)."""

    from src.sandbox.security_patterns import LICENSE_FILENAMES

    try:
        entries = os.listdir(sandbox_path)
    except OSError:
        return ""

    lower_map = {name.lower(): name for name in entries}

    for candidate in LICENSE_FILENAMES:
        if candidate.lower() in lower_map:
            actual = lower_map[candidate.lower()]
            first_line = _first_meaningful_line(os.path.join(sandbox_path, actual))
            return first_line or actual

    package_json = read_package_json(sandbox_path)
    if package_json and isinstance(package_json.get("license"), str) and package_json["license"].strip():
        return package_json["license"].strip()

    return ""


def _first_meaningful_line(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    return line[:120]
    except OSError:
        pass
    return ""
