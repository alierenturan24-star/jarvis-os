from pathlib import Path

from src.context.context_engine import ContextEngine


class PromptBuilder:
    """Tüm modeller için ortak, kısa ve tutarlı prompt üretir."""

    def __init__(self, root: Path | None = None) -> None:
        self.context = ContextEngine(root=root)

    def build_system_and_user(
        self,
        task: str,
        role: str = "JARVIS",
        instructions: list[str] | None = None,
        include_memory: bool = True,
    ) -> tuple[str, str]:
        """``build()`` ile AYNI içeriği üretir ama sistem bağlamını (JARVIS
        kimliği/misyon/proje durumu/hafıza + rol + kurallar) kullanıcının
        gerçek mesajından AYRI döndürür.

        Sprint 19 düzeltmesi: küçük yerel modeller (ör. Ollama), bağlam ve
        kullanıcı mesajı TEK bir düz metinde birleşince, mesaja cevap vermek
        yerine bağlamı olduğu gibi tekrarlayabiliyor. Bu ikisini ayrı
        döndürmek, çağıranın bunları modele ``system``/``user`` rolleriyle
        AYRI göndermesini sağlar (bkz. ``OllamaProvider.generate``).
        """

        rules = instructions or []
        rule_text = "\n".join(f"- {rule}" for rule in rules)
        context_text = self.context.build(
            task=task,
            include_memory=include_memory,
        )

        # Görev, ContextEngine çıktısının sonunda "## GÜNCEL GÖREV" olarak
        # zaten yer alıyor; burada tekrar eklenmemesi için o bölümü çıkarıyoruz.
        task_marker = "\n\n## GÜNCEL GÖREV"
        marker_index = context_text.find(task_marker)
        if marker_index != -1:
            context_text = context_text[:marker_index]

        system_text = f"""{context_text}

## MODEL ROLÜ
{role}

## BU GÖREVE ÖZEL KURALLAR
{rule_text or '- Anayasaya ve proje bağlamına uygun hareket et.'}

## ÇIKTI
Doğal Türkçe ile, kısa, somut ve gerekçeli cevap üret.
Yabancı dil karışımı, uydurma veri ve gereksiz tekrar kullanma.""".strip()

        return system_text, task.strip()

    def build(
        self,
        task: str,
        role: str = "JARVIS",
        instructions: list[str] | None = None,
        include_memory: bool = True,
    ) -> str:
        system_text, user_text = self.build_system_and_user(
            task=task, role=role, instructions=instructions, include_memory=include_memory,
        )

        return f"""{system_text}

## USER

{user_text}

## ASSISTANT""".strip()
