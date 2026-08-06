from __future__ import annotations

from typing import Optional

from src.jobs.task import Task
from src.jobs.task_status import TaskStatus
from src.mission.models import Mission

# Sprint 16 (CEO Report Engine): Mission çalışıyor, department'lar
# çalışıyor, GitHub/Evaluation/Sandbox/Integration gerçekten çalışıyor
# (Sprint 15) -- ama kullanıcı sonucu GÖREMİYORDU (Jarvis eskiden yalnızca
# durum sayaçlarını gösteriyordu, bkz. Sprint 15 denetim raporu). Bu
# modül YENİ bir analiz/puanlama/rapor motoru İCAT ETMEZ; yalnızca
# ``src.mission.department_adapters`` içindeki adaptörlerin ZATEN
# hesapladığı gerçek nesneleri (``task.metadata["report"]``, bkz. o
# dosya) tek bir okunabilir CEO raporuna BİRLEŞTİRİR.

SEPARATOR = "-" * 32
KNOWN_TABLE_DEPARTMENTS = {"github", "evaluation", "sandbox", "integration", "ai_discovery"}


def build_ceo_report(mission: Mission) -> str:
    """Mission'ın gerçek department sonuçlarını CEO raporu olarak biçimlendirir."""

    tasks_by_department: dict[str, Task] = {task.agent: task for task in mission.tasks}

    sections = [_mission_section(mission)]

    # Sprint 17: "AI Discovery" bölümü, klasik Sprint 16 şablonunun
    # (GitHub/Evaluation/Sandbox/Integration) parçası DEĞİL -- yalnızca bu
    # departman mission'da GERÇEKTEN seçildiyse gösterilir (aksi halde her
    # mission'da alakasız bir "seçilmedi" notu gösterirdi).
    if "ai_discovery" in tasks_by_department:
        sections.append(_ai_discovery_section(tasks_by_department.get("ai_discovery")))

    sections.extend([
        _github_section(tasks_by_department.get("github")),
        _evaluation_section(tasks_by_department.get("evaluation")),
        _sandbox_section(tasks_by_department.get("sandbox")),
        _integration_section(tasks_by_department.get("integration")),
    ])

    other = _other_departments_section(tasks_by_department)
    if other:
        sections.append(other)

    sections.append(_ceo_section(mission, tasks_by_department))

    return f"\n{SEPARATOR}\n\n".join(sections)


# --- Ortak yardımcı --------------------------------------------------------------


def _task_note(task: Optional[Task]) -> Optional[str]:
    """Bölüm bir tablo yerine kısa bir durum notu göstermeli mi?

    ``None`` dönerse görev COMPLETED ve gerçek rapor verisi var demektir
    -- çağıran normal tabloyu basar. Aksi halde dönen metin doğrudan
    gösterilecek nottur (departman bu mission'da seçilmedi / handler yok
    / tamamlanmadı)."""

    if task is None:
        return "(bu mission'da bu departman seçilmedi)"
    if task.handler is None:
        return "Bağlı değil: handler tanımlı değil (bu departman henüz gerçek bir modüle bağlanmadı)."
    if task.status != TaskStatus.COMPLETED:
        return f"Tamamlanmadı (durum: {task.status.value}). Hata: {task.error or '-'}"
    return None


def _sandbox_verdict(result) -> str:
    if result is None:
        return "FAIL"
    if result.status.value != "ready_for_review":
        return "FAIL"
    if result.network_risk == "HIGH" or result.execution_risk == "HIGH" or result.dependency_risk == "HIGH":
        return "FAIL"
    return "PASS"


# --- Bölümler ----------------------------------------------------------------


def _mission_section(mission: Mission) -> str:
    return (
        "MISSION\n"
        f"{mission.title}\n\n"
        f"Tür: {mission.mission_type.value.upper()}\n"
        f"Risk: {mission.risk_level}\n"
        f"Confidence: %{mission.confidence:.0f}\n"
        f"Tahmini süre (Mission düzeyinde, kaba sezgisel tahmin): {mission.estimated_duration:.0f} dk"
    )


