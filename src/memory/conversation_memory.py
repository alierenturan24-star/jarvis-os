class ConversationMemory:
    def __init__(self, max_messages=10):
        self.max_messages = max_messages
        self.messages = []

    def add(self, role: str, content: str):
        self.messages.append(
            {
                "role": role,
                "content": content,
            }
        )

        if len(self.messages) > self.max_messages:
            self.messages.pop(0)

    def build_prompt(self) -> str:

        prompt = ""

        for message in self.messages:
            prompt += f"{message['role']}: {message['content']}\n"

        return prompt

    def clear(self):
        self.messages = []