class ToolSelector:

    TOOL_RULES = {
        "file": [
            "dosya oluştur",
            "dosya yaz",
            "kaydet",
            ".txt",
            ".py",
        ],

        "folder": [
            "klasör oluştur",
            "yeni klasör",
            "dizin oluştur",
        ],

        "browser": [
            "google aç",
            "youtube aç",
            "github aç",
            "chatgpt aç",
            "tarayıcı aç",
            "chrome aç",
        ],

        "web": [
            "araştır",
            "internette ara",
            "web ara",
            "google'da ara",
        ],

        "program": [
            "hesap makinesi",
            "not defteri",
            "paint",
            "vs code",
        ],
    }

    def select(self, message: str):

        text = message.lower()

        for tool_name, keywords in self.TOOL_RULES.items():

            if any(keyword in text for keyword in keywords):
                return tool_name

        return None