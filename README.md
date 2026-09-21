# Jarvis OS

Türkçe konuşan, çok ajanlı, çoklu-LLM-sağlayıcılı bir kişisel AI işletim sistemi prototipi.

## Kurulum

### Windows 11 — tek tık (önerilen)

1. Depoyu indirin/klonlayın.
2. `START_JARVIS.bat` dosyasına çift tıklayın.
3. İlk çalışmada oluşturulan `.env` dosyasına kullandığınız sağlayıcının API anahtarını ekleyin ve dosyayı yeniden açın.

Başlatıcı yönetici izni istemez; `.venv` ortamını kurar, gereksinimleri yalnızca değiştiğinde günceller, depodaki yerel FFmpeg'i doğrular ve Control Center'ı yalnız `127.0.0.1:8765` üzerinde açar. `.env` mevcutsa üzerine yazmaz. Claude Code isteğe bağlıdır; kurulu ve giriş yapılmışsa JARVIS kod görevlerinde kontrollü olarak kullanabilir.

Panelde **Ayarlar ve Hazırlık** bölümünden video, ses, AI sağlayıcısı, YouTube hesabı, Claude Code ve güvenli kimlik kasasının gerçek durumunu görebilirsiniz.

### Elle kurulum

```bash
pip install -r requirements.txt
```

Proje kök dizinine `.env.example` dosyasını `.env` adıyla kopyalayın ve yalnız kullanacağınız sağlayıcının anahtarını ekleyin (bkz. `src/config/settings.py`):

```
DEFAULT_PROVIDER=gemini
GEMINI_API_KEY=
# İsteğe bağlı: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY,
# DEEPSEEK_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, AIML_API_KEY ...
```

## Çalıştırma

Kontrol paneli:

```bash
python control_center.py
```

Terminal uygulaması:

```bash
python main.py
```

Komut satırında `çık` / `exit` ile kapatılır, `durum` ile çalışma zamanı durumu görüntülenir.

## Gerçek çalışma sınırları

- Paneldeki görev kutusu gerçek `/api/command` hattına bağlıdır; görevler planner ve ilgili worker'a yönlenir.
- YouTube hattı trend/konu araştırması, senaryo, başlık/açıklama, ses, altyazı, yerel MP4 render ve kalite kontrolü yapabilir. Kaynak veya trend verisi yoksa sonuç uydurmaz.
- YouTube hesabı resmi Google OAuth ile ayrıca bağlanmalıdır. Yayın otomatik değildir; kalite sonrasında insan onayı gerekir.
- Finans hattı gerçek piyasa verisiyle araştırma, backtest ve paper pozisyon çalıştırır. Gerçek para emri kod yolu kapalıdır.
- Claude Code yalnız kurulu ve giriş yapılmışsa kod görevlerinde; izin listesi, süre sınırı ve güvenlik politikası içinde kullanılabilir.

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
