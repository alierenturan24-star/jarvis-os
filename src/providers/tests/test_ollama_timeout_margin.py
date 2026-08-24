from __future__ import annotations

from src.mission.department_orchestrator import DEPARTMENT_TASK_TIMEOUT_SECONDS
from src.providers.ollama_provider import OLLAMA_REQUEST_TIMEOUT_SECONDS


def test_ollama_http_timeout_is_smaller_than_department_task_timeout():
    # Sprint 41 kök neden düzeltmesi: iki timeout AYNI (150/150) olunca
    # JobManager'ın dış timeout'u ile OllamaProvider'ın iç HTTP timeout'u
    # YARIŞIYORDU -- dış timeout önce ateşlenirse arka plan iş parçacığı
    # zorla durdurulamadan çalışmaya devam ediyordu (bkz. job_manager.py).
    # İç timeout'un dıştan KESİNLİKLE küçük olması, Ollama çağrısının HER
    # ZAMAN kendi kontrollü hata mesajıyla önce dönmesini garanti eder.
    assert OLLAMA_REQUEST_TIMEOUT_SECONDS < DEPARTMENT_TASK_TIMEOUT_SECONDS

    margin = DEPARTMENT_TASK_TIMEOUT_SECONDS - OLLAMA_REQUEST_TIMEOUT_SECONDS
    assert margin >= 10  # anlamlı bir güvenlik marjı, göstermelik bir fark değil
