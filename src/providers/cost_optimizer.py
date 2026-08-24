from __future__ import annotations

from dataclasses import dataclass
import re

from src.config.settings import Settings
from src.providers.provider_manager import ProviderManager

# Görev sınıfları (Sprint 7 kapsamında istenen 7 sınıf).
TASK_CHAT = "chat"
TASK_CODING = "coding"
TASK_RESEARCH = "research"
TASK_FINANCE = "finance"
TASK_PLANNING = "planning"
TASK_TRANSLATION = "translation"
TASK_VISION = "vision"

TASK_CLASSES = (
    TASK_CHAT,
    TASK_CODING,
    TASK_RESEARCH,
    TASK_FINANCE,
    TASK_PLANNING,
    TASK_TRANSLATION,
    TASK_VISION,
)

# Yerel modelin (Ollama) tek başına yetersiz kalabileceği, bulut
# sağlayıcılarının da değerlendirilmesi gereken "karmaşık" görev sınıfları.
COMPLEX_TASK_CLASSES = {
    TASK_CODING,
    TASK_RESEARCH,
    TASK_FINANCE,
    TASK_PLANNING,
    TASK_VISION,
}

# Ücretsiz KOTALI BULUT sağlayıcılar (yerel Ollama kasıtlı olarak burada
# yer almaz; yerelin kendi akışı ``CostOptimizer.decide`` içinde ayrıca ve
# önce ele alınır, adım 2 yalnızca gerçek bulut alternatiflerini tarar).
# Not: Bu sınıflandırma her sağlayıcının genel/ücretsiz katmanına göre
# yapılan bir yaklaşıklamadır (gerçek zamanlı kota takibi bu sprintin
# kapsamı dışındadır).
FREE_TIER_PROVIDERS = {"gemini", "groq", "openrouter"}

# API billing değildir: kullanıcının önceden giriş yaptığı CLI abonelik
# kaynaklarıdır. Yalnız coding için aday yapılır ve raporda "ücretsiz API"
# diye etiketlenmez.
PLAN_CLI_PROVIDERS = {"codex", "claude_code"}

# Görev tipine göre metin sınıflandırması için anahtar kelimeler.
# Sıra önemlidir: daha spesifik sınıflar önce kontrol edilir.
_TASK_KEYWORDS: dict[str, tuple[str, ...]] = {
    TASK_VISION: (
        "görsel", "resim", "fotoğraf", "image", "picture", "çiz", "görüntü",
    ),
    TASK_TRANSLATION: (
        "çevir", "tercüme", "translate", "ingilizceye", "türkçeye", "çeviri",
    ),
    TASK_FINANCE: (
        "borsa", "kripto", "hisse", "yatırım", "portföy", "piyasa", "finans",
    ),
    TASK_CODING: (
        "kod", "python", "debug", "hata düzelt", "refactor", "fonksiyon",
        "bug", "github",
    ),
    TASK_RESEARCH: (
        "araştır", "incele", "karşılaştır", "kaynak", "analiz et",
    ),
    TASK_PLANNING: (
        "planla", "plan oluştur", "takvim", "yol haritası", "zaman çizelgesi",
        "strateji oluştur",
    ),
}

# Sağlayıcıların varsayılan model adları (mevcut Settings ile uyumlu).
_DEFAULT_MODELS: dict[str, str] = {
    "ollama": Settings.CHAT_MODEL,
    "aiml": Settings.AIML_DEFAULT_MODEL,
    "openai": Settings.OPENAI_MODEL,
    "anthropic": Settings.ANTHROPIC_MODEL,
    "gemini": Settings.GEMINI_MODEL,
    "deepseek": Settings.DEEPSEEK_MODEL,
    "groq": Settings.GROQ_MODEL,
    "openrouter": Settings.OPENROUTER_MODEL,
}

# Ücretli sağlayıcılar için 1K token başına kaba/göreli nominal maliyet
# birimi (0.0 = ücretsiz). Gerçek faturalandırma değildir; sağlayıcılar
# arası göreli maliyet sıralamasını yansıtır.
_PAID_COST_PER_1K: dict[str, float] = {
    "openai": 0.005,
    "anthropic": 0.006,
    "deepseek": 0.002,
    "aiml": 0.003,
}

