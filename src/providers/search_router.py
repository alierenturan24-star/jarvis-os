class SearchRouter:

    def search(self, query: str):

        query = query.lower()

        if "github" in query:
            return "github"

        if any(word in query for word in [
            "nvidia",
            "openai",
            "claude",
            "gemini",
            "groq",
            "deepseek",
            "huggingface",
        ]):
            return "ai"

        return "web"