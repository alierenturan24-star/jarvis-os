from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Tek bir CSS seçicide birleştirilmiş etkileşimli eleman kümesi. Playwright
# ``Locator`` bunu tek bir ``page.locator(...).all()`` çağrısıyla, belge
# sırasına göre ve YİNELENMESİZ (CSS "veya" birleşimi doğası gereği) çözer.
# Yalnızca Playwright'ın standart, desteklenen API'si kullanılır; sayfa
# içinde herhangi bir JS ifadesi ÇALIŞTIRILMAZ.
INTERACTIVE_SELECTOR = (
    "a[href], button, input:not([type=hidden]), select, textarea, "
    '[role="button"], [role="link"], [role="checkbox"], [role="radio"], '
    '[role="combobox"], [role="menuitem"], [role="tab"], [role="switch"], '
    '[role="textbox"]'
)

# ``role`` özniteliği yoksa, etiket adından çıkarılacak varsayılan rol.
TAG_ROLE_FALLBACK = {
    "a": "link",
    "button": "button",
    "select": "combobox",
    "textarea": "textbox",
}

# <input type=...> için rol eşlemesi (öznitelik tabanlı, JS gerektirmez).
INPUT_TYPE_ROLE = {
    "checkbox": "checkbox",
    "radio": "radio",
    "submit": "button",
    "button": "button",
    "reset": "button",
    "password": "password",
    "search": "textbox",
    "email": "textbox",
    "tel": "textbox",
    "url": "textbox",
    "number": "textbox",
}

MAX_DESCRIPTION_LENGTH = 80


class InvalidDomIndexError(ValueError):
    """Geçersiz, süresi dolmuş veya hiç üretilmemiş bir DOM index'i istendi."""


@dataclass(frozen=True)
class DomElement:
    """Tek bir etkileşimli elemanın, görev-anlık bellekte tutulan kaydı."""

    index: int
    role: str
    description: str
    locator: Any  # playwright.sync_api.Locator (test edilebilirlik için gevşek tip)

    def render(self) -> str:
        return f"[{self.index}] <{self.role}> {self.description}"


class DomSnapshot:
    """Tek bir ``list_elements`` çağrısına ait, sabit index -> eleman eşlemesi.

    Bilerek ÖNBELLEKSİZ tasarlanmıştır: her yeni ``DomEngine.build_snapshot``
    çağrısı sıfırdan bir ``DomSnapshot`` üretir, bir önceki tamamen atılır.
    """

    def __init__(self, elements: list[DomElement]) -> None:
        self._elements = elements
        self._by_index = {element.index: element for element in elements}

    def render(self) -> str:
        if not self._elements:
            return "Sayfada etkileşimli eleman bulunamadı."
        return "\n".join(element.render() for element in self._elements)

    def resolve(self, index: int) -> Any:
        element = self._by_index.get(index)
        if element is None:
            raise InvalidDomIndexError(
                f"Geçersiz index: {index}. Bu index mevcut listede yok "
                "(sayfa değişmiş olabilir; önce 'list_elements' çalıştırın)."
            )
        return element.locator

    def describe(self, index: int) -> str:
        element = self._by_index.get(index)
        if element is None:
            raise InvalidDomIndexError(f"Geçersiz index: {index}.")
        return element.render()

    def __len__(self) -> int:
        return len(self._elements)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def _truncate(value: str) -> str:
    if len(value) <= MAX_DESCRIPTION_LENGTH:
        return value
    return value[: MAX_DESCRIPTION_LENGTH - 1].rstrip() + "…"


def _safe_attr(locator: Any, name: str) -> str | None:
    try:
        return locator.get_attribute(name)
    except Exception:
        return None


def _safe_is_visible(locator: Any) -> bool:
    try:
        return bool(locator.is_visible())
    except Exception:
        return False


def _safe_inner_text(locator: Any) -> str:
    try:
        return locator.inner_text() or ""
    except Exception:
        return ""


def _is_disabled(locator: Any) -> bool:
    if _safe_attr(locator, "disabled") is not None:
        return True
    if (_safe_attr(locator, "aria-disabled") or "").strip().lower() == "true":
        return True
    return False


def _resolve_tag_name(locator: Any) -> str:
    """Etiket adını okur. Playwright'ta bunun tek desteklenen yolu, salt
    okunur ve sabit (kullanıcı girdisi İÇERMEYEN) bir DOM özelliği okuyan
    ``Locator.evaluate`` çağrısıdır -- sayfada script ÇALIŞTIRMAZ, yalnızca
    zaten var olan bir elemanın ``tagName`` özelliğini okur."""
    try:
        tag = locator.evaluate("el => el.tagName")
        return (tag or "").strip().lower()
    except Exception:
        return ""


def _resolve_role(locator: Any) -> tuple[str, str]:
    """(rol, etiket_adı) döndürür."""

    explicit_role = _safe_attr(locator, "role")
    if explicit_role:
        return explicit_role.strip().lower(), _resolve_tag_name(locator)

    tag = _resolve_tag_name(locator)

    if tag == "input":
        input_type = (_safe_attr(locator, "type") or "text").strip().lower()
        return INPUT_TYPE_ROLE.get(input_type, "textbox"), tag

    return TAG_ROLE_FALLBACK.get(tag, tag or "element"), tag


def _resolve_description(locator: Any, role: str) -> str:
    if role == "password":
        return "(şifre alanı)"

    aria_label = _clean_text(_safe_attr(locator, "aria-label"))
    if aria_label:
        return _truncate(aria_label)

    text = _clean_text(_safe_inner_text(locator))
    if text:
        return _truncate(text)

    placeholder = _clean_text(_safe_attr(locator, "placeholder"))
    if placeholder:
        return _truncate(placeholder)

    value = _clean_text(_safe_attr(locator, "value"))
    if value:
        return _truncate(value)

    title = _clean_text(_safe_attr(locator, "title"))
    if title:
        return _truncate(title)

    return "(etiketsiz)"


class DomEngine:
    """Bir Playwright ``Page``'den, görev-anlık bir ``DomSnapshot`` üretir.

    Hiçbir durum tutmaz (stateless); tüm sonuç her çağrıda sıfırdan üretilir.
    Hiçbir LLM çağrısı, kalıcı depolama veya sayfa-içi script çalıştırma
    içermez -- yalnızca Playwright'ın desteklenen ``Locator`` API'sini
    (``.all()``, ``.is_visible()``, ``.get_attribute()``, ``.inner_text()``,
    ``.evaluate()`` [salt tagName okuma]) kullanır.
    """

    def build_snapshot(self, page: Any) -> DomSnapshot:
        elements: list[DomElement] = []
        index = 1

        try:
            candidates = page.locator(INTERACTIVE_SELECTOR).all()
        except Exception:
            candidates = []

        for locator in candidates:
            if not _safe_is_visible(locator):
                continue
            if _is_disabled(locator):
                continue

            role, _tag = _resolve_role(locator)
            description = _resolve_description(locator, role)

            elements.append(DomElement(index=index, role=role, description=description, locator=locator))
            index += 1

        return DomSnapshot(elements)
