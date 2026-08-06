import re


FINANCE_COMMAND_PATTERNS = (
    r"\bfinans analizi yap\b",
    r"\bfinans analizi\b",
    r"\bpiyasa analizi yap\b",
    r"\bpiyasa analizi\b",
    r"\brisk analizi yap\b",
    r"\brisk analizi\b",
    r"\bcoin analiz et\b",
    r"\bhisse analiz et\b",
    r"\banaliz et\b",
)


def clean_finance_asset(message: str) -> str:
    text = message.casefold().strip()

    for pattern in FINANCE_COMMAND_PATTERNS:
        text = re.sub(pattern, " ", text)

    text = re.sub(r"\s+", " ", text)
    return text.strip(" :,-")
