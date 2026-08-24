from __future__ import annotations

import time
from dataclasses import dataclass

from src.providers.aiml_provider import AIMLProvider
from src.providers.anthropic_provider import AnthropicProvider
from src.providers.base_provider import BaseProvider
from src.providers.claude_code_provider import ClaudeCodeProvider
from src.providers.codex_provider import CodexProvider
from src.providers.deepseek_provider import DeepSeekProvider
from src.providers.execution_history import ProviderExecutionHistory
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

# Sprint 42 (PROVIDER TASK LABEL NORMALIZATION): finance/media/local-code
# çağrı yerleri eskiden kendi ad-hoc etiketlerini ("finance_analysis",
# "media_planning", "local_code_analysis") kullanıyordu -- bu da
# ``ProviderExecutionHistory``'e ``CostOptimizer``/``AIStrategyEngine``'in
# ZATEN kullandığı kanonik görev sınıflarından (bkz.
# ``src.providers.cost_optimizer.TASK_FINANCE/TASK_PLANNING/TASK_CODING``)
# FARKLI bir anahtar altında kayıt düşülmesine yol açıyordu (aynı görev
# türü için geçmiş sorgulanamıyordu). Döngüsel import riski yüzünden
# (``cost_optimizer.py`` zaten bu dosyayı import ediyor) sabitler buraya
# TAŞINMADI/import EDİLMEDİ -- yalnızca STRING DEĞERLERİ kasıtlı olarak
# aynı yapıldı. Eski sabitler (``TASK_CODE`` vb.) geriye dönük uyumluluk
# için DEĞİŞTİRİLMEDİ; bunlar EK, ikinci bir kategori sistemi DEĞİLDİR.
TASK_FINANCE = "finance"
TASK_PLANNING = "planning"
TASK_CODING = "coding"

TASK_TYPE_PROVIDERS: dict[str, str] = {
    TASK_CODE: "aiml",
    TASK_LONG_RESEARCH: "aiml",
    TASK_WEB_RESEARCH: "aiml",
    TASK_SHORT_CHAT: "ollama",
    TASK_SIMPLE_QUESTION: "ollama",
    TASK_FINANCE: "aiml",
    TASK_PLANNING: "ollama",
    TASK_CODING: "codex",
}
DEFAULT_TASK_PROVIDER = "ollama"
FALLBACK_PROVIDER = "ollama"

