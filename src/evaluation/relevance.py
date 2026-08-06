from __future__ import annotations

import re

from src.github.models import RepoData

# --- "Genel" repo tespiti: awesome list / roadmap / öğrenme kaynağı /
# kürasyonlu liste / boilerplate / config-dotfiles. Bunlar genellikle
# arama sorgusundaki pek çok anahtar kelimeyi İÇERİR (bu yüzden arama
# sonuçlarında üst sıralara çıkarlar) ama JARVIS'e entegre edilebilecek
# GERÇEK bir proje değildirler — bu yüzden relevance_score'ları sabit
# olarak düşük bir tavana ("cap") çekilir. ------------------------------

GENERIC_NAME_SUBSTRINGS = (
    "awesome", "roadmap", "boilerplate", "dotfiles", "cheatsheet",
    "cheat-sheet", "starter-kit", "starter-template", "template", "list-of",
)
GENERIC_EXACT_NAMES = {"config", ".config", "dotfiles"}
GENERIC_DESCRIPTION_PHRASES = (
    # "list of" kasıtlı olarak GENİŞ tutuldu ("a list of X", "list of major
    # Y", "list of free Z" gibi tüm varyasyonları yakalar) — gerçek proje
    # açıklamaları neredeyse hiç bu kalıpla başlamaz; bu, kürasyonlu liste
    # repolarının en güvenilir tek imzasıdır.
    "list of", "collection of resources", "learning resources", "learning path",
    "awesome list", "roadmap to", "roadmaps, guides", "roadmaps and guides",
    "boilerplate for", "starter template", "dotfiles for", "my dotfiles",
    "config files for", "configuration files for",
)

# NOT: bunlar topics listesindeki elemanlarla TAM eşleştirilir (alt dize
# olarak DEĞİL) — ör. "learning" alt dize olarak kontrol edilseydi
# "machine-learning"/"reinforcement-learning" gibi son derece yaygın ve
# MEŞRU AI/trading konu etiketlerini yanlışça "genel liste" işaretlerdi
# (gerçek API verisiyle doğrulama sırasında tam olarak bu hata bulundu).
GENERIC_TOPIC_TERMS = {
    "awesome", "awesome-list", "roadmap", "curated", "curated-list",
    "learning-resources", "learning-path", "dotfiles", "boilerplate",
    "template", "cheatsheet", "cheat-sheet",
}
# Sprint 9'da bulunan, description alanında bir GitHub sayfasının ham
# HTML/metin dökümünü taşıyan bozuk/anormal repolar (redesigned-pancake,
# .config) için imza ifadeler.
ANOMALY_MARKERS = ("skip to content", "pull requests", "sign in to")

RELEVANCE_LOW_THRESHOLD = 60.0
GENERIC_REPO_CAP = 15.0

# repo.category (arama sorgusu / kategori metni) içindeki çok genel,
# konu ayırt ediciliği olmayan kelimeler — relevance terimlerinden
# çıkarılır ki "python"/"framework" gibi kelimeler her repoyla eşleşip
# sinyali sulandırmasın (dil/mimari uyumu zaten compatibility_score'da
# ayrıca ölçülüyor).
QUERY_STOPWORDS = {
    "the", "and", "for", "with", "open", "source", "using", "based",
    "from", "that", "this", "python", "framework",
}

# GitHubIntelligence'ın 10 sabit kategorisi için elle seçilmiş, eş
# anlamlı/ilişkili terimlerden oluşan alan (domain) sözlüğü — "Hedef
# Jarvis modülü"nün konu alanını temsil eder. Serbest metin sorgular
# (ör. "browser agent python") bu anahtarlardan birine bulanık şekilde
# eşleşir (bkz. ``_domain_terms_for_category``); eşleşmezse sorgunun
# kendi kelimelerine geri düşülür.
DOMAIN_KEYWORDS: dict[str, set[str]] = {
    "browser agent": {"browser", "web", "automation", "scrape", "scraping", "playwright", "selenium", "puppeteer", "navigate", "dom"},
    "youtube automation": {"youtube", "video", "upload", "shorts", "automation", "content", "script", "tts"},
    "ai agent": {"agent", "agents", "autonomous", "llm", "orchestration", "framework", "task", "workflow"},
    "finance ai": {"finance", "financial", "trading", "investment", "portfolio", "market", "stock"},
    "trading bot": {"trading", "trade", "bot", "exchange", "crypto", "cryptocurrency", "binance", "backtest", "strategy"},
    "voice ai": {"voice", "speech", "tts", "stt", "audio", "clone", "synthesis", "whisper"},
    "video generation": {"video", "generation", "generate", "render", "animation", "synthesis", "avatar"},
    "image generation": {"image", "generation", "diffusion", "stable", "art", "picture"},
    "llm": {"llm", "language", "model", "inference", "tokenizer", "transformer", "chat", "completion"},
    "mcp server": {"mcp", "server", "protocol", "model", "context", "tool", "client"},
}

