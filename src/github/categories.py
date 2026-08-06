from __future__ import annotations

# Sprint 9 kapsamında desteklenen 10 arama kategorisi ve bunlara karşılık
# gelen GitHub repo arama sorguları (GitHub Search API "qualifiers"
# sözdizimi). Yalnızca bu liste desteklenir; kapsam dışı bir kategori
# ``GitHubIntelligenceError`` ile reddedilir.
SUPPORTED_CATEGORIES: dict[str, str] = {
    # Sprint 24 kök sebep analizi: tırnaksız "youtube automation", GitHub
    # arama API'sinde İKİ AYRI terim (youtube VE automation, ayrı ayrı
    # herhangi bir yerde) olarak yorumlanıyor -- bu yüzden yalnızca
    # "automation" kelimesini öne çıkaran alakasız repolar (jenkins,
    # ansible/workshops, winutil) sonuçlara sızıyordu (canlı doğrulandı).
    # Tırnaklı TAM İFADE arama, bu iki kelimenin BİRLİKTE geçmesini
    # zorunlu kılıyor ve sonuçları köklü biçimde düzeltiyor (canlı
    # doğrulandı: 12 sonuçtan 11'i gerçekten YouTube otomasyonuyla ilgili).
    "youtube automation": '"youtube automation" in:name,description,readme',
    "browser agent": "browser agent in:name,description,readme",
    "ai agent": "ai agent in:name,description,readme",
    "finance ai": "finance ai in:name,description,readme",
    "trading bot": "trading bot in:name,description,readme",
    "voice ai": "voice ai in:name,description,readme",
    "video generation": "video generation in:name,description,readme",
    "image generation": "image generation in:name,description,readme",
    "llm": "llm in:name,description,readme",
    "mcp server": "mcp server in:name,description,readme",
}
