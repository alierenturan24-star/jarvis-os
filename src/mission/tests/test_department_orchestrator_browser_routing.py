from __future__ import annotations

from src.github.models import RepoData
from src.mission.department_orchestrator import DepartmentOrchestrator
from src.mission.models import Mission


class _FakeGitHubIntelligence:
    """Sprint 32 testleri için: gerçek ağ çağrısı yapmadan, deterministik
    bir "en iyi aday" döndüren sahte ``GitHubIntelligence``."""

    def __init__(self, repos: list[RepoData] | None = None) -> None:
        self.repos = repos if repos is not None else [
            RepoData(
                name="ai", full_name="vercel/ai", url="https://github.com/vercel/ai",
                description="Autonomous LLM agent orchestration workflow", stars=1000, forks=10, license="MIT",
                topics=["ai-agent", "llm", "orchestration", "workflow"],
                last_update="2026-01-01T00:00:00Z", language="TypeScript", category="ai agent",
            )
        ]
        self.search_calls: list[str] = []

    def search(self, category: str, max_results: int = 10, **kwargs):
        self.search_calls.append(category)
        return self.repos


def _browser_tasks_for(text: str, github_intelligence=None) -> list:
    mission = Mission(title=text, description=text, departments=["browser"])
    orchestrator = DepartmentOrchestrator(
        github_intelligence=github_intelligence or _FakeGitHubIntelligence()
    )
    return orchestrator.create_tasks(mission)


# --- 1) Gerçek arama isteği -> search (eski davranış korunmalı) -----------------


class TestBrowserSearchRouting:
    def test_explicit_search_request_routes_to_search(self):
        tasks = _browser_tasks_for("Google'da browser-use ara")

        assert len(tasks) == 1
        assert tasks[0].action == "search"
        # Named target için bütün kullanıcı cümlesi browser query yapılmaz.
        assert tasks[0].target == "browser-use GitHub"

    def test_category_target_with_no_other_signal_opens_real_candidate_not_google(self):
        # Sprint 32: CATEGORY hedefinde, hiçbir açık sinyal (aç/listele/
        # tıkla/ara) yoksa artık ham metin Google'da ARANMIYOR -- gerçek
        # bir GitHub adayı bulunup açılıyor + DOM Engine ile listeleniyor.
        fake = _FakeGitHubIntelligence()
        tasks = _browser_tasks_for("Yeni coin araştır.", github_intelligence=fake)

        assert [t.action for t in tasks] == ["open", "list_elements"]
        assert tasks[0].metadata["url"] == "https://github.com/vercel/ai"
        assert fake.search_calls == ["ai agent"]

    def test_explicit_search_intent_still_wins_over_category_auto_open(self):
        # "ara" fiili AÇIKÇA belirtilmişse (kategoriye rağmen), otomatik
        # repo açma DEVREYE GİRMEMELİ -- kullanıcı gerçekten arama istiyor.
        fake = _FakeGitHubIntelligence()
        tasks = _browser_tasks_for("mcp server ara", github_intelligence=fake)

        assert len(tasks) == 1
        assert tasks[0].action == "search"
        assert fake.search_calls == []

    def test_category_resolution_fails_gracefully_falls_back_to_search(self):
        # GitHub araması başarısız/boş dönerse (ör. ağ hatası, sonuç yok)
        # -- eski davranışa (search, ham metinle) GÜVENLİ şekilde düşülür,
        # sessizce çökmez veya boş bir "open" üretmez.
        fake = _FakeGitHubIntelligence(repos=[])
        tasks = _browser_tasks_for("Yeni coin araştır.", github_intelligence=fake)

        assert len(tasks) == 1
        assert tasks[0].action == "search"
        assert tasks[0].target == "Yeni coin araştır."


# --- 2) Açık URL/repo -> open ----------------------------------------------------


class TestBrowserOpenRouting:
    def test_explicit_url_routes_to_open(self):
        tasks = _browser_tasks_for(
            "https://github.com/browser-use/browser-use adresini aç"
        )

        assert len(tasks) == 1
        assert tasks[0].action == "open"
        assert tasks[0].metadata["url"] == "https://github.com/browser-use/browser-use"


# --- 3) Listeleme isteği -> list_elements ----------------------------------------


class TestBrowserListElementsRouting:
    def test_list_elements_request_alone(self):
        tasks = _browser_tasks_for("Sayfadaki etkileşimli elementleri listele")

        assert len(tasks) == 1
        assert tasks[0].action == "list_elements"


# --- 4) Açık index -> click_index -------------------------------------------------


class TestBrowserClickIndexRouting:
    def test_explicit_index_numaral_form_routes_to_click_index(self):
        tasks = _browser_tasks_for("3 numaralı elemente tıkla")

        assert len(tasks) == 1
        assert tasks[0].action == "click_index"
        assert tasks[0].metadata["index"] == 3

    def test_explicit_index_word_form_routes_to_click_index(self):
        tasks = _browser_tasks_for("index 3'e tıkla")

        assert len(tasks) == 1
        assert tasks[0].action == "click_index"
        assert tasks[0].metadata["index"] == 3


# --- 5) Birleşik görev -> sıralı open -> list_elements (-> click_index) ----------


class TestBrowserCombinedSequentialRouting:
    COMBINED_TEXT = (
        "GitHub üzerinde browser-use/browser-use reposunu tarayıcıyla aç. "
        "DOM Engine kullanarak sayfadaki etkileşimli elemanları listele."
    )

    def test_open_then_list_elements_are_sequential_with_dependency(self):
        tasks = _browser_tasks_for(self.COMBINED_TEXT)

        assert [t.action for t in tasks] == ["open", "list_elements"]
        assert tasks[0].metadata["url"] == "https://github.com/browser-use/browser-use"
        assert tasks[0].depends_on == []
        assert tasks[1].depends_on == [tasks[0].id]

    def test_no_click_index_task_when_index_not_given(self):
        tasks = _browser_tasks_for(self.COMBINED_TEXT)

        assert "click_index" not in [t.action for t in tasks]
        # Kullanıcıdan index seçimi istenmesi gerektiği, sistem raporunda
        # görünecek göreve (başlığa) yansımış olmalı.
        list_task = next(t for t in tasks if t.action == "list_elements")
        assert "index" in list_task.title.lower()

    def test_click_index_appended_when_index_explicitly_given(self):
        text = (
            "GitHub üzerinde browser-use/browser-use reposunu tarayıcıyla aç. "
            "Etkileşimli elemanları listele. index 2'ye tıkla."
        )
        tasks = _browser_tasks_for(text)

        assert [t.action for t in tasks] == ["open", "list_elements", "click_index"]
        assert tasks[2].metadata["index"] == 2
        assert tasks[2].depends_on == [tasks[1].id]
        assert tasks[1].depends_on == [tasks[0].id]


# --- 6) Diğer departmanların üretim mantığı bozulmamalı --------------------------


class TestBrowserRoutingDoesNotAffectOtherDepartments:
    def test_non_browser_department_task_creation_is_unchanged(self):
        mission = Mission(
            title="Yeni coin araştır.",
            description="Yeni coin araştır.",
            departments=["finance", "browser"],
        )
        orchestrator = DepartmentOrchestrator()
        tasks = orchestrator.create_tasks(mission)

        finance_task = next(t for t in tasks if t.agent == "finance")
        assert finance_task.action == "dispatch"
        assert finance_task.depends_on == []
