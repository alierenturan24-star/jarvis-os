from __future__ import annotations

import unittest

from src.tools.browser.dom_engine import DomEngine, InvalidDomIndexError


class FakeLocator:
    """Playwright ``Locator``'ın DomEngine'in kullandığı yüzeyini taklit eder."""

    def __init__(self, tag: str, attrs: dict | None = None, text: str = "", visible: bool = True) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.text = text
        self.visible = visible
        self.clicked = False

    def is_visible(self) -> bool:
        return self.visible

    def get_attribute(self, name: str):
        return self.attrs.get(name)

    def inner_text(self) -> str:
        return self.text

    def evaluate(self, expression: str) -> str:
        # DomEngine yalnızca ``el => el.tagName`` biçiminde, salt okunur ve
        # sabit bir ifade gönderir; sahte burada doğrudan etiket adını döner.
        return self.tag.upper()

    def click(self) -> None:
        self.clicked = True


class FakeLocatorGroup:
    def __init__(self, locators: list[FakeLocator]) -> None:
        self._locators = locators

    def all(self) -> list[FakeLocator]:
        return list(self._locators)


class FakePage:
    def __init__(self, locators: list[FakeLocator]) -> None:
        self._locators = locators

    def locator(self, selector: str) -> FakeLocatorGroup:
        return FakeLocatorGroup(self._locators)


class DomEngineSnapshotTests(unittest.TestCase):
    def _mixed_page(self) -> FakePage:
        return FakePage(
            [
                FakeLocator("button", text="Gönder"),
                FakeLocator("a", attrs={"aria-label": "Ana sayfa", "href": "/"}),
                FakeLocator(
                    "input",
                    attrs={"type": "text", "placeholder": "E-posta"},
                ),
                # Görünmez -- listelenmemeli.
                FakeLocator("button", text="Gizli", visible=False),
                # Devre dışı -- listelenmemeli.
                FakeLocator("button", attrs={"disabled": ""}, text="Pasif"),
                # Şifre alanı -- değeri SIZDIRILMAMALI.
                FakeLocator(
                    "input",
                    attrs={"type": "password", "value": "cok-gizli-sifre"},
                ),
            ]
        )

    def test_only_visible_enabled_elements_are_indexed_starting_at_one(self):
        engine = DomEngine()
        snapshot = engine.build_snapshot(self._mixed_page())

        self.assertEqual(len(snapshot), 4)
        rendered = snapshot.render()
        self.assertIn("[1] <button> Gönder", rendered)
        self.assertIn("[2] <link> Ana sayfa", rendered)
        self.assertIn("[3] <textbox> E-posta", rendered)
        self.assertIn("[4] <password> (şifre alanı)", rendered)

        # Görünmez/devre dışı elemanlar hiç görünmemeli.
        self.assertNotIn("Gizli", rendered)
        self.assertNotIn("Pasif", rendered)

        # Şifre değeri metinde hiçbir biçimde yer almamalı.
        self.assertNotIn("cok-gizli-sifre", rendered)

    def test_snapshot_is_deterministic_across_rebuilds(self):
        engine = DomEngine()
        page = self._mixed_page()

        first = engine.build_snapshot(page).render()
        second = engine.build_snapshot(page).render()

        self.assertEqual(first, second)

    def test_resolve_raises_for_invalid_index(self):
        engine = DomEngine()
        snapshot = engine.build_snapshot(self._mixed_page())

        with self.assertRaises(InvalidDomIndexError):
            snapshot.resolve(999)

        with self.assertRaises(InvalidDomIndexError):
            snapshot.resolve(0)

    def test_resolve_returns_the_correct_locator_for_click(self):
        engine = DomEngine()
        page = self._mixed_page()
        snapshot = engine.build_snapshot(page)

        locator = snapshot.resolve(1)
        locator.click()

        self.assertTrue(page._locators[0].clicked)
        # Diğer elemanlar tıklanmamış olmalı.
        self.assertFalse(page._locators[1].clicked)

    def test_empty_page_renders_friendly_message(self):
        engine = DomEngine()
        snapshot = engine.build_snapshot(FakePage([]))

        self.assertEqual(len(snapshot), 0)
        self.assertEqual(snapshot.render(), "Sayfada etkileşimli eleman bulunamadı.")


if __name__ == "__main__":
    unittest.main()
