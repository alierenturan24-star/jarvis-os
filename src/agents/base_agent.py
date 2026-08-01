class BaseAgent:

    name = "Base Agent"

    def plan(self, task):

        return task

    def execute(self, task):

        raise NotImplementedError

    def verify(self, result):

        if result is None:
            return False

        if isinstance(result, str):

            if result.strip() == "":
                return False

            if result.lower().startswith("hata"):
                return False

        return True

    def report(self, result):

        return result