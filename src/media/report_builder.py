from datetime import datetime
from pathlib import Path
import re

# Sprint 39: ``src.finance.report_builder``/``src.research.report_builder``
# ile AYNI, ZATEN VAR OLAN desen -- yalnızca ``workspace/media/`` altına bir
# markdown dosyası YAZAR, ana projeye hiçbir şey KOPYALAMAZ/ENTEGRE ETMEZ.
# Sprint 38 canlı testinde yakalanan Windows MAX_PATH hatası (bkz.
# ``src.research.report_builder``) buraya baştan itibaren UYGULANDI --
# aynı hatayı tekrar YAZMAMAK için dosya adı burada da kesiliyor.
_MAX_FILENAME_TOPIC_LENGTH = 80


class MediaReportBuilder:

    def __init__(self) -> None:
        self.folder = Path("workspace") / "media"
        self.folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_filename(text: str) -> str:
        filename = (text or "").casefold().strip()
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[\s-]+", "_", filename)
        filename = filename[:_MAX_FILENAME_TOPIC_LENGTH].rstrip("_")
        return filename or "medya"

    def save(
        self,
        topic: str,
        duration_seconds: int,
        plan_text: str,
        quality_summary: str,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = self.folder / f"{self._safe_filename(topic)}_{timestamp}.md"

        content = f"""# {topic} -- YouTube İçerik Planı ({duration_seconds} sn)

## Tarih

{datetime.now().strftime("%d.%m.%Y %H:%M")}

## İçerik Planı

{plan_text}

## Kalite Kontrol

{quality_summary}

## Güvenlik Notu

Bu yalnızca bir ÜRETİM PLANIDIR.
Hiçbir video/ses dosyası otomatik oluşturulmadı, hiçbir şey YouTube'a yüklenmedi.
Gerçek üretim ve yayın için kullanıcı onayı ve manuel adımlar gerekir.
"""

        path.write_text(content, encoding="utf-8")
        return path
