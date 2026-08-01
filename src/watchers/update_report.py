class UpdateReport:

    def build(self, updates):

        text = []

        text.append("===== GÜNCELLEME RAPORU =====")

        if not updates:

            text.append("Yeni güncelleme bulunamadı.")

        else:

            for update in updates:

                text.append("")

                text.append(f"Sağlayıcı : {update['provider']}")

                text.append(f"Kategori : {update['category']}")

                text.append(f"Durum : {update['status']}")

        text.append("")

        text.append("=============================")

        return "\n".join(text)