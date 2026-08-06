class GoalEngine:

    def __init__(self):

        self.goals = [

            "Jarvis'i geliştir",

            "Gelir oluştur",

            "Yeni AI araçlarını öğren",

            "YouTube sistemi kur",

            "Finans araştır",

        ]

    def all(self):

        return self.goals

    def add(self, goal):

        self.goals.append(goal)