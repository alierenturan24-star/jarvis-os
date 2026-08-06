from typing import List, Dict


class DecisionEngine:

    def __init__(self):
        pass

    def choose_best(self, responses: List[Dict]) -> Dict:
        """
        responses örneği:

        [
            {
                "provider": "claude",
                "response": "...",
                "score": 94
            },
            {
                "provider": "openai",
                "response": "...",
                "score": 90
            }
        ]
        """

        if not responses:
            return {
                "provider": None,
                "response": "Hiç cevap alınamadı.",
                "score": 0
            }

        return max(
            responses,
            key=lambda x: x.get("score", 0)
        )

    def rank(self, responses):

        return sorted(
            responses,
            key=lambda x: x.get("score", 0),
            reverse=True
        )