from __future__ import annotations

import ast
import os

from src.sandbox.errors import SandboxLimitExceeded
from src.sandbox.fs_utils import iter_files

CODE_EXTENSIONS = {".py"}
MAX_SOURCE_READ_BYTES = 1_000_000  # tek dosyadan okunacak üst sınır


def extract_python_symbols(
    root_path: str,
    max_files: int = 5000,
    max_bytes: int = 50 * 1024 * 1024,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """``root_path`` altındaki ``.py`` dosyalarını AST ile OKUR (ASLA
    ÇALIŞTIRMAZ/import etmez) ve döndürür:

      - ``modules``: {modül_adı: göreli_dosya_yolu} (ör. "browser_agent" -> "browser_agent.py")
      - ``classes``: {sınıf_adı: [göreli_dosya_yolu, ...]}

    Symlink/junction'lar takip edilmez (``fs_utils.iter_files``). Sözdizimi
    hatalı, okunamayan veya çok büyük dosyalar sessizce ATLANIR — akışı
    kesmez. Sınır aşılırsa o ana kadar toplanan KISMİ sonuçla devam edilir.

    Bu fonksiyon hem sandbox'lanmış harici bir repoyu, hem de (Sprint 12'de)
    JARVIS'in kendi mimarisini taramak için ORTAK olarak kullanılır.
    """

    modules: dict[str, str] = {}
    classes: dict[str, list[str]] = {}

    try:
        for full_path, _size in iter_files(root_path, max_files=max_files, max_bytes=max_bytes):
            if os.path.splitext(full_path)[1].lower() not in CODE_EXTENSIONS:
                continue

            rel_path = os.path.relpath(full_path, root_path)
            module_name = os.path.splitext(os.path.basename(full_path))[0]
            if module_name != "__init__":
                modules.setdefault(module_name, rel_path)

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as handle:
                    source = handle.read(MAX_SOURCE_READ_BYTES)
                tree = ast.parse(source, filename=full_path)
            except (SyntaxError, ValueError, OSError, RecursionError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    classes.setdefault(node.name, []).append(rel_path)
    except SandboxLimitExceeded:
        pass  # sinir asildi; o ana kadar toplanan kismi sonuc dondurulur
    except OSError:
        pass

    return modules, classes
