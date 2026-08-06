from __future__ import annotations

from src.evaluation.criteria import (
    activity_score,
    architecture_score,
    community_score,
    compatibility_score,
    license_score,
    maintenance_score,
    security_score,
)
from src.evaluation.models import RepoEvaluation
from src.evaluation.module_map import target_module_for
from src.evaluation.relevance import RELEVANCE_LOW_THRESHOLD, relevance_score
from src.github.models import RepoData

# Her kriterin genel puana katkı ağırlığı (toplamı 1.0).
#
# Sprint 10.1: ``relevance_score`` en yüksek tek ağırlığı taşır (%25) —
# kaliteli ama sorgu/hedef modülle ALAKASIZ repoların (awesome list,
# roadmap, vb.) yüksek genel puan almasını önlemek bu sprintin amacı.
# Diğer 7 kriter, önceki ağırlıklı oranları korunarak (0.75 ile
# ölçeklenerek) yer açar; aralarındaki göreli sıralama değişmedi.
WEIGHTS = {
    "relevance_score": 0.25,
    "architecture_score": 0.1125,
    "activity_score": 0.1125,
    "community_score": 0.075,
    "license_score": 0.1125,
    "security_score": 0.1125,
    "compatibility_score": 0.1125,
    "maintenance_score": 0.1125,
}

RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"

SUITABLE_MIN_OVERALL = 55.0
SUITABLE_MIN_COMPATIBILITY = 40.0


