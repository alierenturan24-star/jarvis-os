class ContextBuilder:

    def build(
        self,
        system_prompt: str,
        conversation_history: str,
        user_message: str,
    ) -> str:

        prompt = f"""
========================
SİSTEM
========================

{system_prompt}

========================
KONUŞMA GEÇMİŞİ
========================

{conversation_history}

========================
KULLANICININ SON MESAJI
========================

{user_message}

========================
CEVAP KURALLARI
========================

- Her zaman Türkçe cevap ver.
- Önce konuşma geçmişini incele.
- Kullanıcının verdiği bilgileri hatırla.
- Gereksiz açıklama yapma.
- Kullanıcı istemedikçe kod yazma.
- Kullanıcı istemedikçe örnek verme.
- Soruya doğrudan cevap ver.
- Bilmiyorsan bunu açıkça söyle.

JARVIS:
"""

        return prompt