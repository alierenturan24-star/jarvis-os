from __future__ import annotations


FAILURE_MARKERS = (
    "zaman aşımına uğradı",
    "ollama bulunamadı",
    "ollama hatası",
    "ollama hata verdi",
    "model cevap üretmedi",
    "provider bulunamadı",
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


def source_fallback(topic: str, results: list[dict], limit: int = 5) -> str:
    selected = compact_results(results, limit=limit)
    if not selected:
        return "Kaynaklardan güvenilir bir özet oluşturulamadı."

    lines = [
        "Yerel model zamanında yanıt veremediği için kaynak tabanlı kısa özet gösteriliyor.",
        "",
        f"Konu: {topic}",
        "",
        "Öne çıkan kaynaklar:",
    ]

    for index, item in enumerate(selected, start=1):
        title = item.get("title") or "Başlıksız kaynak"
        snippet = item.get("summary") or "Açıklama bulunamadı."
        lines.append(f"{index}. {title}")
        lines.append(f"   {snippet[:280]}")

    lines.extend([
        "",
        "Not: Ayrıntılı yapay zekâ özeti sonraki çalıştırmada yeniden denenebilir.",
    ])
    return "\n".join(lines)
