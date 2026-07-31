class ToolSelector:

    def select(self, message: str):

        text = message.lower()

        if any(x in text for x in [
            "dosya oluştur",
            "dosya yaz",
            "kaydet",
        ]):
            return "file"

        if any(x in text for x in [
            "klasör oluştur",
            "yeni klasör",
        ]):
            return "folder"

        if any(x in text for x in [
            "ara",
            "google",
            "internette",
            "web",
        ]):
            return "web"

        if any(x in text for x in [
            "site aç",
            "tarayıcı aç",
            "chrome aç",
        ]):
            return "browser"

        return None