def _ai_discovery_section(task: Optional[Task]) -> str:
    """Sprint 17: GitHub dışındaki AI ekosistemi (yeni model/araç/agent
    framework) taraması -- ``EvolutionCollector``/``EvolutionScorer``'ın
    (mevcut) gerçek sonucunu gösterir. Ölçülmeyen iddialar (ör. "X,
    Claude Code'dan daha hızlı") HİÇBİR kaynakta bulunmadığı için
    UYDURULMAZ -- yalnızca gerçekten hesaplanmış sinyaller (skor,
    ücretsiz/açık-kaynak işareti, hangi arama sorgusundan geldiği)
    gösterilir.
    """

    header = "AI Discovery"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    data = task.metadata.get("report") or {}
    top = data.get("top") or []
    total = data.get("total_found", 0)

    if not top:
        return f"{header}\n0 yeni AI aracı/modeli bulundu."

    free_count = sum(1 for item in top if item.get("cost_advantage", 0) >= 90)

    lines = [
        header,
        f"{total} yeni aday bulundu (EvolutionCollector, gerçek web araması).",
        f"{free_count}/{len(top)} ücretsiz/açık-kaynak sinyali taşıyor "
        "(EvolutionScorer.cost_advantage >= 90).",
        "",
        f"{'Skor':>5}  {'Başlık':<46} {'Kaynak sorgu':<36} Bağlantı",
    ]
    for item in top:
        title = str(item.get("title", ""))[:46]
        query = str(item.get("query", ""))[:36]
        lines.append(f"{item.get('score', 0):>5}  {title:<46} {query:<36} {item.get('url', '')}")

    lines.append("")
    lines.append(
        "Not: Skorlar EvolutionScorer'ın (mevcut) goal_fit/safety/cost_advantage/"
        "expected_value sezgisel ölçütlerine dayanır. \"X, Claude Code'dan daha "
        "hızlı\" gibi karşılaştırmalı performans iddiaları hiçbir kaynakta "
        "ÖLÇÜLMEDİĞİ için raporlanmaz."
    )
    return "\n".join(lines)


def _github_section(task: Optional[Task]) -> str:
    header = "GitHub"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    data = task.metadata.get("report") or {}
    total = data.get("total_found", 0)
    top = data.get("top", [])

    if not top:
        return f"{header}\n0 repository bulundu."

    lines = [header, f"{total} repository bulundu.", "", "En iyi 5:"]
    lines.append(f"{'★':>5}  {'Repo':<34} {'Star':>7}  {'Lisans':<10} {'Risk':>6}  Neden seçildi")
    for item in top:
        repo = item["repo"]
        lines.append(
            f"{item['quality_score']:>5.0f}  {repo.full_name:<34} {repo.stars:>7,}  "
            f"{(repo.license or 'yok'):<10} {item['risk_score']:>6.0f}  {item['reason']}"
        )
    return "\n".join(lines)


def _ceo_candidate_decision(evaluation, sandbox_verdict: str, integration_plan) -> tuple[str, str]:
    """Sprint 18: CEO'nun her aday için ÖNER/BEKLET/REDDET kararı.

    Yeni bir puanlama sistemi İCAT ETMEZ -- yalnızca zaten hesaplanmış
    etiketlere (``EvaluationEngine.suitable_for_jarvis``/``risk_level``,
    Sandbox'ın PASS/FAIL'i, ``IntegrationPlanner``'ın ``merge_ready``/
    ``estimated_risk``'i) dayalı basit, deterministik bir karar ağacıdır
    (bkz. ``src.evaluation.evaluation_engine`` içindeki ``_risk_level``/
    ``_is_suitable`` ile AYNI desen).
    """

    if not evaluation.suitable_for_jarvis or evaluation.risk_level == "HIGH":
        return "REDDET", evaluation.recommendation

    if sandbox_verdict == "FAIL":
        reason = "Sandbox FAIL"
        if integration_plan is not None:
            reason += f" (Integration riski: {integration_plan.estimated_risk})."
        return "REDDET", f"{reason} Evaluation uygun bulsa da statik analiz aşamasında elendi."

    merge_ready = bool(integration_plan and integration_plan.merge_ready)
    if merge_ready and evaluation.risk_level == "LOW":
        return "ÖNER", (
            f"Evaluation uygun buldu ({evaluation.recommendation}) Sandbox PASS, "
            f"Integration merge'e hazır (risk {integration_plan.estimated_risk})."
        )

    integration_risk = integration_plan.estimated_risk if integration_plan else "bilinmiyor"
    return "BEKLET", (
        f"Kısmen olumlu: {evaluation.recommendation} Sandbox {sandbox_verdict}, "
        f"Integration henüz merge'e hazır değil (risk {integration_risk}) — insan gözden geçirmesi önerilir."
    )


