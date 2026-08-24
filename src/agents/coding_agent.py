import re
from pathlib import Path

from src.agents.base_agent import BaseAgent
from src.agents.claude_code_edit_adapter import ClaudeCodeEditAdapter
from src.config.settings import PROJECT_ROOT
from src.planner.task import Task
from src.providers.router import ModelRouter
from src.providers.provider_manager import TASK_CODING

# JARVIS PRIORITY (Mode B): repo-level edit/test delegation is strictly
# OPT-IN via ``task.metadata["coding_mode"] == "repo_edit"`` -- ordinary
# coding chat/advisory tasks (the default, unset metadata) are completely
# UNCHANGED and never touch the edit adapter. Natural-language auto-
# detection of "this is an edit task" is intentionally NOT built here (see
# final report NEXT ACTION) -- the caller (mission engine, a future
# command, or a live smoke test) must set this metadata explicitly.
CODING_MODE_REPO_EDIT = "repo_edit"

# Sprint 45 (TASK PROMPT FIDELITY FIX): 2026-08-23 canlı smoke testinde
# bulundu -- eski prompt yalnızca "Görev: {task.target}" diyordu ve hem
# claude_code'un zaman aşımına uğradığı hem de Codex fallback'inin
# başarıyla döndüğü koşuda, Codex somut görevi YOK SAYIP genel bir
# "jarvis-os projesinde size nasıl yardımcı olabilirim?" netleştirme
# sorusuyla cevap verdi. Kök neden Codex'e ÖZGÜ değildi -- ProviderManager
# TEK bir ``prompt`` string'ini (bkz. ``route_and_generate``/
# ``_generate_for_route``) HANGİ aday sağlayıcı denenirse denensin AYNEN
# yeniden kullanır, bu yüzden burada tek bir düzeltme hem claude_code'u HEM
# fallback zincirindeki her sağlayıcıyı (Codex dahil) kapsar -- quality.py
# için özel bir durum İCAT EDİLMEDİ, genel görev iletimi düzeltildi.
_FILE_PATH_PATTERN = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}")


def _extract_target_paths(text: str) -> list[str]:
    """Serbest metindeki muhtemel repo-göreli dosya yollarını (ör.
    ``src/media/quality.py``) çıkarır -- modelin bir paragrafın içinde
    bunu fark etmesine GÜVENMEK yerine, prompt'ta AÇIKÇA öne çıkarılır."""

    return list(dict.fromkeys(_FILE_PATH_PATTERN.findall(text or "")))


class CodingAgent(BaseAgent):
    def __init__(self, edit_adapter: ClaudeCodeEditAdapter | None = None) -> None:
        super().__init__("Coding Agent")
        self.router = ModelRouter()
        self.edit_adapter = edit_adapter or ClaudeCodeEditAdapter()

    def health(self) -> dict:
        return {
            "agent": self.name,
            "available": True,
            "providers": self.router.manager.available_names(),
        }

    def execute(self, task: Task) -> str:
        metadata = getattr(task, "metadata", None)
        if metadata is None:
            metadata = {}

        if metadata.get("coding_mode") == CODING_MODE_REPO_EDIT:
            return self._execute_repo_edit(task, metadata)

        prompt = self._build_advisory_prompt(task)
        preferred = metadata.get("preferred_ai_provider")
        return self.router.manager.route_and_generate(
            prompt=prompt, task_type=TASK_CODING, preferred_provider=preferred,
        ).output

    @staticmethod
    def _build_advisory_prompt(task: Task) -> str:
        """Salt-okunur/danışma (advisory) görevler için prompt -- REQUIREMENTS
        2/3 (task prompt fidelity + read-only mode): repository root, tam
        kullanıcı görevi (kısaltılmadan/genelleştirilmeden), açık read-only
        niyeti, varsa hedef dosya/yol, ve JARVIS'e doğrudan iletilebilir bir
        cevap üretme talimatı -- hepsi TEK bir prompt'ta, hangi sağlayıcı
        denenirse denensin (bkz. modül-üstü not) AYNEN korunur."""

        goal = task.target or ""
        paths = _extract_target_paths(goal)
        path_line = (
            f"İlgili dosya/yol(lar): {', '.join(paths)}\n" if paths else ""
        )
        return (
            "Sen JARVIS Coding Agent'sın; JARVIS'in kendi deposu üzerinde "
            f"çalışıyorsun (repository root: {PROJECT_ROOT}).\n"
            "Her zaman Türkçe konuş.\n"
            "Bu görev SALT-OKUNUR/danışma niteliğindedir (read-only/advisory) "
            "-- repo_edit DEĞİL. Hiçbir dosyayı OLUŞTURMA, DEĞİŞTİRME veya "
            "SİLME; yalnızca oku/incele/analiz et.\n"
            f"{path_line}"
            "Elindeki araçları (Read/Glob/Grep) KULLANARAK deponun gerçek "
            "içeriğini incele. Netleştirme SORMA, ek bilgi TALEP ETME -- "
            "görevi doğrudan tamamla ve JARVIS'in kullanıcıya olduğu gibi "
            "iletebileceği somut, eksiksiz bir cevap üret.\n"
            "Kullanıcı tam dosya istiyorsa parça parça kod verme.\n\n"
            f"Görev: {goal}\n"
        )

    def _execute_repo_edit(self, task: Task, metadata: dict) -> str:
        repo_path = metadata.get("repo_path")
        if not repo_path:
            return "claude_code sağlayıcı hatası: repo_path metadata alanı eksik."

        outcome = self.edit_adapter.delegate_edit(
            task.target,
            repo_path=Path(repo_path),
            approved=bool(metadata.get("approved", False)),
            standing_permission=bool(metadata.get("standing_permission", False)),
            run_tests=bool(metadata.get("run_tests", False)),
            test_command=metadata.get("test_command"),
        )
        # Sprint 44+ Control Center exposure pattern (bkz. observability.py):
        # yapılandırılmış ayrıntılar task.metadata'ya YAZILIR, aynı
        # ``preferred_ai_provider``'ın ZATEN okunduğu yerden okunabilsin diye.
        metadata.update(outcome.to_dict())
        return outcome.result_summary
