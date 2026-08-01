from src.planner.task import Task


class Planner:

    def build(self, message: str):

        text = message.lower()

        tasks = []

        if "google" in text:

            tasks.append(
                Task(
                    agent="browser",
                    action="open_google"
                )
            )

        elif "youtube" in text:

            tasks.append(
                Task(
                    agent="browser",
                    action="open_youtube"
                )
            )

        elif "araştır" in text:

            tasks.append(
                Task(
                    agent="research",
                    action="research",
                    target=message
                )
            )

        else:

            tasks.append(
                Task(
                    agent="chat",
                    action="chat",
                    target=message
                )
            )

        return tasks