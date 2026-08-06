import re

from src.planner.task import Task


class Planner:
    """Bir kullanıcı mesajından bir veya daha fazla bağımsız görev üretir."""

    FINANCE_KEYWORDS = (
        "finans analizi",
        "piyasa analizi",
        "risk analizi",
        "coin analiz",
        "hisse analiz",
        "btc analiz",
        "bitcoin analiz",
        "ethereum analiz",
        "borsa analiz",
        "analiz et",
    )

    EVOLUTION_KEYWORDS = (
        "kendini geliştir",
        "kendini geliştirmek için araştır",
        "gelişim fırsatlarını tara",
        "jarvis'i geliştirecek",
        "jarvisi geliştirecek",
        "yeni araçları öğren",
        "merak taraması",
        "gelişim taraması",
    )

    OPPORTUNITY_KEYWORDS = (
        "fırsat",
        "gelir fikri",
        "para kazanma fikri",
        "ücretsiz api",
        "yeni ai aracı",
        "affiliate",
        "saas fikri",
    )

    RESEARCH_KEYWORDS = (
        "araştır",
        "incele",
        "web araması",
    )

    CODING_KEYWORDS = (
        "kod yaz",
        "kod düzelt",
        "python",
        "hata düzelt",
        "debug",
    )

    PLANNING_KEYWORDS = (
        "planla",
        "plan oluştur",
        "adımlara ayır",
    )

    @staticmethod
    def _split_message(message: str) -> list[str]:
        parts = re.split(
            r"\s*(?:,|;|\bve\b|\bsonra\b|\bardından\b)\s*",
            message,
            flags=re.IGNORECASE,
        )
        return [part.strip(" .") for part in parts if part.strip(" .")]

    @staticmethod
    def _contains(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _task_for_segment(self, segment: str) -> Task | None:
        text = segment.casefold().strip()

        if not text:
            return None

        if self._contains(text, self.FINANCE_KEYWORDS):
            return Task(
                agent="finance",
                action="analyze_market",
                target=segment,
                priority=7,
            )

        if self._contains(text, self.EVOLUTION_KEYWORDS):
            return Task(
                agent="evolution",
                action="scan_improvements",
                target=segment,
                priority=8,
            )

        if self._contains(text, self.OPPORTUNITY_KEYWORDS):
            return Task(
                agent="opportunity",
                action="scan_opportunities",
                target=segment,
                priority=6,
            )

        if any(site in text for site in ("google", "youtube", "github", "chatgpt")) and "aç" in text:
            return Task(
                agent="browser",
                action="open_site",
                target=segment,
                priority=5,
            )

        if self._contains(text, self.RESEARCH_KEYWORDS):
            return Task(
                agent="research",
                action="research",
                target=segment,
                priority=4,
            )

        if self._contains(text, self.CODING_KEYWORDS):
            return Task(
                agent="coding",
                action="coding",
                target=segment,
                priority=3,
            )

        if self._contains(text, self.PLANNING_KEYWORDS):
            return Task(
                agent="planning",
                action="planning",
                target=segment,
                priority=2,
            )

        return None

    def build(self, message: str) -> list[Task]:
        message = message.strip()

        if not message:
            return []

        tasks: list[Task] = []
        seen: set[tuple[str, str]] = set()

        for segment in self._split_message(message):
            task = self._task_for_segment(segment)

            if task is None:
                continue

            key = (task.agent, task.target.casefold())
            if key in seen:
                continue

            seen.add(key)
            tasks.append(task)

        if tasks:
            return tasks

        return [
            Task(
                agent="chat",
                action="chat",
                target=message,
                priority=1,
            )
        ]
