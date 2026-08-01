class Reporter:

    def build(self, results):

        report = []

        report.append("=== GÖREV RAPORU ===")

        for i, result in enumerate(results, start=1):

            report.append(f"{i}. {result}")

        report.append("====================")

        return "\n".join(report)