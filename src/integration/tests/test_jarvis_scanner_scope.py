from __future__ import annotations

from src.integration.jarvis_scanner import JARVIS_SCAN_FOLDERS, scan_jarvis_architecture


def test_strategy_and_mission_folders_are_now_in_scan_scope():
    # Sprint 41 (LOCAL CODE INTELLIGENCE): AIStrategyEngine (src/strategy)
    # ve Mission/Department orchestration (src/mission) Sprint 34-40'ta
    # oluşturuldu -- önceki tarama kapsamı bunlardan HABERSİZDİ.
    assert "src/strategy" in JARVIS_SCAN_FOLDERS
    assert "src/mission" in JARVIS_SCAN_FOLDERS


def test_scan_still_finds_previously_known_classes():
    # Regresyon: genişletme, ÖNCEDEN bulunabilen sınıfları (ör.
    # GitHubIntelligence, src/github) BOZMAMALI.
    index = scan_jarvis_architecture()
    assert "GitHubIntelligence" in index.classes


def test_scan_now_finds_ai_strategy_engine():
    index = scan_jarvis_architecture()
    assert "AIStrategyEngine" in index.classes
    assert "CostOptimizer" in index.classes
