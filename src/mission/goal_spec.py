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
        if any(pattern.search(clause) for pattern in _CONSTRAINTS):
            constraints.append(clause)
        elif _OUTPUT.search(clause):
            outputs.append(clause)
        elif not goals:
            goals.append(clause)
        else:
            context.append(clause)

    goal = ". ".join(goals) or text
    return GoalSpec(goal=goal, constraints=tuple(constraints), output_preferences=tuple(outputs), context=tuple(context))
