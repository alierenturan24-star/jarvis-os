from datetime import datetime


class CEOEngine:

    def __init__(self):
        self.daily_plan = []

    def create_daily_plan(self):

        if self.daily_plan:
            return self.daily_plan

        hour = datetime.now().hour

        self.daily_plan = []

        # Sabah araştırma
        if 6 <= hour < 12:
            self.daily_plan.extend([
                "AI haberlerini kontrol et",
                "GitHub trendlerini kontrol et",
                "Yeni AI modellerini kontrol et",
            ])

        # Öğlen geliştirme
        elif 12 <= hour < 18:
            self.daily_plan.extend([
                "Kod görevlerini planla",
                "Eksik modülleri analiz et",
                "Yeni görev oluştur",
            ])

        # Akşam rapor
        else:
            self.daily_plan.extend([
                "Günlük rapor oluştur",
                "Yapılan işleri değerlendir",
                "Yarının planını hazırla",
            ])

        return self.daily_plan

    def get_plan(self):
        return self.daily_plan