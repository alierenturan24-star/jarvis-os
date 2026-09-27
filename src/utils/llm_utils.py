from __future__ import annotations


FAILURE_MARKERS = (
    "zaman aşımına uğradı",
    "ollama bulunamadı",
    "ollama hatası",
    "ollama hata verdi",
    "model cevap üretmedi",
    "provider bulunamadı",
    # Some hosted chat providers occasionally answer the system's research
    # prompt with their generic welcome message.  That is a transport-level
    # success but a task-level failure and must never be persisted as a
    # completed research report.
    "what would you like me to work on",
    "how can i help you today",
    "how may i assist you",
    "nasıl yardımcı olabilirim",
    "size nasıl yardımcı olabilirim",
)


def is_llm_failure(text: object) -> bool:
    value = str(text or "").casefold().strip()
    return not value or any(marker in value for marker in FAILURE_MARKERS)


def compact_results(results: list[dict], limit: int = 5) -> list[dict]:
    """LLM bağlamını küçültür ve boş/tekrarlı bağlantıları eler."""
    compact: list[dict] = []
    seen_urls: set[str] = set()

    for item in results:
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()

        if not title and not summary:
            continue
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        compact.append({**item, "title": title, "url": url, "summary": summary[:700]})
        if len(compact) >= limit:
            break

    return compact


def source_fallback(
    topic: str, results: list[dict], limit: int = 5,
    exclude_topics: list[str] | None = None,
) -> str:
    """Build a truthful provider-free research handoff from collected rows.

    The fallback intentionally does not invent a synthesis.  It selects the
    first usable, dated factual headline and exposes every source field the
    downstream evidence gate needs (date, language and URL).  This keeps the
    free pipeline moving when a provider times out or returns a greeting,
    while the existing freshness/source-count gates still decide whether
    media production may proceed.
    """
    selected = compact_results(results, limit=limit)
    if not selected:
        return "Kaynaklardan güvenilir bir özet oluşturulamadı."

    factual = [
        item for item in selected
        if item.get("reference_role") != "format_only" and item.get("rejected") is not True
    ]
    dated = [item for item in factual if str(item.get("published_at") or "").strip()]
    excluded = [str(item or "").casefold().strip() for item in (exclude_topics or []) if str(item or "").strip()]

    def not_previously_attempted(item: dict) -> bool:
        title = str(item.get("title") or "").casefold().strip()
        return bool(title) and not any(title in old or old in title for old in excluded)

    candidates = dated or factual or selected
    unseen = [item for item in candidates if not_previously_attempted(item)]
    lead = (unseen or candidates)[0]
    lead_title = str(lead.get("title") or "Güncel kaynak taraması").strip()

    lines = [
        f"SEÇİLEN KONU: {lead_title}",
        "",
        "AI sağlayıcısı uygun araştırma özeti döndürmediği için doğrulanabilir kaynaklardan "
        "sağlayıcısız yedek rapor oluşturuldu.",
        f"Araştırma isteği ve pazarı: {topic}",
        "",
        "Destekleyen kaynaklar:",
    ]

    for index, item in enumerate(selected, start=1):
        title = item.get("title") or "Başlıksız kaynak"
        snippet = item.get("summary") or "Açıklama bulunamadı."
        lines.append(f"{index}. Başlık: {title}")
        lines.append(f"   Yayın tarihi: {item.get('published_at') or 'Belirtilmedi'}")
        lines.append(f"   Kaynak dili: {item.get('source_language') or 'Belirtilmedi'}")
        lines.append(f"   Adres: {item.get('url') or 'Belirtilmedi'}")
        lines.append(f"   Bilgi: {snippet[:280]}")

    lines.extend([
        "",
        "JARVIS Önerisi",
        "Yalnızca yukarıdaki tarihli kaynaklar güncellik kanıtı olarak kullanılsın; "
        "medya üretimi mevcut kaynak ve lisans kapılarından geçmeden başlatılmasın.",
    ])
    return "\n".join(lines)
