from __future__ import annotations

import time
from dataclasses import dataclass

from src.providers.aiml_provider import AIMLProvider
from src.providers.anthropic_provider import AnthropicProvider
from src.providers.base_provider import BaseProvider
from src.providers.deepseek_provider import DeepSeekProvider
from src.providers.gemini_provider import GeminiProvider
from src.providers.groq_provider import GroqProvider
from src.providers.ollama_provider import OllamaProvider
from src.providers.openai_provider import OpenAIProvider
from src.providers.openrouter_provider import OpenRouterProvider

# Sprint 25 düzeltmesi: ``src.utils.llm_utils.is_llm_failure`` yalnızca
# Ollama'ya özgü hata metinlerini ("ollama bulunamadı" vb.) tanıyor --
# canlı doğruladım, AIML'in kendi "AIML API hatası: ..." biçimini
# TANIMIYOR, bu da otomatik fallback'in hiç TETİKLENMEMESİNE yol açıyordu.
# Bu paylaşılan yardımcıyı (Research/Finance'ın DA kullandığı) genişletip
# olası yan etki yaratmak yerine, ``ProviderManager``'ın KENDİ ürettiği
# hata biçimlerini (``generate()``/``_generate_for_route()``'un ürettiği
# "<provider> sağlayıcı hatası: ...", "API anahtarı tanımlı değil" vb.)
# tanıyan, bu dosyaya ÖZEL bir kontrol kullanılıyor.
_GENERIC_FAILURE_MARKERS = (
    "sağlayıcı hatası",
    "api anahtarı tanımlı değil",
    "api hatası",
    "desteklenmeyen provider",
    "zaman aşımına uğradı",
    "bulunamadı",
    "hata verdi",
    "cevap üretmedi",
    "boş cevap verdi",
)


def _is_generation_failure(output: str) -> bool:
    text = str(output or "").casefold().strip()
    return not text or any(marker in text for marker in _GENERIC_FAILURE_MARKERS)

# Sprint 25 (Intelligent Provider Router): görev türüne göre HANGİ
# provider'ın önce denenmesi gerektiğine dair sabit tablo. ``CostOptimizer``
# (bkz. src/providers/cost_optimizer.py) da benzer bir amaca hizmet ediyor
# ama felsefesi farklı: "önce yerel, yalnızca yerel/ücretsiz kotalı hiçbir
# seçenek YOKSA ücretliye geç" -- bu, şu an tek gerçek bulut seçeneği olan
# ``aiml``'i (ücretsiz-kotalı sayılmadığı için) hiçbir zaman seçmiyor,
# Ollama her zaman kullanılabilir olduğu sürece hep yerelde kalıyor
# (canlı doğrulandı). Bu yüzden burada AYRI, basit bir görev->provider
# tablosu tanımlandı; bu YENİ bir router mimarisi DEĞİL, mevcut
# ``ProviderManager``'ın (zaten var olan ``generate()``/``get()``/
# ``available_names()`` üzerine) doğrudan bir genişlemesi.
TASK_CODE = "code"
TASK_LONG_RESEARCH = "long_research"
TASK_WEB_RESEARCH = "web_research"
TASK_SHORT_CHAT = "short_chat"
TASK_SIMPLE_QUESTION = "simple_question"

TASK_TYPE_PROVIDERS: dict[str, str] = {
    TASK_CODE: "aiml",
    TASK_LONG_RESEARCH: "aiml",
    TASK_WEB_RESEARCH: "aiml",
    TASK_SHORT_CHAT: "ollama",
    TASK_SIMPLE_QUESTION: "ollama",
}
DEFAULT_TASK_PROVIDER = "ollama"
FALLBACK_PROVIDER = "ollama"


@dataclass
class RouteResult:
    """Bir ``route_and_generate`` çağrısının tam dökümü -- hangi provider
    seçildi, neden, çalışma zamanında fallback'e düşüldü mü, ne kadar
    sürdü, başarılı mı. Raporlama için (bkz. Sprint 25 kabul testi)."""

    output: str
    chosen_provider: str
    provider_used: str
    reason: str
    fallback_used: bool
    duration_seconds: float
    success: bool


