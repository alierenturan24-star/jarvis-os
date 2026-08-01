class Verifier:

    def verify(self, task, result):

        if result is None:
            return False

        if isinstance(result, str):

            if result.strip() == "":
                return False

            if result.lower().startswith("hata"):
                return False

        return True