from src.planner.task import Task
from src.utils.llm_utils import is_llm_failure


class ResultAggregator:
    TITLES = {
        "finance": "Finans",
        "evolution": "Kontrollü Gelişim",
        "opportunity": "Fırsatlar",
        "research": "Araştırma",
        "browser": "Tarayıcı",
        "coding": "Kodlama",
        "planning": "Planlama",
        "chat": "JARVIS",
    }

    @staticmethod
    def _executive_summary(tasks: list[Task], results: list[object]) -> str:
        completed = 0
        warnings: list[str] = []
        next_steps: list[str] = []

        for index, result in enumerate(results):
            task = tasks[index] if index < len(tasks) else None
            text = str(result)
            title = ResultAggregator.TITLES.get(
                task.agent if task else "task",
                task.agent.title() if task else "Görev",
            )

            if "Görev sırasında hata" in text:
                warnings.append(f"{title} görevi hata verdi.")
            else:
                completed += 1

            if is_llm_failure(text):
                warnings.append(f"{title} bölümünde yerel model zaman aşımı yaşandı.")
            if "daha önce araştırılmış" in text:
                next_steps.append(f"{title}: kayıtlı bilgi kullanıldı; gerekirse 'güncelle' komutuyla yenile.")

        total = max(1, len(results))
        confidence = round((completed / total) * 100)
        warning_text = "\n".join(f"- {item}" for item in warnings) or "- Kritik uyarı yok."
        next_text = "\n".join(f"- {item}" for item in next_steps) or "- Raporlardaki ilk güvenli adımları sırayla değerlendir."

        return (
            "===========================\n"
            "JARVIS YÖNETİCİ ÖZETİ\n"
            "===========================\n\n"
            f"Tamamlanan görev: {completed}/{len(results)}\n"
            f"İş akışı güveni: {confidence}/100\n\n"
            "Uyarılar:\n"
            f"{warning_text}\n\n"
            "Önerilen sonraki adımlar:\n"
            f"{next_text}"
        )

    def aggregate(self, tasks: list[Task], results: list[object]) -> str:
        if not results:
            return "Görev sonucu üretilemedi."
        if len(results) == 1:
            return str(results[0])

        sections: list[str] = []
        for index, result in enumerate(results):
            task = tasks[index] if index < len(tasks) else None
            agent = task.agent if task is not None else "task"
            title = self.TITLES.get(agent, agent.title())
            target = task.target if task is not None else ""
            sections.append(f"## {title}\nGörev: {target}\n\n{str(result)}")

        return (
            self._executive_summary(tasks, results)
            + "\n\n---\n\n"
            + "\n\n---\n\n".join(sections)
        )
