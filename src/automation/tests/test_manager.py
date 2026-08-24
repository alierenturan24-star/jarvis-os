from __future__ import annotations

from src.automation.manager import AutomationManager


class TestAutomationManagerPlan:
    def test_empty_topic_returns_early(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = AutomationManager()
        assert "konu belirtilmedi" in manager.plan("   ")

    def test_plan_is_a_checklist_never_an_executed_action(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = AutomationManager()
        result = manager.plan("Bitcoin neden düştü")

        assert "Otomatik yapılan: HİÇBİRİ." in result
        assert "Hesap girişi: YAPILMADI." in result
        assert "Credential: OLUŞTURULMADI" in result
        assert "Yayın: YAPILMADI." in result
        assert "Rapor kaydedildi" in result

    def test_plan_is_saved_to_workspace_automation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        manager = AutomationManager()
        manager.plan("Bitcoin neden düştü")

        saved = list((tmp_path / "workspace" / "automation").glob("*.md"))
        assert len(saved) == 1

    def test_no_network_or_llm_calls_needed(self, tmp_path, monkeypatch):
        # Deterministik olduğunu -- hiçbir provider/network çağrısı
        # OLMADIĞINI -- dolaylı olarak doğrular: hiçbir provider/requests
        # mock'lanmadan test hızlı ve başarılı çalışır.
        monkeypatch.chdir(tmp_path)
        manager = AutomationManager()
        result = manager.plan("herhangi bir konu")
        assert isinstance(result, str)
        assert len(result) > 0