def _evaluation_section(task: Optional[Task]) -> str:
    header = "Evaluation"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    data = task.metadata.get("report") or {}
    candidates = data.get("candidates") or []

    if not candidates:
        return f"{header}\nDeğerlendirilecek repo bulunamadı."

    lines = [header, "AI Validation Pipeline: GitHub -> Evaluation -> Sandbox -> IntegrationPlanner -> CEO kararı", ""]
    lines.append(
        f"{'Repo':<30} {'Lisans':<8} {'Risk':<7} {'Overall':>8} {'Relevance':>10} "
        f"{'Compat.':>8} {'Sandbox':<8} {'Int. Zorluk':<12} {'Karar':<7} Gerekçe"
    )
    for candidate in candidates:
        repo = candidate["repo"]
        evaluation = candidate["evaluation"]
        sandbox_verdict = candidate["sandbox_verdict"]
        integration_plan = candidate.get("integration_plan")

        decision, reason = _ceo_candidate_decision(evaluation, sandbox_verdict, integration_plan)
        candidate["decision"] = decision
        candidate["reason"] = reason

        lines.append(
            f"{repo.full_name:<30} {(repo.license or 'yok'):<8} {evaluation.risk_level:<7} "
            f"{evaluation.overall_score:>7.0f}/100 {evaluation.relevance_score:>9.0f}/100 "
            f"{evaluation.compatibility_score:>7.0f}/100 {sandbox_verdict:<8} "
            f"{evaluation.integration_difficulty:<12} {decision:<7} {reason}"
        )
    return "\n".join(lines)


def _sandbox_section(task: Optional[Task]) -> str:
    header = "Sandbox"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    data = task.metadata.get("report") or {}
    result = data.get("result")
    if result is None:
        return f"{header}\nDenenecek repo bulunamadı."

    repo = data.get("repo")
    verdict = _sandbox_verdict(result)

    lines = [
        header,
        f"Repo: {repo.full_name if repo else result.repository_name}",
        verdict,
        "CPU: ölçülmedi (SandboxManager yalnızca statik analiz yapar, kod çalıştırmaz)",
        "RAM: ölçülmedi (SandboxManager yalnızca statik analiz yapar, kod çalıştırmaz)",
        f"Taranan boyut: {result.total_size_mb} MB, {result.files_scanned} dosya (dil: {result.detected_language or 'bilinmiyor'})",
        f"Süre (gerçek, ölçüldü): {data.get('duration_seconds', 0.0):.2f} sn",
        f"Öneri: {result.recommended_action}",
    ]
    return "\n".join(lines)


def _integration_section(task: Optional[Task]) -> str:
    header = "Integration"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    data = task.metadata.get("report") or {}
    plan = data.get("plan")
    if plan is None:
        return f"{header}\nEntegrasyon planı üretilemedi (uygun aday bulunamadı)."

    lines = [header, f"Repo: {plan.repository_name}", "", "Entegrasyon sırası:"]
    for index, step in enumerate(plan.migration_steps, start=1):
        lines.append(f"  {index}. {step}")

    lines.append(f"Risk: {plan.estimated_risk} (kırıcı değişiklik olasılığı: %{plan.breaking_change_probability:.0f})")
    lines.append(
        "Tahmini süre: IntegrationPlanner bu alanı üretmiyor "
        "(yalnızca dosya/değişiklik sayısı tahmini var, aşağıda)."
    )
    lines.append(f"Kod değişikliği: ~{plan.estimated_files} dosya, ~{plan.estimated_changes} değişiklik noktası")
    lines.append(f"Merge'e hazır: {'evet' if plan.merge_ready else 'hayır'}")
    return "\n".join(lines)


