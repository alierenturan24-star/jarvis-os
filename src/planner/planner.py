class Planner:

    def create_plan(self, user_message: str):

        plan = []

        text = user_message.lower()

        if any(word in text for word in [
            "ara",
            "internette",
            "google",
            "haber",
            "araştır"
        ]):
            plan.append("research")

        if any(word in text for word in [
            "dosya",
            "klasör",
            "oluştur",
            "sil",
            "kaydet"
        ]):
            plan.append("tool")

        plan.append("chat")

        return plan