class ProviderManager:
    """Tüm LLM sağlayıcı örneklerini tek bir yerde tutar, isme göre bulur
    ve çalıştırır. ``ModelRouter`` bu sınıfın ince bir uyumluluk katmanıdır."""

    ALIASES = {
        "claude": "anthropic",
        "google": "gemini",
        "local": "ollama",
    }

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {
            "ollama": OllamaProvider(),
            "aiml": AIMLProvider(),
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "gemini": GeminiProvider(),
            "deepseek": DeepSeekProvider(),
            "groq": GroqProvider(),
            "openrouter": OpenRouterProvider(),
        }

    @classmethod
    def normalize(cls, name: str) -> str:
        normalized = (name or "").strip().casefold()
        return cls.ALIASES.get(normalized, normalized)

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(self.normalize(name))

    def names(self) -> list[str]:
        return list(self._providers.keys())

    def available_names(self) -> list[str]:
        return [
            key
            for key, provider in self._providers.items()
            if provider.is_available()
        ]

    def generate(
        self,
        prompt: str,
        provider_name: str,
        model_name: str | None = None,
    ) -> str:
        normalized = self.normalize(provider_name)
        provider = self._providers.get(normalized)

        if provider is None:
            return f"Desteklenmeyen provider: {normalized}"

        try:
            return provider.generate(prompt, model=model_name)
        except Exception as error:
            return f"{normalized} sağlayıcı hatası: {error}"

    # --- Sprint 25: Intelligent Provider Router --------------------------------

    def choose_provider_for_task(self, task_type: str) -> tuple[str, str]:
        """Görev türü için (provider_adı, gerekçe) döner.

        Yalnızca GERÇEKTEN kullanılabilir olan (``is_available()``) bir
        provider önerir -- tercih edilen provider kullanılamıyorsa
        (ör. anahtar tanımlı değil) doğrudan sabit ``FALLBACK_PROVIDER``
        önerilir; böylece ``route_and_generate`` çalışma zamanında
        gereksiz bir başarısız deneme yapmaz.
        """

        preferred = TASK_TYPE_PROVIDERS.get(task_type, DEFAULT_TASK_PROVIDER)

        if task_type not in TASK_TYPE_PROVIDERS:
            return DEFAULT_TASK_PROVIDER, (
                f'Bilinmeyen görev türü {task_type!r} -- güvenli varsayılan: "{DEFAULT_TASK_PROVIDER}".'
            )

        provider = self.get(preferred)
        if provider is None or not provider.is_available():
            return FALLBACK_PROVIDER, (
                f'Görev türü {task_type!r} için tercih edilen "{preferred}" kullanılamıyor '
                f'(anahtar/bağlantı yok) -- "{FALLBACK_PROVIDER}" kullanıldı.'
            )

        return preferred, f'Görev türü {task_type!r} -> "{preferred}".'

    def route_and_generate(
        self,
        prompt: str,
        task_type: str,
        *,
        system: str | None = None,
        model_name: str | None = None,
    ) -> RouteResult:
        """Görev türüne göre provider seçer, çalıştırır; seçilen provider
        başarısız olursa (bkz. ``_is_generation_failure``) OTOMATİK olarak
        ``FALLBACK_PROVIDER``'a (Ollama) düşer.

        Yeni bir router mimarisi İCAT ETMEZ -- yalnızca bu sınıfın zaten
        var olan ``generate()``/``get()`` sözleşmesi üzerine ince bir
        karar+çalıştırma katmanıdır.
        """

        chosen, reason = self.choose_provider_for_task(task_type)

        started = time.monotonic()
        output = self._generate_for_route(chosen, prompt, system, model_name)

        fallback_used = False
        provider_used = chosen

        if _is_generation_failure(output) and chosen != FALLBACK_PROVIDER:
            fallback_used = True
            provider_used = FALLBACK_PROVIDER
            reason += f' "{chosen}" başarısız oldu -> otomatik olarak "{FALLBACK_PROVIDER}"a düşüldü.'
            output = self._generate_for_route(FALLBACK_PROVIDER, prompt, system, model_name)

        duration = round(time.monotonic() - started, 2)

        return RouteResult(
            output=output,
            chosen_provider=chosen,
            provider_used=provider_used,
            reason=reason,
            fallback_used=fallback_used,
            duration_seconds=duration,
            success=not _is_generation_failure(output),
        )

    def _generate_for_route(
        self,
        provider_name: str,
        prompt: str,
        system: str | None,
        model_name: str | None,
    ) -> str:
        provider = self._providers.get(provider_name)
        if provider is None:
            return f"Desteklenmeyen provider: {provider_name}"

        try:
            if system and provider_name == "ollama":
                # Yalnızca OllamaProvider ``system`` parametresini yerel
                # olarak destekliyor (bkz. Sprint 19). Diğer sağlayıcılar
                # için mevcut ``generate(prompt, model)`` sözleşmesi
                # DEĞİŞTİRİLMEDİ -- bunun yerine bağlam+mesaj tek bir
                # prompt'ta birleştirilir.
                return provider.generate(prompt, model=model_name, system=system)
            if system:
                return provider.generate(f"{system}\n\n{prompt}", model=model_name)
            return provider.generate(prompt, model=model_name)
        except Exception as error:
            return f"{provider_name} sağlayıcı hatası: {error}"
