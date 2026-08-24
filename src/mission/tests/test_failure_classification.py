from __future__ import annotations

from src.mission.failure_classification import (
    FailureClass,
    classify_failure,
    is_recoverable_via_different_provider,
)


class TestClassifyFailure:
    def test_ollama_timeout_message(self):
        assert classify_failure("Ollama zaman aşımına uğradı.") == FailureClass.TIMEOUT

    def test_missing_api_key_message(self):
        assert classify_failure("API anahtarı tanımlı değil.") == FailureClass.AUTH_REQUIRED

    def test_quota_message(self):
        assert classify_failure("insufficient_quota: you exceeded your current quota") == FailureClass.QUOTA_EXHAUSTED

    def test_rate_limit_message(self):
        assert classify_failure("429 Too Many Requests") == FailureClass.RATE_LIMIT

    def test_no_handler_message(self):
        assert classify_failure("Görev için handler tanımlı değil.") == FailureClass.TOOL_FAILURE

    def test_model_not_responding(self):
        assert classify_failure("Model cevap üretmedi.") == FailureClass.MODEL_UNAVAILABLE

    def test_generic_provider_error_falls_back_to_provider_unavailable(self):
        assert classify_failure("ollama sağlayıcı hatası: boom") == FailureClass.PROVIDER_UNAVAILABLE

    def test_empty_text_is_unknown(self):
        assert classify_failure("") == FailureClass.UNKNOWN
        assert classify_failure(None) == FailureClass.UNKNOWN

    def test_successful_output_is_unknown_not_a_failure_class(self):
        # Bu fonksiyon başarı/başarısızlık AYRIMI yapmaz -- yalnızca
        # verilen bir hata metnini sınıflandırır. Çağıran, önce
        # is_llm_failure ile başarısızlık olup olmadığını kontrol etmeli.
        assert classify_failure("Gerçek bir analiz sonucu burada.") == FailureClass.UNKNOWN


class TestIsRecoverableViaDifferentProvider:
    def test_timeout_is_recoverable(self):
        assert is_recoverable_via_different_provider(FailureClass.TIMEOUT) is True

    def test_tool_failure_is_not_recoverable_via_provider_switch(self):
        assert is_recoverable_via_different_provider(FailureClass.TOOL_FAILURE) is False

    def test_capability_mismatch_is_not_recoverable_via_provider_switch(self):
        assert is_recoverable_via_different_provider(FailureClass.CAPABILITY_MISMATCH) is False
