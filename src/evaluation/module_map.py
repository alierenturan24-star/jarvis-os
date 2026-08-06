from __future__ import annotations

# GitHubIntelligence'ın desteklediği 10 arama kategorisini, JARVIS'in
# GERÇEKTE VAR OLAN modüllerine eşler ("Mevcut mimarimizde hangi modülü
# geliştirir?" sorusunun cevabı). Karşılığı henüz olmayan kategoriler
# (ör. video/görsel/ses üretimi) açıkça "yeni modül" olarak işaretlenir —
# var olmayan bir modülü uydurmak yanıltıcı olurdu.
CATEGORY_TARGET_MODULE: dict[str, str] = {
    "browser agent": "src/agents/browser_agent.py",
    "ai agent": "src/agents/agent_manager.py",
    "finance ai": "src/finance/ (manager.py, risk_engine.py)",
    "trading bot": "src/agents/finance_agent.py + src/finance/",
    "llm": "src/providers/ (router.py, provider_manager.py)",
    "mcp server": "src/tools/ (tool_manager.py, plugin_loader.py)",
    "youtube automation": "Yeni modül gerekir (karşılığı yok, ör. src/media/)",
    "voice ai": "Yeni modül gerekir (karşılığı yok, ör. src/voice/)",
    "video generation": "Yeni modül gerekir (karşılığı yok, ör. src/media/)",
    "image generation": "Yeni modül gerekir (karşılığı yok, ör. src/media/)",
}

DEFAULT_TARGET_MODULE = "Bilinmiyor (tanınmayan kategori)"


def target_module_for(category: str) -> str:
    return CATEGORY_TARGET_MODULE.get((category or "").strip().lower(), DEFAULT_TARGET_MODULE)
