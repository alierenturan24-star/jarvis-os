class ProviderSelector:
    """
    Görevin türüne, gizlilik ihtiyacına ve ücretsiz kullanım tercihine
    göre uygun yapay zekâ sağlayıcısını seçer.
    """

    def select(
        self,
        message: str,
        available_providers: set[str],
    ) -> str:
        text = message.lower()

        # Bilgisayardaki özel dosyalar için öncelikle yerel model.
        if any(
            keyword in text
            for keyword in [
                "özel",
                "gizli",
                "kişisel dosya",
                "yerel",
                "internetsiz",
            ]
        ):
            return self._first_available(
                ["ollama", "mock"],
                available_providers,
            )

        # Kodlama görevleri.
        if any(
            keyword in text
            for keyword in [
                "kod yaz",
                "kod düzelt",
                "python",
                "github",
                "hata düzelt",
                "proje geliştir",
                "refactor",
            ]
        ):
            return self._first_available(
                [
                    "codex",
                    "claude_code",
                    "qwen",
                    "deepseek",
                    "ollama",
                    "mock",
                ],
                available_providers,
            )

        # Araştırma ve uzun analiz görevleri.
        if any(
            keyword in text
            for keyword in [
                "araştır",
                "incele",
                "karşılaştır",
                "şirket analizi",
                "piyasa analizi",
                "haberleri kontrol et",
            ]
        ):
            return self._first_available(
                [
                    "gemini",
                    "openai",
                    "claude",
                    "nvidia",
                    "openrouter",
                    "ollama",
                    "mock",
                ],
                available_providers,
            )

        # Finans görevleri.
        if any(
            keyword in text
            for keyword in [
                "borsa",
                "kripto",
                "hisse",
                "yatırım",
                "portföy",
                "piyasa",
            ]
        ):
            return self._first_available(
                [
                    "openai",
                    "claude",
                    "gemini",
                    "deepseek",
                    "ollama",
                    "mock",
                ],
                available_providers,
            )

        # İçerik ve video görevleri.
        if any(
            keyword in text
            for keyword in [
                "video",
                "youtube",
                "senaryo",
                "seslendirme",
                "thumbnail",
                "içerik",
            ]
        ):
            return self._first_available(
                [
                    "gemini",
                    "claude",
                    "openai",
                    "qwen",
                    "ollama",
                    "mock",
                ],
                available_providers,
            )

        # Normal sohbet için mümkünse ücretsiz yerel model.
        return self._first_available(
            ["ollama", "openrouter", "mock"],
            available_providers,
        )

    @staticmethod
    def _first_available(
        preferences: list[str],
        available_providers: set[str],
    ) -> str:
        for provider_name in preferences:
            if provider_name in available_providers:
                return provider_name

        raise RuntimeError(
            "Kullanılabilir hiçbir yapay zekâ sağlayıcısı bulunamadı."
        )
