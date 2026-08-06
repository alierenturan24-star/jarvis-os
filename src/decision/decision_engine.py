from dataclasses import dataclass
import re


@dataclass
class Decision:
    intent: str = "chat"
    risk: str = "low"
    internet: bool = False
    confirmation: bool = False
    blocked: bool = False
    reason: str = ""
    model: str = "ollama"
    agents: list[str] | None = None

    def __post_init__(self) -> None:
        if self.agents is None:
            self.agents = []


class DecisionEngine:
    """Normal konuşmayı engellemeden tehlikeli komutları ayırır."""

    CRITICAL_PATTERNS = (
        r"\bformat\s+[a-z]:",
        r"\brm\s+-rf\b",
        r"\bdel\s+/[fqs]\b",
        r"\b(sistem|windows|c:|c:\\).{0,25}\b(sil|kaldır|yok et)\b",
        r"\bşifre(yi)?\s+(göster|paylaş|yaz)\b",
        r"\bapi\s*anahtar(ı|ını)?\s+(göster|paylaş|yaz)\b",
        r"\b(para|kripto).{0,20}\b(gönder|çek|transfer)\b",
    )

    CONFIRM_PATTERNS = (
        r"\b(dosya|klasör|proje).{0,25}\b(sil|kaldır)\b",
        r"\b(git push|yayınla|public yayın|canlı işlem|gerçek işlem)\b",
        r"\b(btc|eth|coin|hisse).{0,25}\b(al|sat|işlem aç)\b",
    )

    def analyze(self, message: str) -> Decision:
        text = message.casefold().strip()
        decision = Decision()

        if any(word in text for word in ("araştır", "incele", "karşılaştır", "web araması")):
            decision.intent = "research"
            decision.internet = True
            decision.agents.append("research")
        elif any(site in text for site in ("google", "youtube", "github", "chatgpt")) and "aç" in text:
            decision.intent = "browser"
            decision.agents.append("browser")

        if any(re.search(pattern, text, re.IGNORECASE) for pattern in self.CRITICAL_PATTERNS):
            decision.risk = "critical"
            decision.confirmation = True
            decision.blocked = True
            decision.reason = "Kritik sistem, kimlik bilgisi veya para transferi riski tespit edildi."
            return decision

        if any(re.search(pattern, text, re.IGNORECASE) for pattern in self.CONFIRM_PATTERNS):
            decision.risk = "high"
            decision.confirmation = True
            decision.reason = "Bu işlem geri alınamaz veya finansal sonuç doğurabilir."

        return decision