# Doğrulanabilir ücret sınıfları (raporlama/Control Center için). "free"
# yalnızca gerçek ücretsiz kota/yerel çalışma için kullanılır -- CLI
# abonelik worker'ları (PLAN_CLI_PROVIDERS) kasıtlı olarak "free" DEĞİL,
# ayrı "plan" sınıfındadır (bkz. yukarıdaki not: "ücretsiz API" diye
# etiketlenmez). Tabloda yer almayan bir sağlayıcı için asla uydurulmaz --
# "unknown" döner.
COST_CLASS_FREE = "free"
COST_CLASS_PLAN = "plan"
COST_CLASS_PAID = "paid"
COST_CLASS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class TaskCostProfile:
    """Bir görev sınıfı için sağlayıcı önceliği ve maliyet/kalite/hız profili."""

    task_type: str
    priority_provider: str
    fallback_provider: str
    estimated_cost: float
    quality_score: int
    speed_score: int


# Görev sınıfı -> (öncelikli provider, yedek provider, tahmini maliyet,
# kalite puanı, hız puanı). Maliyet, 1K token başına kaba/göreli bir
# birimdir (0.0 = ücretsiz kota); gerçek faturalandırma değildir.
TASK_COST_PROFILES: dict[str, TaskCostProfile] = {
    TASK_CHAT: TaskCostProfile(
        task_type=TASK_CHAT,
        priority_provider="ollama",
        fallback_provider="groq",
        estimated_cost=0.0,
        quality_score=65,
        speed_score=85,
    ),
    TASK_CODING: TaskCostProfile(
        task_type=TASK_CODING,
        priority_provider="codex",
        fallback_provider="claude_code",
        estimated_cost=0.0,
        quality_score=86,
        speed_score=70,
    ),
    TASK_RESEARCH: TaskCostProfile(
        task_type=TASK_RESEARCH,
        priority_provider="gemini",
        fallback_provider="openrouter",
        estimated_cost=0.0,
        quality_score=88,
        speed_score=80,
    ),
    TASK_FINANCE: TaskCostProfile(
        task_type=TASK_FINANCE,
        priority_provider="deepseek",
        fallback_provider="openai",
        estimated_cost=0.002,
        quality_score=86,
        speed_score=70,
    ),
    TASK_PLANNING: TaskCostProfile(
        task_type=TASK_PLANNING,
        priority_provider="ollama",
        fallback_provider="deepseek",
        estimated_cost=0.0,
        quality_score=65,
        speed_score=65,
    ),
    TASK_TRANSLATION: TaskCostProfile(
        task_type=TASK_TRANSLATION,
        priority_provider="groq",
        fallback_provider="gemini",
        estimated_cost=0.0,
        quality_score=75,
        speed_score=90,
    ),
    TASK_VISION: TaskCostProfile(
        task_type=TASK_VISION,
        priority_provider="gemini",
        fallback_provider="openai",
        estimated_cost=0.004,
        quality_score=88,
        speed_score=75,
    ),
}


@dataclass
class ModelDecision:
    """CostOptimizer'ın bir görev için verdiği model seçim kararı."""

    provider: str
    model: str
    reason: str
    estimated_cost: float
    confidence: int
    fallback: str | None = None