def _other_departments_section(tasks_by_department: dict[str, Task]) -> str:
    """github/evaluation/sandbox/integration DIŞINDAKİ (research, finance,
    browser, ...) departmanlar için şablonun tanımlamadığı ama mission'da
    seçilmiş olabilecek sonuçları kaybetmemek için kısa bir özet satırı."""

    others = [(name, task) for name, task in tasks_by_department.items() if name not in KNOWN_TABLE_DEPARTMENTS]
    if not others:
        return ""

    lines = ["Diğer departmanlar"]
    for name, task in others:
        note = _task_note(task)
        if note:
            lines.append(f"- {name}: {note}")
        else:
            output = task.result.output if task.result else ""
            lines.append(f"- {name}: {output}")
    return "\n".join(lines)


def _ceo_section(mission: Mission, tasks_by_department: dict[str, Task]) -> str:
    """CEO'nun departman sonuçlarından ürettiği öneri/sonuç/sonraki adım.

    Yeni bir puanlama/analiz İCAT ETMEZ -- yalnızca zaten hesaplanmış
    alanlara (mission.risk_level/confidence, Evaluation'ın suitable_count,
    Sandbox'ın PASS/FAIL durumu, Integration'ın merge_ready'si) dayalı
    basit, deterministik bir karar metni üretir.
    """

    eval_task = tasks_by_department.get("evaluation")
    eval_data = (eval_task.metadata.get("report") if eval_task else None) or {}
    suitable_count = (eval_data.get("summary") or {}).get("suitable_count", 0)
    candidates = eval_data.get("candidates") or []

    sandbox_task = tasks_by_department.get("sandbox")
    sandbox_data = (sandbox_task.metadata.get("report") if sandbox_task else None) or {}
    sandbox_result = sandbox_data.get("result")
    sandbox_pass = sandbox_result is not None and _sandbox_verdict(sandbox_result) == "PASS"

    integration_task = tasks_by_department.get("integration")
    integration_data = (integration_task.metadata.get("report") if integration_task else None) or {}
    integration_plan = integration_data.get("plan")
    merge_ready = bool(integration_plan and integration_plan.merge_ready)

    risk_ok = mission.risk_level in ("LOW", "MEDIUM")

    # Sprint 21 düzeltmesi: CEO'nun genel kararı önceden YALNIZCA GitHub'ın
    # bulup Evaluation'ın değerlendirdiği adaylara bakıyordu -- AI
    # Discovery gerçek model/araç bulsa veya Research gerçek bir sonuç
    # üretse bile, GitHub tarafı ilgisiz çıkınca CEO hep düz "REDDET"
    # diyordu (bkz. Sprint 20 Beta Test raporu, madde 6). Yeni bir karar
    # sistemi YAZILMADI -- mevcut ÖNER/BEKLET/REDDET çerçevesi, zaten
    # hesaplanmış AI Discovery/Research sinyalleriyle GENİŞLETİLDİ.
    discovery_task = tasks_by_department.get("ai_discovery")
    discovery_data = (discovery_task.metadata.get("report") if discovery_task else None) or {}
    discovery_top = discovery_data.get("top") or []
    discovery_free_count = sum(1 for item in discovery_top if item.get("cost_advantage", 0) >= 90)
    discovery_found = len(discovery_top) > 0

    research_task = tasks_by_department.get("research")
    research_ok = research_task is not None and _task_note(research_task) is None

    other_signal_sources: list[str] = []
    if discovery_found:
        other_signal_sources.append(f"AI Discovery ({len(discovery_top)} aday, {discovery_free_count} ücretsiz)")
    if research_ok:
        other_signal_sources.append("Research")
    has_other_signal = bool(other_signal_sources)

    # Sprint 18: bu mission'ın Evaluation departmanı AI Validation
    # Pipeline (her aday için ÖNER/BEKLET/REDDET, bkz. yukarıdaki
    # Evaluation bölümü) çalıştırdıysa, CEO'nun genel önerisi bu GERÇEK
    # kararlardan türetilir; yoksa (candidates boşsa) Sprint 16'nın eski
    # tek-aday sandbox/integration mantığına düşülür (geriye dönük uyumluluk).
    if candidates:
        decision_counts = {"ÖNER": 0, "BEKLET": 0, "REDDET": 0}
        for candidate in candidates:
            decision, _ = _ceo_candidate_decision(
                candidate["evaluation"], candidate["sandbox_verdict"], candidate.get("integration_plan"),
            )
            decision_counts[decision] += 1

        if decision_counts["ÖNER"] > 0:
            recommendation = (
                f"ÖNER — {decision_counts['ÖNER']}/{len(candidates)} aday entegrasyona hazır "
                "(bkz. Evaluation tablosu)."
            )
        elif decision_counts["BEKLET"] > 0:
            recommendation = (
                f"BEKLET — {decision_counts['BEKLET']}/{len(candidates)} aday kısmen olumlu, "
                "insan gözden geçirmesi önerilir."
            )
        elif has_other_signal:
            recommendation = (
                f"BEKLET — GitHub tarafında uygun repo bulunamadı, ama {', '.join(other_signal_sources)} "
                "gerçek bulgular sundu (bkz. ilgili bölümler); insan gözden geçirmesi önerilir."
            )
        else:
            recommendation = f"REDDET — değerlendirilen {len(candidates)} adayın hiçbiri uygun bulunmadı."
    elif has_other_signal:
        recommendation = (
            f"BEKLET — {', '.join(other_signal_sources)} gerçek bulgular sundu; "
            "insan gözden geçirmesi önerilir."
        )
    elif merge_ready and sandbox_pass and risk_ok:
        recommendation = "ONAYLA — bulgular olumlu, entegrasyon planı merge'e hazır görünüyor."
    elif suitable_count > 0 or sandbox_pass:
        recommendation = "DİKKATLİ İLERLE — kısmen olumlu bulgular var, insan gözden geçirmesi önerilir."
    else:
        recommendation = "BEKLET — mevcut bulgular güçlü bir aday göstermiyor."

    completed = sum(1 for task in mission.tasks if task.status == TaskStatus.COMPLETED)
    total = len(mission.tasks)
    result_line = (
        f"{completed}/{total} departman gerçek sonuçla tamamlandı "
        f"(risk={mission.risk_level}, confidence=%{mission.confidence:.0f})."
    )

    if discovery_task is not None:
        result_line += (
            f" AI Discovery: {discovery_data.get('total_found', 0)} yeni aday "
            f"({discovery_free_count} ücretsiz/açık-kaynak sinyalli)."
        )

    if candidates:
        if decision_counts["ÖNER"] > 0:
            next_step = "ÖNER edilen adaylar için Evaluation tablosundaki gerekçeyi insan gözden geçirmesiyle doğrula."
        elif decision_counts["BEKLET"] > 0:
            next_step = "BEKLET edilen adayları insan gözden geçirmesiyle doğrula; hiçbiri otomatik uygulanmadı."
        elif has_other_signal:
            next_step = "AI Discovery/Research bölümlerindeki bulguları insan gözden geçirmesiyle değerlendir; GitHub tarafında uygun repo yok."
        else:
            next_step = "Değerlendirilen adayların hiçbiri uygun değil — farklı bir kategori/kaynak için mission'ı tekrar çalıştır."
    elif has_other_signal:
        next_step = "AI Discovery/Research bölümlerindeki gerçek bulguları insan gözden geçirmesiyle değerlendir."
    elif merge_ready:
        next_step = "İnsan gözden geçirmesiyle Integration bölümündeki entegrasyon sırasını uygula."
    elif sandbox_pass:
        next_step = "Sandbox bulgularını insan gözden geçirmesiyle doğrula, ardından entegrasyon planlamasına geç."
    else:
        next_step = "Mevcut sonuçlar yetersiz — farklı bir aday için mission'ı tekrar çalıştır veya kapsamı daralt."

    return "CEO\n" f"Öneri: {recommendation}\n" f"Sonuç: {result_line}\n" f"Sonraki adım: {next_step}"
