class ReasoningEngine:

    def analyze(self, message: str):

        text = message.lower()

        plan = {
            "internet": False,
            "browser": False,
            "coding": False,
            "research": False,
            "memory": True,
            "priority": "normal",
            "agents": [],
        }

        if any(x in text for x in [
            "araştır",
            "incele",
            "karşılaştır",
        ]):
            plan["research"] = True
            plan["internet"] = True
            plan["agents"].append("research")

        if any(x in text for x in [
            "google",
            "youtube",
            "github",
            "aç",
        ]):
            plan["browser"] = True
            plan["agents"].append("browser")

        if any(x in text for x in [
            "kod",
            "python",
            "programla",
        ]):
            plan["coding"] = True
            plan["agents"].append("coding")

        return plan