class CostOptimizer:
    """Görev başına en düşük maliyetli ama yeterli modeli seçer.

    Seçim sırası:
      1) Önce yerel model (Ollama) denenir.
      2) Görev karmaşıksa ücretsiz bulut sağlayıcıları da değerlendirilir.
      3) Ücretsiz kotası olan bir sağlayıcı varsa öncelikle o kullanılır.
      4) Hiçbir yerel/ücretsiz seçenek uygun değilse ücretli sağlayıcıya
         geçilir.
      5) Her kararın nedeni ``ModelDecision.reason`` alanında raporlanır.

    ``ProviderManager`` üzerinden çalışır; sağlayıcıların gerçek
    kullanılabilirliği (API anahtarı / yerel erişim) buradan sorgulanır.
    """

    def __init__(self, provider_manager: ProviderManager | None = None) -> None:
        self.provider_manager = provider_manager or ProviderManager()

    @staticmethod
    def is_free(provider_name: str) -> bool:
        return ProviderManager.normalize(provider_name) in FREE_TIER_PROVIDERS

    @staticmethod
    def cost_class(provider_name: str) -> str:
        """Sağlayıcının doğrulanabilir ücret sınıfı. Yalnızca güvenilir
        şekilde bilinen sağlayıcılar için "free"/"plan"/"paid" döner;
        tabloda yer almayan bir sağlayıcı için maliyet UYDURULMAZ --
        "unknown" döner."""

        normalized = ProviderManager.normalize(provider_name)
        if normalized == "ollama" or normalized in FREE_TIER_PROVIDERS:
            return COST_CLASS_FREE
        if normalized in PLAN_CLI_PROVIDERS:
            return COST_CLASS_PLAN
        if normalized in _PAID_COST_PER_1K:
            return COST_CLASS_PAID
        return COST_CLASS_UNKNOWN

    def _is_available(self, provider_name: str) -> bool:
        provider = self.provider_manager.get(provider_name)
        return bool(provider) and provider.is_available()

    @staticmethod
    def _default_model(provider_name: str) -> str:
        normalized = ProviderManager.normalize(provider_name)
        return _DEFAULT_MODELS.get(normalized, normalized)

    def _cost_for(self, provider_name: str, profile: TaskCostProfile) -> float:
        """Seçilen sağlayıcının gerçek ücretsiz/ücretli durumuna göre
        maliyet tahmini döndürür (görev sınıfının statik tablo değerini
        körü körüne kopyalamak yerine)."""

        normalized = ProviderManager.normalize(provider_name)

        if normalized == "ollama" or self.is_free(normalized):
            return 0.0

        if normalized in PLAN_CLI_PROVIDERS:
            return 0.0  # API billing yok; mevcut plan kullanımı ayrı semantiktir.

        return _PAID_COST_PER_1K.get(normalized, profile.estimated_cost or 0.001)

    @staticmethod
    def _other(profile: TaskCostProfile, selected: str) -> str:
        selected = ProviderManager.normalize(selected)
        if selected == ProviderManager.normalize(profile.priority_provider):
            return profile.fallback_provider
        return profile.priority_provider

    def _decision(
        self,
        *,
        provider: str,
        profile: TaskCostProfile,
        reason: str,
        estimated_cost: float,
        confidence: int,
        fallback: str | None,
    ) -> ModelDecision:
        return ModelDecision(
            provider=ProviderManager.normalize(provider),
            model=self._default_model(provider),
            reason=reason,
            estimated_cost=estimated_cost,
            confidence=confidence,
            fallback=ProviderManager.normalize(fallback) if fallback else None,
        )

    @staticmethod
    def classify(message: str) -> str:
        """Serbest metni yedi görev sınıfından birine eşler; eşleşme
        yoksa ``chat`` döner."""

        text = (message or "").casefold()

        for task_type, keywords in _TASK_KEYWORDS.items():
            if any(
                re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text)
                if keyword == "bug" else keyword in text
                for keyword in keywords
            ):
                return task_type

        return TASK_CHAT

    def decide(self, task_type: str) -> ModelDecision:
        """Verilen görev sınıfı için maliyet-optimize model kararı üretir."""

        normalized_task = task_type if task_type in TASK_COST_PROFILES else TASK_CHAT
        profile = TASK_COST_PROFILES[normalized_task]
        is_complex = normalized_task in COMPLEX_TASK_CLASSES

        local_available = self._is_available("ollama")

        # Coding worker'ları yalnız coding görevinde kullanılır. Codex hedefli
        # implementation/debug için, Claude Code ise fallback olarak mimari/
        # geniş inceleme için mevcut profile sırasıyla değerlendirilir.
        if normalized_task == TASK_CODING:
            for candidate in (profile.priority_provider, profile.fallback_provider):
                if self._is_available(candidate):
                    return self._decision(
                        provider=candidate,
                        profile=profile,
                        reason=(
                            f'Coding görevi için mevcut abonelik CLI worker kaynağı '
                            f'({ProviderManager.normalize(candidate)}) seçildi; OpenAI/Anthropic '
                            "API billing kullanılmaz."
                        ),
                        estimated_cost=0.0,
                        confidence=profile.quality_score,
                        fallback=self._other(profile, candidate),
                    )

        # 1) Basit görevlerde yerel model maliyetsiz ve yeterlidir.
        if local_available and not is_complex:
            return self._decision(
                provider="ollama",
                profile=profile,
                reason=(
                    f'Görev sınıfı "{normalized_task}" basit; yerel model '
                    "(Ollama) maliyetsiz ve yeterli kabul edildi."
                ),
                estimated_cost=0.0,
                confidence=profile.quality_score,
                fallback=self._other(profile, "ollama"),
            )

        # 2) Karmaşık görevlerde önce yerel değerlendirilmiş kabul edilir,
        #    ardından ücretsiz kotalı bulut sağlayıcılar değerlendirilir.
        for candidate in (profile.priority_provider, profile.fallback_provider):
            if self.is_free(candidate) and self._is_available(candidate):
                return self._decision(
                    provider=candidate,
                    profile=profile,
                    reason=(
                        f'Görev sınıfı "{normalized_task}" karmaşık; yerel model '
                        "tek başına yetersiz kabul edildi. Ücretsiz kotalı bulut "
                        f"sağlayıcı ({ProviderManager.normalize(candidate)}) yeterli "
                        "kalite sunduğu için seçildi."
                    ),
                    estimated_cost=0.0,
                    confidence=profile.quality_score,
                    fallback=self._other(profile, candidate),
                )

        # 3) Ücretsiz bulut seçeneği yoksa, elde varsa yerel model yine de
        #    denenir (ücretli sağlayıcıya geçmeden önceki son ücretsiz adım).
        if local_available:
            return self._decision(
                provider="ollama",
                profile=profile,
                reason=(
                    f'Görev sınıfı "{normalized_task}" karmaşık ve ücretsiz '
                    "kotalı bulut sağlayıcı kullanılamıyor; ücretli sağlayıcıya "
                    "geçmeden önce yerel model denendi."
                ),
                estimated_cost=0.0,
                confidence=max(profile.quality_score - 15, 0),
                fallback=self._other(profile, "ollama"),
            )

        # 4) Son çare: gerçekten gerektiği için ücretli sağlayıcıya geçilir.
        for candidate in (profile.priority_provider, profile.fallback_provider):
            if self._is_available(candidate):
                return self._decision(
                    provider=candidate,
                    profile=profile,
                    reason=(
                        f'Görev sınıfı "{normalized_task}" için ne yerel model ne '
                        "de ücretsiz kotalı bir bulut sağlayıcı kullanılabilir "
                        f"durumda; bu yüzden ücretli sağlayıcıya "
                        f"({ProviderManager.normalize(candidate)}) geçildi."
                    ),
                    estimated_cost=self._cost_for(candidate, profile),
                    confidence=profile.quality_score,
                    fallback=self._other(profile, candidate),
                )

        # 5) Görev profilindeki iki aday da kullanılamıyorsa (ör. yalnızca
        #    o görev sınıfı için öngörülmemiş bir ücretli sağlayıcının
        #    anahtarı tanımlı), tamamen yanıtsız kalmak yerine kullanılabilir
        #    herhangi bir sağlayıcıya geçilir.
        for name in self.provider_manager.available_names():
            return self._decision(
                provider=name,
                profile=profile,
                reason=(
                    f'Görev sınıfı "{normalized_task}" için öngörülen '
                    "sağlayıcılardan hiçbiri kullanılabilir değil; "
                    f"kullanılabilir herhangi bir sağlayıcıya "
                    f"({ProviderManager.normalize(name)}) geçildi."
                ),
                estimated_cost=self._cost_for(name, profile),
                confidence=max(profile.quality_score - 25, 0),
                fallback=None,
            )

        raise RuntimeError(
            "Kullanılabilir hiçbir yapay zekâ sağlayıcısı bulunamadı."
        )

    def decide_for_message(self, message: str) -> ModelDecision:
        """Mesajı görev sınıfına ayırıp o sınıf için karar üretir."""
        return self.decide(self.classify(message))

    @staticmethod
    def report(decision: ModelDecision) -> str:
        """Bir ``ModelDecision`` kararını okunabilir bir rapora çevirir."""
        return (
            f"Sağlayıcı: {decision.provider}\n"
            f"Model: {decision.model}\n"
            f"Neden: {decision.reason}\n"
            f"Tahmini maliyet: {decision.estimated_cost}\n"
            f"Güven: {decision.confidence}/100\n"
            f"Yedek sağlayıcı: {decision.fallback or '-'}"
        )
