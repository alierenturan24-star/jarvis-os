import unittest

from src.utils.text_cleaner import clean_finance_asset


class FinanceTextCleanerTests(unittest.TestCase):
    def test_bitcoin_name_is_not_truncated(self):
        self.assertEqual(clean_finance_asset("Bitcoin analiz et"), "bitcoin")

    def test_generic_finance_phrase_is_removed(self):
        self.assertEqual(
            clean_finance_asset("Ethereum finans analizi yap"),
            "ethereum",
        )


if __name__ == "__main__":
    unittest.main()
