import unittest

from src.utils.llm_utils import compact_results, is_llm_failure


class LlmUtilsTests(unittest.TestCase):
    def test_timeout_is_failure(self):
        self.assertTrue(is_llm_failure("Ollama zaman aşımına uğradı."))

    def test_normal_answer_is_not_failure(self):
        self.assertFalse(is_llm_failure("Araştırma başarıyla tamamlandı."))

    def test_compact_results_deduplicates_urls(self):
        results = [
            {"title": "A", "url": "https://a", "summary": "Bir"},
            {"title": "A2", "url": "https://a", "summary": "İki"},
            {"title": "B", "url": "https://b", "summary": "Üç"},
        ]
        compact = compact_results(results, limit=5)
        self.assertEqual(len(compact), 2)
