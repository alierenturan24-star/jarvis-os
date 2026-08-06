from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Iterator, Optional

from src.sandbox.errors import SandboxLimitExceeded

# Tüm sandbox dizinleri bunun ALTINDA oluşturulur; ``safe_rmtree`` bu
# önek dışındaki HİÇBİR yolu silmeyi reddeder (ana proje klasörüne
# yanlışlıkla dokunmayı imkansız kılan son bir güvenlik katmanı).
SANDBOX_ROOT = Path(tempfile.gettempdir()) / "jarvis_sandbox"

# Güvenlik taraması sırasında içeriği OKUNMAYACAK (ikili/gereksiz büyük)
# uzantılar — performans ve gürültü azaltma amaçlı, güvenlik sınırı
# DEĞİLDİR (dosya sayısı/boyut sınırları ayrı ve zorunludur).
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf",
    ".eot", ".pdf", ".zip", ".tar", ".gz", ".7z", ".exe", ".dll", ".so",
    ".dylib", ".pyc", ".class", ".jar", ".mp3", ".mp4", ".avi", ".mov",
    ".bin", ".dat", ".db", ".sqlite",
}
MAX_FILE_READ_BYTES = 200_000  # her dosyadan güvenlik taraması için okunan üst sınır


def is_link(path: str) -> bool:
    """Sembolik link VEYA Windows junction/reparse point olup olmadığını
    kontrol eder. Junction'lar Windows'ta klasik ``os.path.islink`` ile
    her zaman yakalanmayabilir; bu yüzden ``os.lstat`` reparse bayrağı da
    ayrıca kontrol edilir (bkz. modül seviyesi not)."""

    try:
        if os.path.islink(path):
            return True
        st = os.lstat(path)
        return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) if hasattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT") else False
    except OSError:
        return False


def iter_files(
    root: str,
    max_files: int,
    max_bytes: int,
) -> Iterator[tuple[str, int]]:
    """``root`` altındaki dosyaları, sembolik link/junction'ları TAKİP
    ETMEDEN sıralar. Sınır aşılırsa ``SandboxLimitExceeded`` fırlatır
    (çağıran bunu BLOCKED durumuna çevirir).

    Her öğe ``(tam_yol, boyut_bayt)``'tır.
    """

    count = 0
    total = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Alt dizin bir symlink/junction ise İÇİNE GİRME (sandbox kaçışını
        # önler) — os.walk'un kendi followlinks=False'u ana bariyerdir,
        # bu ek filtre defans-in-depth amaçlıdır.
        dirnames[:] = [d for d in dirnames if not is_link(os.path.join(dirpath, d))]

        for filename in filenames:
            full_path = os.path.join(dirpath, filename)

            if is_link(full_path):
                continue  # symlink dosya: takip edilmez, boyuta katılmaz

            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            count += 1
            total += size

            if count > max_files or total > max_bytes:
                raise SandboxLimitExceeded(
                    f"Sınır aşıldı: {count} dosya / {total / (1024 * 1024):.1f} MB "
                    f"(izin verilen: {max_files} dosya / {max_bytes / (1024 * 1024):.1f} MB)."
                )

            yield full_path, size


def read_text_safe(path: str, max_bytes: int = MAX_FILE_READ_BYTES) -> Optional[str]:
    """Bir dosyanın ilk ``max_bytes``'ını metin olarak okur. İkili
    içerik/okuma hatası varsa ``None`` döner (akışı KESMEZ)."""

    ext = os.path.splitext(path)[1].lower()
    if ext in BINARY_EXTENSIONS:
        return None
    if is_link(path):
        return None

    try:
        with open(path, "rb") as handle:
            raw = handle.read(max_bytes)
    except OSError:
        return None

    if b"\x00" in raw:  # kaba ikili-dosya tespiti
        return None

    return raw.decode("utf-8", errors="ignore")


def _force_writable_and_retry(func, path, exc_info) -> None:
    """``shutil.rmtree`` hata callback'i. Git'in ``.git/objects`` altında
    salt-okunur bıraktığı dosyalar Windows'ta ``ignore_errors=True`` ile
    bile SESSİZCE silinmeden kalabiliyor (gerçek clone testinde bulundu).
    Bu, dosyayı yazılabilir yapıp silme işlemini bir kez daha dener."""

    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def safe_rmtree(path: Optional[str]) -> bool:
    """``path``'i SİLER — ancak yalnızca ``SANDBOX_ROOT`` altındaysa.

    Bu, ``cleanup()``'ın (ya da herhangi bir hata durumunun) ASLA ana
    proje klasörüne veya sandbox dışı herhangi bir yola dokunamamasını
    garanti eden son güvenlik katmanıdır.
    """

    if not path:
        return False

    resolved = Path(path).resolve()
    root_resolved = SANDBOX_ROOT.resolve()

    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise SandboxLimitExceeded(
            f"Güvenlik ihlali engellendi: {resolved} sandbox kökünün "
            f"({root_resolved}) DIŞINDA — silme reddedildi."
        )

    if not resolved.exists():
        return False

    shutil.rmtree(resolved, onerror=_force_writable_and_retry)
    return not resolved.exists()
