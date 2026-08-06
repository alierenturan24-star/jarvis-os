class Security:

    BLOCKED = [

        "format",

        "rm -rf",

        "delete",

        "del ",

        "shutdown",

        "reg delete",

    ]

    def check(self, message):

        text = message.lower()

        for word in self.BLOCKED:

            if word in text:

                return False

        return True