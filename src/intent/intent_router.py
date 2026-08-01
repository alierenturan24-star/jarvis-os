class IntentRouter:

    def detect(self, text):

        text = text.lower()

        if any(word in text for word in [
            "google",
            "youtube",
            "chrome",
            "tarayıcı",
            ".com",
            "aç"
        ]):
            return "browser"

        if any(word in text for word in [
            "dosya",
            ".txt",
            ".py",
            "oku",
            "yaz"
        ]):
            return "file"

        if any(word in text for word in [
            "klasör",
            "dizin"
        ]):
            return "folder"

        if any(word in text for word in [
            "hesap makinesi",
            "not defteri",
            "paint",
            "program"
        ]):
            return "program"

        return None