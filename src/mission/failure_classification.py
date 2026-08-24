from __future__ import annotations

from enum import Enum

# Sprint 42 (FAILURE CLASSIFICATION): mevcut hata metinlerini (bkz.
# ``src.utils.llm_utils.FAILURE_MARKERS``, ``src.providers.provider_manager.
# _GENERIC_FAILURE_MARKERS``, ``OllamaProvider.ERROR_MESSAGES``) YAPILANDIRILMIŞ
# bir sınıfa eşler. Yeni bir exception/hata sistemi İCAT ETMEZ -- yalnızca
# ZATEN VAR OLAN, gerçek koddan üretilen metinleri OKUR. Marker listeleri bu
# üç yerin BİRLEŞİMİ + birkaç yeni (kota/rate-limit/auth) sinyal -- hiçbiri
# bu üç yerdeki mevcut davranışı DEĞİŞTİRMEZ, yalnızca ONLARI okuyup
# sınıflandırır.


class FailureClass(str, Enum):
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    TOOL_FAILURE = "tool_failure"
    NETWORK_FAILURE = "network_failure"
    AUTH_REQUIRED = "auth_required"
    CAPABILITY_MISMATCH = "capability_mismatch"
    QUALITY_INSUFFICIENT = "quality_insufficient"
    UNKNOWN = "unknown"


# Sıra ÖNEMLİDİR -- daha SPESİFİK sınıflar önce kontrol edilir (ör.
# "model bulunamadı" PROVIDER_UNAVAILABLE'ın genel "bulunamadı" yakalayıcısına
# düşmeden ÖNCE MODEL_UNAVAILABLE olarak eşleşmeli).
_CLASS_MARKERS: dict[FailureClass, tuple[str, ...]] = {
    FailureClass.AUTH_REQUIRED: (
        "api anahtarı tanımlı değil", "unauthorized", "401", "403",
        "invalid api key", "authentication",
    ),
    FailureClass.RATE_LIMIT: ("rate limit", "429", "çok fazla istek", "too many requests"),
    FailureClass.QUOTA_EXHAUSTED: (
        "quota", "kota", "kredi yetersiz", "insufficient_quota", "limit aşıldı",
    ),
    FailureClass.TIMEOUT: ("zaman aşımına uğradı", "timeout"),
    FailureClass.MODEL_UNAVAILABLE: ("model cevap üretmedi", "model not found", "model bulunamadı"),
    FailureClass.NETWORK_FAILURE: ("bağlantı hatası", "connectionerror", "connection error", "network"),
    FailureClass.TOOL_FAILURE: ("handler tanımlı değil", "tool hatası", "araç hatası"),
    FailureClass.CAPABILITY_MISMATCH: (
        "desteklenmeyen provider", "desteklenmeyen işlem", "kapsamı dışında",
    ),
    FailureClass.QUALITY_INSUFFICIENT: ("kalite yetersiz",),
    # Genel yakalayıcı -- yukarıdaki DAHA SPESİFİK sınıflardan hiçbiri
    # eşleşmediyse, ZATEN VAR OLAN genel hata metinleri buraya düşer.
    FailureClass.PROVIDER_UNAVAILABLE: (
        "bulunamadı", "kullanılamıyor", "sağlayıcı hatası", "api hatası", "hata verdi",
    ),
}

# Bu sınıflarda BAŞKA bir provider/model denemek MANTIKLI (bkz. Sprint 42
# RECOVERY LADDER, basamak 2-3) -- ``TOOL_FAILURE``/``CAPABILITY_MISMATCH``
# provider'dan BAĞIMSIZ bir sorundur, provider değiştirmek YARDIMCI OLMAZ.
_RECOVERABLE_VIA_DIFFERENT_PROVIDER = {
    FailureClass.RATE_LIMIT,
    FailureClass.QUOTA_EXHAUSTED,
    FailureClass.TIMEOUT,
    FailureClass.PROVIDER_UNAVAILABLE,
    FailureClass.MODEL_UNAVAILABLE,
    FailureClass.AUTH_REQUIRED,
    FailureClass.NETWORK_FAILURE,
    FailureClass.QUALITY_INSUFFICIENT,
    FailureClass.UNKNOWN,
}


def classify_failure(text: object) -> FailureClass:
    """Bir hata/başarısızlık metnini ``FailureClass``'a eşler. Yeni bir
    ölçüm İCAT ETMEZ -- yalnızca ZATEN VAR OLAN hata metinlerini okur.
    Tanınmayan/boş metin -> ``UNKNOWN`` (uydurma bir sınıf ATANMAZ)."""

    lowered = str(text or "").casefold().strip()
    if not lowered:
        return FailureClass.UNKNOWN

    for failure_class, markers in _CLASS_MARKERS.items():
        if any(marker in lowered for marker in markers):
            return failure_class

    return FailureClass.UNKNOWN


def is_recoverable_via_different_provider(failure_class: FailureClass) -> bool:
    return failure_class in _RECOVERABLE_VIA_DIFFERENT_PROVIDER
