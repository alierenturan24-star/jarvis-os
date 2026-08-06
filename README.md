# Jarvis OS

Türkçe konuşan, çok ajanlı, çoklu-LLM-sağlayıcılı bir kişisel AI işletim sistemi prototipi.

## Kurulum

```bash
pip install -r requirements.txt
```

Proje kök dizinine bir `.env` dosyası ekleyin (bkz. `src/config/settings.py` içindeki tüm anahtarlar):

```
DEFAULT_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest
# İsteğe bağlı: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY,
# DEEPSEEK_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, AIML_API_KEY ...
```

## Çalıştırma

```bash
python main.py
```

Komut satırında `çık` / `exit` ile kapatılır, `durum` ile çalışma zamanı durumu görüntülenir.

## Testler

```bash
pytest
```

## Mimari

Çalışan çekirdek çağrı zinciri:

```
main.py
  -> src/core/runtime.py   (JarvisRuntime: BOOTING/READY/WORKING/SLEEPING/STOPPED durum makinesi)
    -> src/core/jarvis.py  (Jarvis: Brain + DecisionEngine + AgentRouter + WorkflowEngine'i bağlar)
      -> src/ai/brain.py            (LLM sağlayıcılarına erişim)
      -> src/decision/decision_engine.py  (riskli komutları engelleme/onay isteme)
      -> src/memory/memory_manager.py     (remember/recall için kalıcı anahtar-değer hafızası, memory.json)
      -> src/core/agent_router.py   (WorkerRegistry üzerinden görevleri ajanlara yönlendirir)
        -> src/registry/worker_registry.py
        -> src/agents/*  (browser, research, opportunity, finance, evolution, chat, coding, planning)
      -> src/core/workflow_engine.py (Planner + TaskQueue + Executor + ResultAggregator pipeline'ı)
```

Diğer önemli paketler:

- `src/providers/` — Ollama, OpenAI, Anthropic, Gemini, DeepSeek, Groq, OpenRouter, AIML sağlayıcılarını tek arayüzde birleştiren `ModelRouter`.
- `src/planner/` — kullanıcı mesajını görevlere bölen kural tabanlı planlayıcı.
- `src/council/` — çoklu-model konsensüs mekanizması (`ChatAgent` tarafından kullanılır).
- `src/evolution/`, `src/finance/`, `src/opportunity/`, `src/research/` — Collector → Scorer/Summarizer → ReportBuilder → Manager desenini izleyen, `workspace/` altına rapor üreten "departman" modülleri.
- `src/context/` — belge/hafıza/görev bağlamından prompt üreten katman.
- `src/config/settings.py` — `.env` tabanlı merkezi ayar sınıfı.
- `docs/` — proje anayasası (`constitution.md`), misyon (`mission.md`) ve güncel bağlam (`project_context.md`).

Not: `src/` altında bu zincirin dışında kalan, henüz temizlenmemiş eski/deneysel modüller de bulunuyor (bkz. `docs/project_context.md`). Yeni geliştirme yaparken yukarıdaki aktif çağrı zincirini referans alın.
