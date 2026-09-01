from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GoalSpec:
    """One user message, separated into planning roles without creating jobs."""

    goal: str
    constraints: tuple[str, ...] = ()
    output_preferences: tuple[str, ...] = ()
    context: tuple[str, ...] = ()


_CONSTRAINTS = (
    re.compile(r"^(?:kurma|yükleme|yükleme yapma|install etme)\b", re.I),
    re.compile(r"^(?:para|ücret)\s+harcama\b", re.I),
    re.compile(r"^(?:commit|push|commit/push)\s+yapma\b", re.I),
    re.compile(r"^(?:yayınlama|paylaşma|hesap açma)\b", re.I),
    re.compile(r"^.+\b(?:yapma|etme|kullanma|çalıştırma)\b", re.I),
)
_OUTPUT = re.compile(
    r"^(?:kısa|özet|detaylı|madde madde)\b.*(?:sonuç|rapor|cevap|ver)|^(?:son rapor|karar|evaluation)\s*:?$",
    re.I,
)
_LABEL = re.compile(r"^(?:goal|hedef|context|bağlam|constraints?|kısıtlar?|output|çıktı)\s*:\s*", re.I)

# Operational recovery and approval instructions describe how JARVIS must
# behave if the primary goal hits a boundary; they are not additional goals.
# Keep them on ``Mission.constraints`` for audit/safety, while preventing
# their capability/provider/integration vocabulary from entering routing.
_CONDITIONAL_RECOVERY = re.compile(
    r"^(?:gerekli|gereken|eğer|eger|if)\b.*\b"
    r"(?:yeten\w*|capabilit\w*|sağlayıcı\w*|saglayici\w*|provider\w*|recovery|kurtarma)\b",
    re.I,
)
_CONDITIONAL_APPROVAL = re.compile(
    r"\b(?:gerekiyorsa|gerekirse|gerektiğinde|if required)\b.*\b"
    r"(?:onay|approval)\b|\b(?:onay|approval)\b.*\b(?:gerçekleştirme|yapma|etme)\b",
    re.I,
)
_PROHIBITED_EXTERNAL_ACTION = re.compile(
    r"^(?:videoyu\s+)?(?:youtube['’]?a\s+)?(?:yükleme|yükleme\s+yapma|upload(?:ing)?|"
    r"yayınlama|paylaşma)\b|\b(?:yükleme|upload|yayınlama|paylaşma)\b.*\b"
    r"(?:yapma|etme|gerçekleştirme)\b",
    re.I,
)


def _is_constraint_clause(clause: str) -> bool:
    return (
        any(pattern.search(clause) for pattern in _CONSTRAINTS)
        or bool(_CONDITIONAL_RECOVERY.search(clause))
        or bool(_CONDITIONAL_APPROVAL.search(clause))
        or bool(_PROHIBITED_EXTERNAL_ACTION.search(clause))
    )


def parse_goal_spec(message: str) -> GoalSpec:
    """Classify clauses, while preserving the original positive goal text."""

    text = (message or "").strip()
    clauses = [part.strip(" \t-•.") for part in re.split(r"[\r\n]+|(?<=[.!?])\s+", text) if part.strip()]
    goals: list[str] = []
    constraints: list[str] = []
    outputs: list[str] = []
    context: list[str] = []

    for raw in clauses:
        clause = _LABEL.sub("", raw).strip()
        if not clause:
            continue
        if _is_constraint_clause(clause):
            constraints.append(clause)
        elif _OUTPUT.search(clause):
            outputs.append(clause)
        elif not goals:
            goals.append(clause)
        else:
            context.append(clause)

    goal = ". ".join(goals) or text
    return GoalSpec(goal=goal, constraints=tuple(constraints), output_preferences=tuple(outputs), context=tuple(context))
