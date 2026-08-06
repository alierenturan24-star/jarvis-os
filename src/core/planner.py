from typing import Any, Dict, List


class Planner:
    """
    Kullanıcının verdiği ana görevi küçük adımlara böler.

    Bu ilk sürüm kural tabanlı çalışır.
    İleride yapay zekâ destekli dinamik planlama eklenecektir.
    """

    def create_plan(self, command: str) -> Dict[str, Any]:
        command = command.strip()

        if not command:
            return {
                "goal": "",
                "status": "failed",
                "message": "Plan oluşturmak için bir komut gerekli.",
                "tasks": [],
            }

        command_lower = command.lower()

        if self._contains_any(
            command_lower,
            ["youtube", "video", "kanal", "içerik üret"],
        ):
            tasks = self._youtube_plan(command)

        elif self._contains_any(
            command_lower,
            ["bitcoin", "coin", "kripto", "borsa", "hisse", "finans"],
        ):
            tasks = self._finance_plan(command)

        elif self._contains_any(
            command_lower,
            ["araştır", "araştırma", "incele", "bilgi bul"],
        ):
            tasks = self._research_plan(command)

        elif self._contains_any(
            command_lower,
            ["kod", "proje", "uygulama", "yazılım", "program"],
        ):
            tasks = self._software_plan(command)

        elif self._contains_any(
            command_lower,
            ["sosyal medya", "instagram", "tiktok", "twitter", "linkedin"],
        ):
            tasks = self._social_media_plan(command)

        else:
            tasks = self._general_plan(command)

        return {
            "goal": command,
            "status": "planned",
            "message": f"{len(tasks)} görevden oluşan bir plan hazırlandı.",
            "tasks": tasks,
        }

    def _youtube_plan(self, command: str) -> List[Dict[str, Any]]:
        return [
            self._task(
                1,
                "İsteği analiz et",
                "Kullanıcının içerik hedefini, konuyu ve hedef kitleyi belirle.",
                "analysis",
            ),
            self._task(
                2,
                "Konu araştırması yap",
                "Konuyla ilgili eğilimleri, rakipleri ve içerik fırsatlarını araştır.",
                "research",
                depends_on=[1],
            ),
            self._task(
                3,
                "İçerik fikri oluştur",
                "Araştırma sonuçlarına göre uygun video fikri ve başlık seçenekleri üret.",
                "content",
                depends_on=[2],
            ),
            self._task(
                4,
                "Senaryo hazırla",
                "Video için giriş, ana bölüm ve kapanıştan oluşan senaryo yaz.",
                "writing",
                depends_on=[3],
            ),
            self._task(
                5,
                "Görsel plan hazırla",
                "Her sahne için gerekli görselleri ve video parçalarını belirle.",
                "media",
                depends_on=[4],
            ),
            self._task(
                6,
                "Video üretim görevini hazırla",
                "Senaryo ve görsel plana göre kullanılacak video üretim aracını belirle.",
                "video",
                depends_on=[4, 5],
                requires_confirmation=True,
            ),
            self._task(
                7,
                "Başlık ve açıklama oluştur",
                "Yayın için başlık, açıklama, etiket ve küçük resim fikri hazırla.",
                "publishing",
                depends_on=[4],
            ),
            self._task(
                8,
                "Kalite kontrolü yap",
                "Senaryoyu, görselleri ve yayın bilgilerini son kez kontrol et.",
                "review",
                depends_on=[6, 7],
            ),
            self._task(
                9,
                "Yayın onayı iste",
                "İçerik yayınlanmadan önce kullanıcıdan açık onay al.",
                "approval",
                depends_on=[8],
                requires_confirmation=True,
            ),
        ]

    def _finance_plan(self, command: str) -> List[Dict[str, Any]]:
        return [
            self._task(
                1,
                "Finansal isteği analiz et",
                "Varlık türünü, zaman aralığını ve kullanıcının istediği analizi belirle.",
                "analysis",
            ),
            self._task(
                2,
                "Piyasa verilerini topla",
                "Güncel fiyat, hacim, volatilite ve ilgili piyasa verilerini getir.",
                "market_data",
                depends_on=[1],
            ),
            self._task(
                3,
                "Teknik analiz yap",
                "Trend, destek, direnç ve temel teknik göstergeleri değerlendir.",
                "technical_analysis",
                depends_on=[2],
            ),
            self._task(
                4,
                "Risk analizi yap",
                "Olası zararları, belirsizlikleri ve risk seviyesini belirle.",
                "risk",
                depends_on=[2, 3],
            ),
            self._task(
                5,
                "Sonuçları karşılaştır",
                "Birden fazla analiz sonucunu Decision Engine ile karşılaştır.",
                "decision",
                depends_on=[3, 4],
            ),
            self._task(
                6,
                "Kullanıcıya rapor sun",
                "Sonucu yatırım tavsiyesi vermeden, riskleri açıkça belirterek sun.",
                "report",
                depends_on=[5],
            ),
            self._task(
                7,
                "İşlem onayı iste",
                "Gerçek para veya hesap üzerinde işlem yapılacaksa açık kullanıcı onayı al.",
                "approval",
                depends_on=[6],
                requires_confirmation=True,
            ),
        ]

    def _research_plan(self, command: str) -> List[Dict[str, Any]]:
        return [
            self._task(
                1,
                "Araştırma sorusunu belirle",
                "Araştırılacak konuyu ve beklenen sonucu netleştir.",
                "analysis",
            ),
            self._task(
                2,
                "Kaynakları tara",
                "Konuyla ilgili güvenilir ve güncel kaynakları bul.",
                "research",
                depends_on=[1],
            ),
            self._task(
                3,
                "Bilgileri karşılaştır",
                "Kaynaklardaki ortak noktaları ve çelişkileri belirle.",
                "verification",
                depends_on=[2],
            ),
            self._task(
                4,
                "Sonuç raporu oluştur",
                "Doğrulanan bilgileri kısa ve anlaşılır bir rapora dönüştür.",
                "report",
                depends_on=[3],
            ),
        ]

    def _software_plan(self, command: str) -> List[Dict[str, Any]]:
        return [
            self._task(
                1,
                "Yazılım isteğini analiz et",
                "İstenen özelliği, girdileri, çıktıları ve teknik sınırları belirle.",
                "analysis",
            ),
            self._task(
                2,
                "Teknik plan oluştur",
                "Dosyaları, sınıfları ve modülleri belirle.",
                "architecture",
                depends_on=[1],
            ),
            self._task(
                3,
                "Kodu üret",
                "Teknik plana uygun kodu hazırla.",
                "coding",
                depends_on=[2],
            ),
            self._task(
                4,
                "Kodu kontrol et",
                "Sözdizimi, import, hata yönetimi ve güvenlik kontrollerini yap.",
                "review",
                depends_on=[3],
            ),
            self._task(
                5,
                "Dosya değişikliği onayı iste",
                "Mevcut dosyalar değiştirilecekse kullanıcıdan onay al.",
                "approval",
                depends_on=[4],
                requires_confirmation=True,
            ),
        ]

    def _social_media_plan(self, command: str) -> List[Dict[str, Any]]:
        return [
            self._task(
                1,
                "Platformu ve hedefi belirle",
                "İçeriğin yayınlanacağı platformu ve beklenen sonucu analiz et.",
                "analysis",
            ),
            self._task(
                2,
                "İçerik araştırması yap",
                "Kaydedilen içerikleri, eğilimleri ve rakip paylaşımları incele.",
                "research",
                depends_on=[1],
            ),
            self._task(
                3,
                "İçerik taslağı oluştur",
                "Platforma uygun metin, görsel veya video fikri hazırla.",
                "content",
                depends_on=[2],
            ),
            self._task(
                4,
                "Kalite ve uygunluk kontrolü yap",
                "İçeriği dil, doğruluk, marka uyumu ve platform kuralları açısından kontrol et.",
                "review",
                depends_on=[3],
            ),
            self._task(
                5,
                "Yayın onayı iste",
                "Paylaşım yayınlanmadan önce kullanıcıdan açık onay al.",
                "approval",
                depends_on=[4],
                requires_confirmation=True,
            ),
        ]

    def _general_plan(self, command: str) -> List[Dict[str, Any]]:
        return [
            self._task(
                1,
                "Görevi analiz et",
                "Kullanıcının isteğini, hedefini ve gerekli çıktıyı belirle.",
                "analysis",
            ),
            self._task(
                2,
                "Gerekli bilgileri topla",
                "Görevi tamamlamak için gerekli bilgi ve kaynakları hazırla.",
                "research",
                depends_on=[1],
            ),
            self._task(
                3,
                "Çözümü üret",
                "Toplanan bilgilere göre görevi yerine getir.",
                "execution",
                depends_on=[2],
            ),
            self._task(
                4,
                "Sonucu kontrol et",
                "Üretilen sonucu doğruluk ve eksiklik açısından incele.",
                "review",
                depends_on=[3],
            ),
            self._task(
                5,
                "Sonucu kullanıcıya sun",
                "Kontrol edilen sonucu açık ve anlaşılır şekilde sun.",
                "response",
                depends_on=[4],
            ),
        ]

    @staticmethod
    def _task(
        task_id: int,
        title: str,
        description: str,
        task_type: str,
        depends_on: List[int] | None = None,
        requires_confirmation: bool = False,
    ) -> Dict[str, Any]:
        return {
            "id": task_id,
            "title": title,
            "description": description,
            "type": task_type,
            "status": "pending",
            "depends_on": depends_on or [],
            "requires_confirmation": requires_confirmation,
            "result": None,
            "error": None,
        }

    @staticmethod
    def _contains_any(text: str, keywords: List[str]) -> bool:
        return any(keyword in text for keyword in keywords)