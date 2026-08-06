import json
import tempfile
import unittest
from pathlib import Path

from src.context.context_engine import ContextEngine
from src.context.document_loader import DocumentLoader
from src.context.prompt_builder import PromptBuilder


class ContextEngineTests(unittest.TestCase):

    def test_missing_document_returns_empty_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = DocumentLoader(Path(tmp))
            self.assertEqual(loader.read("docs/missing.md"), "")

    def test_context_contains_task_and_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "constitution.md").write_text(
                "Türkçe konuş.", encoding="utf-8"
            )
            (root / "docs" / "mission.md").write_text(
                "Araştır ve doğrula.", encoding="utf-8"
            )
            (root / "docs" / "project_context.md").write_text(
                "Workflow çalışıyor.", encoding="utf-8"
            )

            output = ContextEngine(root).build("Yeni görevi planla")

            self.assertIn("Türkçe konuş.", output)
            self.assertIn("Workflow çalışıyor.", output)
            self.assertIn("Yeni görevi planla", output)

    def test_recent_knowledge_is_summarized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "workspace" / "knowledge"
            path.mkdir(parents=True)
            (path / "knowledge.json").write_text(
                json.dumps(
                    {
                        "research": [
                            {
                                "topic": "NVIDIA",
                                "created_at": "2026-08-03",
                                "source_count": 12,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output = ContextEngine(root).build("NVIDIA'yı değerlendir")
            self.assertIn("NVIDIA", output)
            self.assertIn("kaynak: 12", output)

    def test_prompt_builder_adds_role_and_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = PromptBuilder(Path(tmp)).build(
                task="Bir plan hazırla",
                role="Planlama uzmanı",
                instructions=["Kısa yaz."],
                include_memory=False,
            )
            self.assertIn("Planlama uzmanı", prompt)
            self.assertIn("Kısa yaz.", prompt)
            self.assertIn("Bir plan hazırla", prompt)


if __name__ == "__main__":
    unittest.main()
