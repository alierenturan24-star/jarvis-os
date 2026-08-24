from datetime import datetime
from pathlib import Path
import re

# Sprint 39: "automation" departmanının GERÇEK, dar kapsamlı ilk yeteneği --
# bir içerik planının YAYINA/OTOMASYONA hazırlanması için insanın atması
# gereken adımların LİSTESİ. IntegrationPlanner/EvolutionManager ile AYNI
# "yalnızca ÖNER, asla UYGULAMA" ilkesi: hiçbir hesaba giriş yapmaz, hiçbir
# credential OLUŞTURMAZ/İSTEMEZ, hiçbir şey ZAMANLAMAZ/YAYINLAMAZ. Yeni bir
# LLM çağrısı da İCAT ETMEZ -- tamamen deterministik bir şablondur (bir
# "içerik planını yayına hazırlama" adımlar dizisi her zaman AYNIDIR,
# konudan bağımsız gerçek bir yapay zeka değerlendirmesi GEREKTİRMEZ).
_MAX_FILENAME_TOPIC_LENGTH = 80


class AutomationManager:
    def __init__(self) -> None:
        self.folder = Path("workspace") / "automation"
        self.folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_filename(text: str) -> str:
        filename = (text or "").casefold().strip()
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[\s-]+", "_", filename)
        filename = filename[:_MAX_FILENAME_TOPIC_LENGTH].rstrip("_")
        return filename or "otomasyon"

    def plan(self, topic: str) -> str:
        topic = topic.strip()
        if not topic:
            return "Otomasyon planı için konu belirtilmedi."

        checklist = f"""OTOMASYON / YAYIN ÖNCESİ KONTROL LİSTESİ
Konu: {topic}

Bu bir ÖNERİDİR -- JARVIS hiçbirini otomatik OLARAK yapmadı:

1. Media departmanının ürettiği içerik planını (varsa) insan gözden geçirmesiyle onayla.
2. Seslendirme/görsel için seçilecek gerçek aracı (ücretsiz/yerel öncelikli) kur ve test et.
3. Gerçek ses/video dosyasını üret, kaliteyi manuel kontrol et.
4. YouTube hesabına GİRİŞ YAPMADAN önce, hangi hesapla yayınlanacağına insan karar versin.
5. Telif hakkı, kaynak gösterimi ve YouTube topluluk kurallarına uygunluğu kontrol et.
6. Başlık/açıklama/etiketleri son kez gözden geçir.
7. İlk yayında (varsa) zamanlama/otomasyon aracını (ör. YouTube Studio zamanlayıcı) MANUEL olarak kur.
8. Yayından SONRA performansı izle, gerekirse bir sonraki içerik için bulguları JARVIS'e bildir.

Otomatik yapılan: HİÇBİRİ.
Hesap girişi: YAPILMADI.
Credential: OLUŞTURULMADI/İSTENMEDİ.
Yayın: YAPILMADI.
"""

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = self.folder / f"{self._safe_filename(topic)}_{timestamp}.md"
        path.write_text(checklist, encoding="utf-8")

        return f"{checklist}\nRapor kaydedildi:\n{path}"