_COST_TASK_ALIASES = {
    TASK_CODE: TASK_CODING,
    TASK_LONG_RESEARCH: "research",
    TASK_WEB_RESEARCH: "research",
    TASK_SHORT_CHAT: "chat",
    TASK_SIMPLE_QUESTION: "chat",
}


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
    attempted_providers: tuple[str, ...] = ()


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
            # Sprint 44 (CLAUDE CODE WORKER BRIDGE): "claude" DEĞİL --
            # ``ALIASES`` zaten "claude"yı "anthropic"e (HTTP API) eşliyor.
            # Bu, yerelde kurulu Claude Code CLI'yi çağıran AYRI/farklı bir
            # worker (bkz. claude_code_provider.py) -- kayıt tek başına onu
            # task-type routing/CostOptimizer/execution history/recovery
            # merdivenine bağlar, ``ceo.py``ye dokunulmadı.
            "claude_code": ClaudeCodeProvider(),
            "codex": CodexProvider(),
        }
        # Sprint 40 (LEARNING FROM EXECUTION): ``route_and_generate``'in
        # ZATEN ürettiği ``RouteResult``'ı (provider/başarı/fallback/süre)
        # kaydeder -- yeni bir veritabanı İCAT ETMEZ (bkz. execution_history.py).
        self.execution_history = ProviderExecutionHistory()

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

        # Doğrudan çağrılarda da AIStrategyEngine'in kullandığı mevcut karar
        # motoruna başvur. Tembel import, cost_optimizer -> manager döngüsünü önler.
        try:
            from src.providers.cost_optimizer import CostOptimizer, TASK_COST_PROFILES

            cost_task = _COST_TASK_ALIASES.get(task_type, task_type)
            if cost_task in TASK_COST_PROFILES:
                decision = CostOptimizer(self).decide(cost_task)
                return decision.provider, decision.reason
        except RuntimeError:
            pass

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
        preferred_provider: str | None = None,
    ) -> RouteResult:
        """Görev türüne göre provider seçer ve çalıştırır. Seçilen provider
        başarısız olursa kullanılabilir profil alternatiflerini birer kez
        değerlendirir; ``FALLBACK_PROVIDER`` (Ollama) son güvenlik ağıdır.

        Yeni bir router mimarisi İCAT ETMEZ -- yalnızca bu sınıfın zaten
        var olan ``generate()``/``get()`` sözleşmesi üzerine ince bir
        karar+çalıştırma katmanıdır.

        Sprint 35: ``preferred_provider`` -- AI Strategy Engine'in
        (``src.strategy``, Sprint 34) ``CostOptimizer`` üzerinden ZATEN
        verdiği kararı buraya taşıyabilmek için eklenen OPSİYONEL bir
        parametre (yeni bir router İCAT EDİLMEDİ, mevcut karar noktası
        genişletildi). Verilmezse (``None``) davranış BİREBİR eskisi
        ``choose_provider_for_task`` üzerinden CostOptimizer'a gider. Verilirse ve GERÇEKTEN
        kullanılabilirse KULLANILIR; kullanılamıyorsa (ör. plan üretildikten
        sonra sağlayıcı devre dışı kaldıysa) sessizce eski görev-türü
        kararına düşülür -- otomatik Ollama güvenlik ağı korunur.
        """

        if preferred_provider:
            normalized_preferred = self.normalize(preferred_provider)
            candidate = self.get(normalized_preferred)
            if candidate is not None and candidate.is_available():
                chosen = normalized_preferred
                reason = f'AI Strategy Engine tarafından seçildi: "{chosen}".'
            else:
                chosen, reason = self.choose_provider_for_task(task_type)
                reason += (
                    f' (AI Strategy "{normalized_preferred}" önerdi ama artık '
                    "kullanılamıyor -- görev türü tablosuna düşüldü.)"
                )
        else:
            chosen, reason = self.choose_provider_for_task(task_type)

        candidates = self._route_candidates(task_type, chosen)
        started = time.monotonic()
        output = "Kullanılabilir yapay zekâ sağlayıcısı bulunamadı."
        provider_used = chosen
        attempted: list[str] = []

        for provider_name in candidates:
            provider_used = provider_name
            attempted.append(provider_name)
            is_fallback = len(attempted) > 1
            print(
                f"[AŞAMA: PROVIDER] {provider_name.upper()}"
                + (" (fallback)" if is_fallback else ""), flush=True,
            )
            attempt_started = time.monotonic()
            output = self._generate_for_route(
                provider_name, prompt, system, model_name if not is_fallback else None,
            )
            attempt_success = not _is_generation_failure(output)
            self._record_attempt(
                task_type, provider_name, attempt_success, is_fallback,
                round(time.monotonic() - attempt_started, 2),
            )
            if attempt_success:
                break

        fallback_used = len(attempted) > 1
        if fallback_used:
            reason += " Fallback zinciri: " + " -> ".join(attempted) + "."
        duration = round(time.monotonic() - started, 2)
        success = not _is_generation_failure(output)

        return RouteResult(
            output=output,
            chosen_provider=chosen,
            provider_used=provider_used,
            reason=reason,
            fallback_used=fallback_used,
            duration_seconds=duration,
            success=success,
            attempted_providers=tuple(attempted),
        )

    def _route_candidates(self, task_type: str, chosen: str) -> list[str]:
        """Kullanılabilir, benzersiz ve sonlu deneme sırası üretir."""
        ordered: list[str | None] = [chosen]
        try:
            from src.providers.cost_optimizer import (
                CostOptimizer,
                PLAN_CLI_PROVIDERS,
                TASK_CODING,
                TASK_COST_PROFILES,
            )

            cost_task = _COST_TASK_ALIASES.get(task_type, task_type)
            profile = TASK_COST_PROFILES.get(cost_task)
            if profile:
                decision = CostOptimizer(self).decide(cost_task)
                ordered.extend((decision.fallback, profile.priority_provider, profile.fallback_provider))
                if cost_task == "research":
                    ordered.append("aiml")
        except RuntimeError:
            pass
        ordered.append(FALLBACK_PROVIDER)

        profile_candidates: list[str] = []
        for name in ordered:
            normalized = self.normalize(name or "")
            provider = self.get(normalized)
            if (
                normalized
                and normalized not in profile_candidates
                and provider
                and provider.is_available()
            ):
                profile_candidates.append(normalized)

        # Profildeki dar fallback'ler tükendiğinde registry'deki genel LLM
        # sağlayıcılarını da değerlendir. Plan/CLI worker'ları normal chat ve
        # research çağrılarına sızmaz; coding profilindeki Codex -> Claude Code
        # sırası ise yukarıdaki profil katmanında aynen korunur.
        registry_candidates: list[str] = []
        for name, provider in self._providers.items():
            normalized = self.normalize(name)
            if normalized in profile_candidates:
                continue
            if cost_task != TASK_CODING and normalized in PLAN_CLI_PROVIDERS:
                continue
            if provider.is_available():
                registry_candidates.append(normalized)

        def history_score(name: str) -> float:
            score = self.execution_history.success_rate(name, task_type)
            return score if score is not None else 50.0

        # Python'ın kararlı sıralaması eşit/verisiz sağlayıcılarda registry
        # ekleme sırasını korur; böylece zincir deterministic ve sonludur.
        registry_candidates.sort(key=history_score, reverse=True)
        return [*profile_candidates, *registry_candidates]

    def _record_attempt(
        self, task_type: str, provider_name: str, success: bool,
        fallback_used: bool, duration: float,
    ) -> None:
        provider = self._providers.get(provider_name)
        timing = getattr(provider, "last_call_timing", None) or {}
        try:
            # Tembel import: cost_optimizer.py zaten bu modülü import ediyor
            # (döngüsel import önlemi, dosyanın geri kalanındaki desenle aynı).
            from src.providers.cost_optimizer import CostOptimizer
            cost_class = CostOptimizer.cost_class(provider_name)
        except Exception:
            cost_class = None
        try:
            self.execution_history.record(
                task_type=task_type, provider=provider_name, success=success,
                fallback_used=fallback_used, duration_seconds=duration,
                queue_wait_seconds=timing.get("queue_wait_seconds"),
                inference_seconds=timing.get("inference_seconds"),
                resource_type=getattr(provider, "resource_type", None),
                cost_class=cost_class,
            )
        except Exception:
            pass

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
