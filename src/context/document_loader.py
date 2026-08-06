from pathlib import Path


class DocumentLoader:
    """Proje belgelerini güvenli ve sınırlı biçimde yükler."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()

    def read(self, relative_path: str, max_chars: int = 5000) -> str:
        path = self.root / relative_path

        try:
            if not path.is_file():
                return ""

            text = path.read_text(encoding="utf-8").strip()
            return text[:max_chars]
        except (OSError, UnicodeError):
            return ""
