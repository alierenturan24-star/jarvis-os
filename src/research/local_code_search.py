from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from src.integration.jarvis_scanner import PROJECT_ROOT, scan_jarvis_architecture

# Sprint 41 (LOCAL CODE INTELLIGENCE): "JARVIS kendi proje kodu/mimarisi
# sorulduğunda internete gitmemeli" -- ZATEN VAR OLAN
# ``scan_jarvis_architecture`` (Sprint 12, IntegrationPlanner'ın kullandığı
# salt-okunur AST tarayıcı) yeniden kullanılır. İkinci bir dosya/repository
# sistemi İCAT EDİLMEZ.
#
# Sinyal, hardcoded bir CÜMLE listesi DEĞİL -- metinde JARVIS'in KENDİ kod
# tabanında GERÇEKTEN var olan bir sınıf/modül adı geçiyor mu, doğrudan
# ``scan_jarvis_architecture()``'ın indeksine bakılarak (dinamik) belirlenir.
MIN_SYMBOL_NAME_LENGTH = 4  # "Task" gibi çok genel/kısa adları gürültü olarak ele

# Sprint 41 canlı testinde yakalandı: "Jarvis" (src/core/jarvis.py'deki
# GERÇEK sınıf) bu projedeki HEMEN HEMEN HER isteğin başında bir HİTAP
# ("Jarvis, ...") olarak geçiyor -- sınıf adıyla bire bir aynı olduğu
# için, hiçbir gerçek yerel-kod niyeti OLMASA BİLE her mesaj yanlışlıkla
# "yerel kod sorgusu" sanılıyordu (ör. "Bitcoin neden düştü" isteği bile
# TEST 2'de gereksiz yere 132 sn'lik bir local-code çağrısı tetikledi).
# Dar, açık bir istisna -- yeni bir sınıflandırma sistemi İCAT ETMEZ.
_EXCLUDED_ADDRESS_SYMBOLS = {"Jarvis"}
MAX_SYMBOLS_PER_QUERY = 3
# Sprint 41 bölüm 5 (CONTEXT CONTROL): "Alakasız dosyaları gönderme" --
# ilk sürüm dosyanın İLK N karakterini (import'lar/lisans başlığı dahil,
# çoğunlukla ALAKASIZ) gönderiyordu; bu hem gereksiz büyük hem de yerel
# modelin (llama3.2) 130 sn'lik bütçede işleyemediği kadar YAVAŞTI (canlı
# ölçüldü). Artık yalnızca İLGİLİ sınıfın/fonksiyonun AST kaynak
# segmenti gönderiliyor -- yoksa (AST çıkaramazsa) dosyanın küçük bir
# bölümüne düşülür.
MAX_FILE_EXCERPT_CHARS = 1200


@dataclass(frozen=True)
class CodeEvidence:
    symbol: str
    file_path: str
    excerpt: str


def detect_referenced_symbols(text: str) -> list[str]:
    """Metinde GERÇEK bir JARVIS sınıf/modül adına referans var mı?

    Yeni bir sınıflandırma İCAT ETMEZ -- yalnızca ZATEN VAR OLAN
    ``scan_jarvis_architecture()`` indeksindeki adları arar. Bu yüzden
    sinyal her zaman GERÇEK koddan gelir, hiçbir zaman "hayali" bir sınıf
    adıyla yanlışlıkla eşleşmez."""

    index = scan_jarvis_architecture()
    candidates = set(index.classes.keys()) | set(index.modules.keys())

    found: list[str] = []
    for name in candidates:
        if len(name) < MIN_SYMBOL_NAME_LENGTH:
            continue
        if name in _EXCLUDED_ADDRESS_SYMBOLS:
            continue
        if re.search(rf"\b{re.escape(name)}\b", text):
            found.append(name)

    return sorted(found)


def _extract_class_source(source: str, class_name: str) -> str | None:
    """``class_name``'in AST kaynak segmentini döndürür (yalnızca o sınıf
    -- dosyanın geri kalanı/import'lar DEĞİL). Ayrıştırılamazsa ``None``."""

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            segment = ast.get_source_segment(source, node)
            return segment
    return None


def gather_code_evidence(symbols: list[str], max_symbols: int = MAX_SYMBOLS_PER_QUERY) -> list[CodeEvidence]:
    """Bulunan sembollerin GERÇEKTEN bulunduğu dosyaları okur -- ama
    dosyanın TAMAMINI DEĞİL: mümkünse yalnızca İLGİLİ sınıfın AST kaynak
    segmentini (import'lar/alakasız kod HARİÇ) gönderir; AST çıkaramazsa
    dosyanın küçük bir bölümüne (``MAX_FILE_EXCERPT_CHARS``) düşer."""

    index = scan_jarvis_architecture()
    evidence: list[CodeEvidence] = []
    seen_paths: set[str] = set()

    for symbol in symbols[:max_symbols]:
        rel_paths = index.classes.get(symbol) or (
            [index.modules[symbol]] if symbol in index.modules else []
        )
        for rel_path in rel_paths[:1]:  # aynı isim birden çok dosyada olabilir -- ilkini al
            if rel_path in seen_paths:
                continue
            full_path = PROJECT_ROOT / rel_path
            if not full_path.exists():
                continue
            try:
                text = full_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            seen_paths.add(rel_path)

            class_source = _extract_class_source(text, symbol)
            excerpt = (class_source or text)[:MAX_FILE_EXCERPT_CHARS]

            evidence.append(CodeEvidence(symbol=symbol, file_path=rel_path, excerpt=excerpt))

    return evidence


def is_local_code_query(text: str) -> bool:
    return bool(detect_referenced_symbols(text))


def format_evidence(evidence: list[CodeEvidence]) -> str:
    if not evidence:
        return "Metinde JARVIS'in kendi kod tabanında bilinen bir sembol/sınıf adı bulunamadı."

    blocks = ["Bulunan kod kanıtları (yalnızca yerel proje dosyaları -- internet KULLANILMADI):"]
    for item in evidence:
        blocks.append(f"\n### {item.symbol} ({item.file_path})\n```python\n{item.excerpt}\n```")
    return "\n".join(blocks)