class EvaluationEngine:
    """``GitHubIntelligence`` tarafından bulunan repoları, olası bir
    entegrasyondan ÖNCE çok kriterli olarak değerlendiren motor.

    Girdisi ``src.github.models.RepoData`` (``GitHubIntelligence.search()``
    / ``recommend()`` çıktısıyla üretilir); bu sınıf ``src.github``
    içindeki hiçbir koda dokunmaz, yalnızca onun ürettiği veriyi TÜKETİR.
    Klonlama/indirme/entegrasyon YAPMAZ — yalnızca değerlendirme üretir.
    """

    def evaluate(self, repo: RepoData) -> RepoEvaluation:
        scores = {
            "relevance_score": relevance_score(repo),
            "architecture_score": architecture_score(repo),
            "activity_score": activity_score(repo),
            "community_score": community_score(repo),
            "license_score": license_score(repo),
            "security_score": security_score(repo),
            "compatibility_score": compatibility_score(repo),
            "maintenance_score": maintenance_score(repo),
        }

        overall = sum(scores[key] * weight for key, weight in WEIGHTS.items())
        overall = round(min(100.0, max(0.0, overall)), 1)

        risk_level = self._risk_level(repo, overall, scores)
        target_module = target_module_for(repo.category)
        integration_difficulty = self._integration_difficulty(scores)

        # Sprint 10.1: relevance_score eşiğin (60) altındaysa, diğer
        # kriterler ne kadar güçlü olursa olsun repo REDDEDİLİR — bu,
        # kaliteli ama alakasız repoların (awesome list, roadmap, vb.)
        # top_candidates()'a sızmasını KÖKTEN engeller (top_candidates
        # zaten suitable_for_jarvis'e göre filtreliyor, ek bir değişiklik
        # gerekmiyor).
        if scores["relevance_score"] < RELEVANCE_LOW_THRESHOLD:
            suitable = False
            recommendation = (
                f"REDDET — sorgu/hedef modülle alakasız "
                f"(relevance {scores['relevance_score']:.0f}/100, eşik {RELEVANCE_LOW_THRESHOLD:.0f})."
            )
        else:
            suitable = self._is_suitable(repo, overall, scores, risk_level)
            recommendation = self._build_recommendation(
                repo, overall, scores, risk_level, suitable, target_module
            )

        return RepoEvaluation(
            name=repo.name,
            url=repo.url,
            overall_score=overall,
            architecture_score=scores["architecture_score"],
            activity_score=scores["activity_score"],
            community_score=scores["community_score"],
            license_score=scores["license_score"],
            security_score=scores["security_score"],
            compatibility_score=scores["compatibility_score"],
            maintenance_score=scores["maintenance_score"],
            relevance_score=scores["relevance_score"],
            recommendation=recommendation,
            suitable_for_jarvis=suitable,
            target_module=target_module,
            integration_difficulty=integration_difficulty,
            risk_level=risk_level,
        )

    def evaluate_many(self, repos: list[RepoData]) -> list[RepoEvaluation]:
        return [self.evaluate(repo) for repo in repos]

    # --- Sorgulama -----------------------------------------------------------

    def summary(self, evaluations: list[RepoEvaluation]) -> dict:
        """Bir değerlendirme kümesinin toplu özetini üretir: ortalama
        puanlar, risk seviyesi dağılımı, uygun/uygun-olmayan sayısı ve
        hedef modüle göre kırılım."""

        if not evaluations:
            return {
                "count": 0,
                "average_overall_score": 0.0,
                "suitable_count": 0,
                "risk_distribution": {RISK_LOW: 0, RISK_MEDIUM: 0, RISK_HIGH: 0},
                "by_target_module": {},
            }

        count = len(evaluations)
        average_overall = round(sum(e.overall_score for e in evaluations) / count, 1)
        suitable_count = sum(1 for e in evaluations if e.suitable_for_jarvis)

        risk_distribution = {RISK_LOW: 0, RISK_MEDIUM: 0, RISK_HIGH: 0}
        for e in evaluations:
            risk_distribution[e.risk_level] = risk_distribution.get(e.risk_level, 0) + 1

        by_target_module: dict[str, int] = {}
        for e in evaluations:
            by_target_module[e.target_module] = by_target_module.get(e.target_module, 0) + 1

        return {
            "count": count,
            "average_overall_score": average_overall,
            "suitable_count": suitable_count,
            "risk_distribution": risk_distribution,
            "by_target_module": by_target_module,
        }

    def top_candidates(
        self,
        evaluations: list[RepoEvaluation],
        limit: int = 5,
        only_suitable: bool = True,
    ) -> list[RepoEvaluation]:
        """En yüksek genel puanlı ilk ``limit`` değerlendirmeyi döndürür.
        ``only_suitable=True`` (varsayılan) iken ``suitable_for_jarvis``
        olmayanlar elenir."""

        pool = [e for e in evaluations if e.suitable_for_jarvis] if only_suitable else list(evaluations)
        pool.sort(key=lambda e: (-e.overall_score, e.risk_level != RISK_LOW))
        return pool[:limit]

    # --- Dahili: soru-cevap mantığı -------------------------------------------

    @staticmethod
    def _risk_level(repo: RepoData, overall: float, scores: dict) -> str:
        if repo.archived or scores["license_score"] <= 20.0 or overall < 40.0:
            return RISK_HIGH
        if overall >= 75.0 and scores["security_score"] >= 60.0 and scores["license_score"] >= 70.0:
            return RISK_LOW
        return RISK_MEDIUM

    @staticmethod
    def _is_suitable(repo: RepoData, overall: float, scores: dict, risk_level: str) -> bool:
        return (
            risk_level != RISK_HIGH
            and overall >= SUITABLE_MIN_OVERALL
            and scores["compatibility_score"] >= SUITABLE_MIN_COMPATIBILITY
        )

    @staticmethod
    def _integration_difficulty(scores: dict) -> str:
        if scores["compatibility_score"] >= 80.0 and scores["architecture_score"] >= 60.0:
            return "Düşük"
        if scores["compatibility_score"] >= 45.0:
            return "Orta"
        return "Yüksek"

    @staticmethod
    def _build_recommendation(
        repo: RepoData,
        overall: float,
        scores: dict,
        risk_level: str,
        suitable: bool,
        target_module: str,
    ) -> str:
        weakest_key = min(scores, key=lambda key: scores[key])
        weakest_label = {
            "relevance_score": "sorgu/hedef modülle alaka sınırda",
            "architecture_score": "mimari/uyum sinyalleri zayıf",
            "activity_score": "uzun süredir güncellenmemiş",
            "community_score": "topluluk küçük",
            "license_score": "lisans belirsiz/kısıtlayıcı",
            "security_score": "güvenlik sinyalleri zayıf",
            "compatibility_score": "JARVIS'in Python yığınıyla düşük uyum",
            "maintenance_score": "bakım/bus-factor riski",
        }[weakest_key]

        if suitable and risk_level == RISK_LOW:
            return (
                f"ÖNERİLİR — {target_module} için güçlü aday "
                f"(genel puan {overall:.0f}/100, risk {risk_level})."
            )
        if suitable and risk_level == RISK_MEDIUM:
            return (
                f"DİKKATLE DEĞERLENDİRİLEBİLİR — {target_module} için uygun, "
                f"ancak {weakest_label} (genel puan {overall:.0f}/100, risk {risk_level})."
            )
        return (
            f"ÖNERİLMEZ — {weakest_label} (genel puan {overall:.0f}/100, "
            f"risk {risk_level})."
        )
