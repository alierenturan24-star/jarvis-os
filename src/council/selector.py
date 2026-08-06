from __future__ import annotations

from src.council.models import ModelProfile
from src.council.registry import CouncilRegistry


class CouncilSelector:

    def __init__(self) -> None:

        self.registry = CouncilRegistry()

    @staticmethod
    def _detect_skills(message: str) -> set[str]:

        text = message.casefold()
        skills = {"general"}

        if any(
            keyword in text
            for keyword in [
                "kod",
                "python",
                "debug",
                "hata",
                "yazılım",
            ]
        ):
            skills.add("coding")
            skills.add("reasoning")

        if any(
            keyword in text
            for keyword in [
                "araştır",
                "incele",
                "haber",
                "kaynak",
            ]
        ):
            skills.add("research")
            skills.add("analysis")

        if any(
            keyword in text
            for keyword in [
                "bitcoin",
                "coin",
                "borsa",
                "hisse",
                "finans",
                "piyasa",
            ]
        ):
            skills.add("finance")
            skills.add("analysis")

        if any(
            keyword in text
            for keyword in [
                "video",
                "youtube",
                "senaryo",
                "içerik",
                "thumbnail",
            ]
        ):
            skills.add("content")
            skills.add("writing")

        if any(
            keyword in text
            for keyword in [
                "gizli",
                "özel",
                "kişisel",
                "yerel",
            ]
        ):
            skills.add("privacy")
            skills.add("local")

        return skills

    @classmethod
    def _detect_task_type(cls, message: str) -> str:
        """Mesajı CouncilRegistry.TASK_PROVIDER_MAP anahtarlarından birine
        (coding/research/finance) sınıflandırır; eşleşme yoksa "general"."""

        skills = cls._detect_skills(message)

        for task_type in ("coding", "research", "finance"):
            if task_type in skills:
                return task_type

        return "general"

    @staticmethod
    def _score(
        profile: ModelProfile,
        required_skills: set[str],
    ) -> int:

        strength_matches = len(
            required_skills.intersection(
                set(profile.strengths)
            )
        )

        return round(
            strength_matches * 20
            + profile.quality_score * 0.45
            + profile.speed_score * 0.15
            + profile.cost_score * 0.10
            + profile.priority * 0.10
        )

    def choose(
        self,
        message: str,
        max_models: int = 3,
    ) -> tuple[list[ModelProfile], str]:

        task_type = self._detect_task_type(message)

        candidates: list[ModelProfile] = []
        seen: set[str] = set()

        def add(profile: ModelProfile | None) -> None:
            if profile is not None and profile.name not in seen:
                candidates.append(profile)
                seen.add(profile.name)

        # 1) Görev tipine özel öncelik listesi (CouncilRegistry.TASK_PROVIDER_MAP sırası).
        for profile in self.registry.profiles_for_task(task_type):
            add(profile)

        # 2) Fallback: görev tipine özel havuz yetersizse genel havuzdan tamamla.
        if len(candidates) < max_models and task_type != "general":
            for profile in self.registry.profiles_for_task("general"):
                add(profile)

        # 3) Fallback: hâlâ yetersizse, beceri-skoru tabanlı diğer aktif
        #    modellerle (kayıtlı ama task map'te olmayanlar dahil) tamamla.
        if len(candidates) < max_models:
            required_skills = self._detect_skills(message)

            scored = sorted(
                (
                    (self._score(profile, required_skills), profile)
                    for profile in self.registry.enabled_models()
                    if profile.name not in seen
                ),
                key=lambda item: item[0],
                reverse=True,
            )

            for _, profile in scored:
                add(profile)
                if len(candidates) >= max_models:
                    break

        return candidates[:max_models], task_type
