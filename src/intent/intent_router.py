import re

from src.intent.intent_result import IntentResult


class IntentRouter:
    """Kullanıcının isteğini uygun işlem türüne yönlendirir."""

    FILE_PATTERN = re.compile(
        r'([\wğüşöçıİĞÜŞÖÇ\-. ]+\.[a-zA-Z0-9]+)',
        re.IGNORECASE,
    )

    def detect(self, user_message: str) -> IntentResult:
        original_message = user_message.strip()
        normalized_message = original_message.lower()

        if not normalized_message:
            return IntentResult(
                name="empty",
                parameters={},
            )

        if normalized_message in {"araçlar", "araçları göster"}:
            return IntentResult(name="tools.list")

        filename = self._extract_filename(original_message)

        if filename and any(
            word in normalized_message
            for word in ("oluştur", "hazırla", "yeni dosya")
        ):
            content = self._extract_content(original_message)

            return IntentResult(
                name="file.write",
                parameters={
                    "path": filename,
                    "content": content,
                },
            )

        if filename and any(
            word in normalized_message
            for word in ("oku", "göster", "içeriği ne")
        ):
            return IntentResult(
                name="file.read",
                parameters={
                    "path": filename,
                },
            )

        if "klasör" in normalized_message and any(
            word in normalized_message
            for word in ("oluştur", "aç", "hazırla")
        ):
            folder_name = self._extract_folder_name(original_message)

            if folder_name:
                return IntentResult(
                    name="folder.create",
                    parameters={
                        "path": folder_name,
                    },
                )

        if any(
            phrase in normalized_message
            for phrase in (
                "dosyaları listele",
                "dosyaları göster",
                "klasörde ne var",
                "projedeki dosyalar",
            )
        ):
            return IntentResult(
                name="folder.list",
                parameters={
                    "path": ".",
                },
            )

        return IntentResult(
            name="chat",
            parameters={
                "message": original_message,
            },
        )

    def _extract_filename(self, message: str) -> str | None:
        match = self.FILE_PATTERN.search(message)

        if match is None:
            return None

        filename = match.group(1).strip()
        filename = filename.strip('"\'.,;:!?')

        words = filename.split()

        if len(words) > 1:
            filename = words[-1]

        return filename or None

    def _extract_content(self, message: str) -> str:
        content_markers = (
            "içine",
            "içeriğine",
            "şunu yaz",
        )

        lowered_message = message.lower()

        for marker in content_markers:
            marker_position = lowered_message.find(marker)

            if marker_position != -1:
                content = message[
                    marker_position + len(marker):
                ].strip()

                return content.strip('"\' ')

        return ""

    def _extract_folder_name(self, message: str) -> str | None:
        cleaned_message = message.strip().strip(".!?")

        patterns = (
            r'["\']([^"\']+)["\']',
            r'(.+?)\s+adında\s+klasör',
            r'(.+?)\s+isimli\s+klasör',
            r'klasör\s+oluştur\s+(.+)',
            r'(.+?)\s+klasörü\s+oluştur',
            r'(.+?)\s+klasörü\s+aç',
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                cleaned_message,
                re.IGNORECASE,
            )

            if match:
                folder_name = match.group(1).strip()
                folder_name = folder_name.strip('"\' ')

                if folder_name:
                    return folder_name

        words = cleaned_message.split()

        ignored_words = {
            "klasör",
            "klasörü",
            "oluştur",
            "aç",
            "hazırla",
            "yeni",
            "bir",
            "adında",
            "isimli",
        }

        candidates = [
            word.strip('"\'.,;:!?')
            for word in words
            if word.lower() not in ignored_words
        ]

        if not candidates:
            return None

        return candidates[-1]