FEATURE_VERB_PATTERNS = (
    "supports", "provides", "enables", "allows you to", "lets you",
    "features", "includes", "built with", "powered by", "integrates with",
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _significant_terms(text: str) -> set[str]:
    words = _WORD_RE.findall((text or "").lower())
    return {w for w in words if len(w) >= 2 and w not in QUERY_STOPWORDS}


def _domain_terms_for_category(category: str) -> set[str]:
    key = (category or "").strip().lower()

    if key in DOMAIN_KEYWORDS:
        return DOMAIN_KEYWORDS[key]

    for known_key, terms in DOMAIN_KEYWORDS.items():
        if all(word in key for word in known_key.split()):
            return terms

    return _significant_terms(key)


def _overlap_ratio(terms: set[str], haystack_text: str) -> float:
    """``terms``'ten kaçının ``haystack_text`` içinde (alt dize olarak)
    geçtiğinin oranı. Alt dize eşleşmesi kasıtlı: "server"in "servers"i,
    "client"in "mcp-client"i de yakalamasını sağlar (basit çoğul/ek
    varyasyonları için lemmatizer'a gerek bırakmaz)."""

    if not terms:
        return 0.0
    hits = sum(1 for term in terms if term in haystack_text)
    return hits / len(terms)


def _build_haystack(repo: RepoData) -> str:
    parts = [repo.name or "", repo.description or "", " ".join(repo.topics or [])]
    return " ".join(parts).lower()


def is_anomalous_description(description: str) -> bool:
    """GitHub sayfası dökümü gibi bozuk/otomatik metin taşıyan
    açıklamaları tespit eder (Sprint 9'da bulunan gerçek örnekler)."""

    lowered = (description or "").lower()
    hits = sum(1 for marker in ANOMALY_MARKERS if marker in lowered)
    return hits >= 2


def is_generic_repo(repo: RepoData) -> bool:
    """awesome list / roadmap / öğrenme kaynağı / kürasyonlu liste /
    boilerplate / config-dotfiles / anormal (bozuk) açıklamalı repoları
    tespit eder. Bunlar teknik olarak kaliteli görünse bile JARVIS'e
    entegre edilebilecek somut bir proje DEĞİLDİR."""

    name = (repo.name or "").strip().lower()
    description = (repo.description or "").lower()
    topics_lower = {str(t).strip().lower() for t in (repo.topics or [])}

    if name in GENERIC_EXACT_NAMES:
        return True
    if any(substring in name for substring in GENERIC_NAME_SUBSTRINGS):
        return True
    if any(phrase in description for phrase in GENERIC_DESCRIPTION_PHRASES):
        return True
    if topics_lower & GENERIC_TOPIC_TERMS:
        return True
    if is_anomalous_description(repo.description):
        return True

    return False


def _readme_bonus(readme_excerpt: str | None, domain_terms: set[str]) -> float:
    if not readme_excerpt:
        return 0.0

    text = readme_excerpt.lower()
    domain_hits = sum(1 for term in domain_terms if term in text)
    has_feature_language = any(pattern in text for pattern in FEATURE_VERB_PATTERNS)

    if domain_hits >= 2 and has_feature_language:
        return 10.0
    if domain_hits >= 1:
        return 5.0
    return 0.0


def relevance_score(repo: RepoData) -> float:
    """Reponun, arandığı sorgu/kategoriyle ve hedef JARVIS modülünün
    konu alanıyla GERÇEKTEN ilgili olup olmadığını 0-100 arası puanlar.

    Girdiler: repo adı, açıklama, topics, ana dil, arama sorgusu/kategori
    (``repo.category``), hedef modülün konu alanı (kategoriden türetilen
    ``DOMAIN_KEYWORDS``) ve varsa README özetindeki özellik ifadeleri.
    "Genel" (awesome list/roadmap/vb.) repolar, diğer sinyaller ne kadar
    güçlü olursa olsun ``GENERIC_REPO_CAP`` ile sınırlanır.
    """

    query_terms = _significant_terms(repo.category)
    domain_terms = _domain_terms_for_category(repo.category)
    haystack = _build_haystack(repo)

    query_overlap = _overlap_ratio(query_terms, haystack)
    domain_overlap = _overlap_ratio(domain_terms, haystack)
    language_component = 10.0 if (repo.language or "").strip() else 0.0

    score = 45.0 * query_overlap + 30.0 * domain_overlap + language_component
    score += _readme_bonus(repo.readme_excerpt, domain_terms)

    if is_generic_repo(repo):
        score = min(score, GENERIC_REPO_CAP)

    return round(min(100.0, max(0.0, score)), 1)
