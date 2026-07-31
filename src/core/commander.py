from pathlib import Path

from src.agents.agent_manager import AgentManager
from src.core.context_builder import ContextBuilder
from src.intent.intent_router import IntentRouter
from src.memory.conversation_memory import ConversationMemory
from src.providers.router import ModelRouter
from src.tools.tool_manager import ToolManager


class Commander:
    """JARVIS görevlerini yöneten ana kontrol merkezi."""

    def __init__(self):
        self.router = ModelRouter()
        self.memory = ConversationMemory()
        self.context_builder = ContextBuilder()
        self.agent_manager = AgentManager()
        self.tool_manager = ToolManager()
        self.intent_router = IntentRouter()

        self.system_prompt = """
Sen JARVIS adlı gelişmiş kişisel yapay zekâ asistansın.

Kimliğin:
- Kullanıcının kişisel yardımcı asistanısın.
- Her zaman Türkçe konuş.
- Samimi, saygılı ve profesyonel ol.

Kurallar:
- Kullanıcı istemedikçe kod yazma.
- Kullanıcı istemedikçe uzun örnekler verme.
- Gereksiz uzun cevap verme.
- Sadece sorulan konuya cevap ver.
- Önceki konuşmaları dikkate al.
- Emin olmadığın bilgileri uydurma.
- Bilmediğin konuda açıkça "Bilmiyorum." de.
- Dosya veya klasör işlemleri gerektiğinde uygun aracı kullan.
"""

    def process(self, user_message: str) -> str:
        user_message = user_message.strip()

        if not user_message:
            return "Lütfen bir komut veya mesaj yaz."

        self.memory.add("Kullanıcı", user_message)

        intent = self.intent_router.detect(user_message)

        tool_response = self._execute_intent(intent)

        if tool_response is not None:
            self.memory.add("Jarvis", tool_response)
            return tool_response

        response = self._generate_chat_response(user_message)

        self.memory.add("Jarvis", response)

        return response

    def _execute_intent(self, intent) -> str | None:
        if intent.name == "empty":
            return "Lütfen bir komut veya mesaj yaz."

        if intent.name == "tools.list":
            return self._list_tools()

        if intent.name == "file.write":
            path = intent.parameters.get("path")
            content = intent.parameters.get("content", "")

            if not path:
                return "Dosya adı bulunamadı."

            return self.tool_manager.execute(
                "file",
                action="write",
                path=path,
                content=content,
            )

        if intent.name == "file.read":
            path = intent.parameters.get("path")

            if not path:
                return "Okunacak dosyanın adı bulunamadı."

            return self.tool_manager.execute(
                "file",
                action="read",
                path=path,
            )

        if intent.name == "folder.create":
            path = intent.parameters.get("path")

            if not path:
                return "Klasör adı bulunamadı."

            return self.tool_manager.execute(
                "folder",
                action="create",
                path=path,
            )

        if intent.name == "folder.list":
            path = Path(
                intent.parameters.get("path", ".")
            )

            try:
                items = sorted(
                    item.name
                    for item in path.iterdir()
                )

                if not items:
                    return "Bu klasörde gösterilecek öğe yok."

                return "Klasörde bulunan öğeler:\n- " + "\n- ".join(items)

            except Exception as error:
                return f"Klasör listelenemedi: {error}"

        return None

    def _list_tools(self) -> str:
        tools = self.tool_manager.list_tools()

        if not tools:
            return "Kullanılabilir araç bulunamadı."

        lines = ["Kullanılabilir araçlar:"]

        for tool in tools:
            name = tool.get("name", "İsimsiz araç")
            description = tool.get(
                "description",
                "Açıklama bulunmuyor.",
            )

            lines.append(f"- {name}: {description}")

        return "\n".join(lines)

    def _generate_chat_response(self, user_message: str) -> str:
        selected_agent = self.agent_manager.find_agent(
            user_message
        )

        history = self.memory.build_prompt()

        if selected_agent:
            agent_info = (
                f"Aktif Agent: {selected_agent.name}\n"
                "Bu agent görevi yönetiyor."
            )
        else:
            agent_info = "Aktif Agent: Genel Sohbet"

        prompt = self.context_builder.build(
            system_prompt=(
                f"{self.system_prompt}\n\n{agent_info}"
            ),
            conversation_history=history,
            user_message=user_message,
        )

        return self.router.generate(
            prompt=prompt,
            provider_name="ollama",
        )