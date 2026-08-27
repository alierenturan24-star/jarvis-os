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
KNOWN_TABLE_DEPARTMENTS = {"github", "evaluation", "sandbox", "integration", "ai_discovery", "research", "media"}


def build_ceo_report(mission: Mission) -> str:
    """Mission'ın gerçek department sonuçlarını CEO raporu olarak biçimlendirir.

    Sprint 33B: kanıt sırası -- Target repo -> GitHub metadata -> README
    özeti -> Research -> Evaluation -> Sandbox -> Integration -> CEO
    kararı (bkz. ``_ceo_section``). Yeni bir rapor motoru İCAT ETMEZ --
    yalnızca zaten hesaplanmış bölümlerin SIRASI ve README/Research için
    (Sprint 16'da "Diğer departmanlar" içine gömülü olan Research artık
    kendi bölümüne ayrılıyor) yeni birer bölüm eklenir.
    """

    tasks_by_department: dict[str, Task] = {task.agent: task for task in mission.tasks}

    sections = [
        _mission_section(mission),
        _ai_strategy_section(mission),
        _execution_plan_section(mission),
    ]

    # Sprint 17: "AI Discovery" bölümü, klasik Sprint 16 şablonunun
    # (GitHub/Evaluation/Sandbox/Integration) parçası DEĞİL -- yalnızca bu
    # departman mission'da GERÇEKTEN seçildiyse gösterilir (aksi halde her
    # mission'da alakasız bir "seçilmedi" notu gösterirdi).
    if "ai_discovery" in tasks_by_department:
        sections.append(_ai_discovery_section(tasks_by_department.get("ai_discovery")))

    sections.append(_github_section(tasks_by_department.get("github")))
    # Sprint 33B: README artık relevance puanına eriyip kaybolmuyor --
    # kısa, kontrollü bir özet olarak GitHub'ın hemen altında (aynı repo
    # target'ına bağlı) gösteriliyor.
    sections.append(_readme_section(tasks_by_department.get("github")))

    # Sprint 33B: Research, ai_discovery ile AYNI desenle (yalnızca
    # GERÇEKTEN seçildiyse) artık "Diğer departmanlar" içine gömülü
    # DEĞİL, CEO'nun kanıt sırasındaki (Target repo -> GitHub -> README
    # -> Research -> Evaluation -> ...) kendi yerinde gösteriliyor.
    if "research" in tasks_by_department:
        sections.append(_research_section(tasks_by_department.get("research")))

    # Sprint 39: Media (YouTube içerik/senaryo/sahne planı, bkz. src.media)
    # -- ai_discovery/research ile AYNI desen: yalnızca GERÇEKTEN
    # seçildiyse gösterilir, Research'ten hemen SONRA (kanıt zincirinde
    # doğal yeri -- önce araştırma, sonra o araştırmaya dayanan içerik
    # planı).
    if "media" in tasks_by_department:
        sections.append(_media_section(tasks_by_department.get("media")))

    sections.extend([
        _evaluation_section(tasks_by_department.get("evaluation")),
        _sandbox_section(tasks_by_department.get("sandbox")),
        _integration_section(tasks_by_department.get("integration")),
    ])

    other = _other_departments_section(tasks_by_department)
    if other:
        sections.append(other)

    sections.append(_ceo_section(mission, tasks_by_department))
    # Sprint 36 SELF CHECK: "her görev sonunda" -- kanıt zincirinin/CEO
    # kararının SONRASINDA, raporun EN SONUNDA gösterilir.
    sections.append(_self_check_section(mission))
    # Sprint 42 RECOVERY: self-check'in AÇIĞA ÇIKARDIĞI başarısızlıkların
    # (varsa) nasıl ele alındığı -- raporun EN SONUNDA, en son bilgi
    # olarak.
    sections.append(_recovery_section(mission))

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
        note = f"Tamamlanmadı (durum: {task.status.value}). Hata: {task.error or '-'}"
        # Mission repair (real Swiss-Insider-Shorts failure, ROOT CAUSE --
        # MEDIA 75S TIMEOUT): a flat "Görev zaman aşımına uğradı (75.0 sn)."
        # gave no evidence of WHICH internal stage was running. Departments
        # that track their own progress (currently: media, see
        # ``src.media.manager``/``src.media.production``) write a plain
        # ``task.metadata["last_stage"]`` marker as they go -- generic
        # (not media-specific) so any other multi-stage department can
        # adopt the same convention later.
        last_stage = (task.metadata or {}).get("last_stage")
        if last_stage:
            note += f" (son aşama: {last_stage})"
        return note
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


def _target_repo_label(mission: Mission) -> str:
    """Sprint 33B: CEO kanıt zincirinin 1. maddesi ("Target repo") --
    Mission oluşturulurken TEK kez çözümlenen ``mission.target``'ı
    (bkz. ``target_resolver.py``) okunabilir bir etikete çevirir. Yeni
    bir hedef çözümleme mekanizması İCAT ETMEZ."""

    target = mission.target
    if target is None:
        return "belirlenemedi"
    full_name = getattr(target, "full_name", None)
    if full_name:
        return full_name
    category_hint = getattr(target, "category_hint", None)
    if category_hint:
        return f"kategori: {category_hint}"
    text = getattr(target, "text", None)
    if text:
        return text
    return "belirlenemedi"


def _mission_section(mission: Mission) -> str:
    return (
        "MISSION\n"
        f"{mission.title}\n\n"
        f"Tür: {mission.mission_type.value.upper()}\n"
        f"Hedef repo: {_target_repo_label(mission)}\n"
        f"Risk: {mission.risk_level}\n"
        f"Confidence: %{mission.confidence:.0f}\n"
        f"Tahmini süre (Mission düzeyinde, kaba sezgisel tahmin): {mission.estimated_duration:.0f} dk"
    )


def _ai_strategy_section(mission: Mission) -> str:
    """Sprint 35: AI Strategy Engine'in (Sprint 34, bkz. ``src.strategy``)
    bu mission için Mission ÇALIŞMADAN ÖNCE ürettiği planı KISA bir CEO
    bölümü olarak gösterir -- yalnızca Sprint 35'in istediği 6 alan
    (kategori/provider/katman/department/tool/gerekçe); uzun debug bilgisi
    (ör. güven puanı, yedek sağlayıcı, tahmini maliyet) BASILMAZ."""

    header = "AI STRATEGY"
    strategy = mission.ai_strategy
    if strategy is None:
        return f"{header}\nPlan üretilemedi (veri yok)."

    department_names = ", ".join(choice.name for choice in strategy.departments) or "-"
    tool_names = ", ".join(tool.name for tool in strategy.tools) or "-"

    lines = [
        header,
        f"Görev kategorisi: {strategy.category.value}",
        f"Seçilen provider: {strategy.ai_choice.provider} ({strategy.ai_choice.model})",
        f"Maliyet katmanı: {strategy.ai_choice.tier}",
        f"Kullanılan department'lar: {department_names}",
        f"Kullanılan tool'lar: {tool_names}",
        f"Seçim gerekçesi: {strategy.ai_choice.reason}",
    ]

    # Sprint 40 (TASK-LEVEL ROUTING): mission özeti TEK bir provider
    # gösterse de, LLM çağıran her departman KENDİ kararını AYRI verir --
    # bkz. ``strategy.department_ai_choices`` (ZATEN hesaplanmış, burada
    # yalnızca gösterilir).
    if strategy.department_ai_choices:
        lines.append("")
        lines.append("Departman başına provider kararı:")
        for name, choice in strategy.department_ai_choices.items():
            lines.append(f"  - {name}: {choice.provider} ({choice.tier}) -- {choice.reason}")

    return "\n".join(lines)


def _execution_plan_section(mission: Mission) -> str:
    """Sprint 36 (AUTONOMOUS EXECUTION ENGINE): "Görev -> AI seçimi ->
    Tool seçimi -> Department zinciri -> Risk -> Maliyet" -- Execution
    Planner'ın (bkz. ``src.strategy.execution_planner``) ``ai_strategy``'den
    TÜRETTİĞİ, okunabilir yürütme zinciri. Gerçek dispatch sırasını
    DEĞİŞTİRMEZ (departmanlar hâlâ bağımsız/paralel çalışır) -- yalnızca
    CEO'nun "sonucu değil, bütün yürütme planını" görebilmesi içindir."""

    header = "EXECUTION PLAN"
    plan = mission.execution_plan
    if plan is None:
        return f"{header}\nPlan üretilemedi (veri yok)."

    lines = [header, "Department zinciri (anlatım sırası -- gerçek dispatch hâlâ bağımsız/paralel):"]
    for step in plan.steps:
        ai_part = f"AI: {step.ai_note}" if step.uses_ai else step.ai_note
        lines.append(f"  {step.order}. {step.label} | Tool: {step.tool} | {ai_part}")

    lines.append("")
    lines.append(f"Risk: {plan.risk_level}")
    lines.append(f"Maliyet: {plan.estimated_cost} -- {plan.cost_note}")

    return "\n".join(lines)


def _self_check_section(mission: Mission) -> str:
    """Sprint 36 SELF CHECK: her görev sonunda -- başarı oranı, eksik
    bilgi, tekrar araştırılması gereken yer, (Sprint 35'in ZATEN
    ürettiği) daha ucuz/hızlı/yeni-ücretsiz-model değerlendirmesi ve
    (LEARNING) bu araştırmanın önbellekten mi geldiği."""

    header = "SELF CHECK"
    check = mission.self_check
    if check is None:
        return f"{header}\nDeğerlendirme üretilemedi (veri yok)."

    lines = [
        header,
        f"Başarı oranı: %{check.success_rate:.0f}",
    ]

    if check.expected_outputs:
        lines.extend((
            "EXPECTED OUTPUT:",
            ", ".join(check.expected_outputs),
            "ARTIFACT STATUS:",
            ", ".join(check.artifact_statuses),
            "REMAINING:",
            ", ".join(check.remaining) if check.remaining else "hiçbir şey",
        ))

    if check.missing_info:
        lines.append("Eksik bilgi:")
        lines.extend(f"  - {item}" for item in check.missing_info)
    else:
        lines.append("Eksik bilgi: yok")

    if check.needs_reresearch:
        lines.append("Tekrar araştırılması gereken yer:")
        lines.extend(f"  - {item}" for item in check.needs_reresearch)
    else:
        lines.append("Tekrar araştırılması gereken yer: yok")

    lines.append(f"Learning: {check.cache_note}")

    review = check.review
    if review is not None:
        lines.append(f"Daha ucuz seçenek var mıydı: {'evet' if review.cheaper_ai_possible else 'hayır'} -- {review.cheaper_ai_note}")
        lines.append(f"Daha hızlı seçenek olabilir miydi: {'evet' if review.faster_ai_possible else 'hayır'} -- {review.faster_ai_note}")
        lines.append(f"Yeni ücretsiz AI bulundu mu: {'evet' if review.new_free_model_available else 'hayır'} -- {review.new_free_model_note}")
    else:
        lines.append("Daha ucuz/hızlı seçenek/yeni ücretsiz AI: veri yok (AI Strategy review üretilemedi).")

    return "\n".join(lines)


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


def _readme_section(task: Optional[Task]) -> str:
    """Sprint 33B: README artık ``_readme_bonus``'a eriyip kaybolmuyor --
    ``GitHubDepartmentAgent``'ın ürettiği kısa, kontrollü özeti (bkz.
    ``department_adapters.summarize_readme``) CEO'ya AYRI, okunabilir bir
    kanıt olarak gösterir. Aynı repo target'ına bağlıdır (``evidence_repo``
    -- bkz. ``DepartmentOrchestrator._resolve_evidence_repo``)."""

    header = "README"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    data = task.metadata.get("report") or {}
    summary = data.get("readme_summary")
    evidence_repo = data.get("evidence_repo")

    if summary is None:
        if evidence_repo:
            return f"{header}\nRepo: {evidence_repo}\nREADME alınamadı, boş veya çözümlenemedi (veri yok)."
        return (
            f"{header}\nBu mission somut bir repo değerlendirme/seçme zinciri "
            "çalıştırmadığı için README çekilmedi (veri yok)."
        )

    lines = [header, f"Repo: {evidence_repo or '-'}", "", f"Amaç: {summary['purpose']}"]

    if summary["features"]:
        lines.append("Temel özellikler:")
        lines.extend(f"  - {feature}" for feature in summary["features"])
    else:
        lines.append("Temel özellikler: README'de açık bir madde işaretli liste bulunamadı.")

    setup_text = ", ".join(summary["setup_signals"]) if summary["setup_signals"] else "belirgin bir sinyal yok"
    lines.append(f"Kurulum/bağımlılık sinyalleri: {setup_text}")

    security_text = (
        ", ".join(summary["security_notes"]) if summary["security_notes"] else "belirgin bir güvenlik notu yok"
    )
    lines.append(f"Güvenlik açısından önemli noktalar: {security_text}")

    return "\n".join(lines)


def _research_section(task: Optional[Task]) -> str:
    """Sprint 33B: Research artık "Diğer departmanlar" içine gömülü
    DEĞİL -- CEO kanıt sırasındaki kendi yerinde (GitHub/README'den
    sonra, Evaluation'dan önce) ayrı bir bölüm olarak gösterilir. Yeni
    bir araştırma motoru İCAT ETMEZ -- ``ResearchAgent``'ın (zaten var
    olan) ``task.result.output``'unu okur."""

    header = "Research"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    output = task.result.output if task.result else ""
    # Mission repair (real Swiss-Insider-Shorts follow-up evidence, item 3/4):
    # this is RAW LLM research prose -- a real run's research text called a
    # tool "free"/"accessible"/"suitable" without that ever being checked
    # against an actual capability adapter/health-check. That claim was
    # never itself capable of promoting anything to an operational
    # capability (research output never reaches src.capabilities.resolution
    # or mission.completion's evidence checks -- see
    # test_swiss_insider_mission_repair.py's
    # TestResearchClaimsCannotSelfPromoteToCapability) -- but the report
    # text alone could still read as an operational recommendation to a
    # human. This disclaimer makes that boundary explicit at the point of
    # display, without changing what research actually produces.
    disclaimer = (
        "(Bu, DOĞRULANMAMIŞ ham araştırma metnidir -- burada adı geçen bir araç/site/sağlayıcı "
        "hakkındaki \"ücretsiz\"/\"erişilebilir\"/\"uygun\" gibi iddialar KENDİ BAŞINA hiçbir "
        "capability/provider'ı operasyonel yapmaz. Yalnızca Evaluation -> Sandbox -> Integration "
        "-> onay zincirinden geçmiş adaylar, ya da GERÇEKTEN çalıştırılıp doğrulanmış bir handler, "
        "kullanılabilir kabul edilir.)"
    )
    return f"{header}\n{output}\n\n{disclaimer}"


def _media_section(task: Optional[Task]) -> str:
    """Sprint 39: ``MediaManager``'ın (zaten var olan) çıktısını -- senaryo/
    sahne/seslendirme-planı/görsel-planı/altyazı/thumbnail/başlık/açıklama/
    etiket -- ayrı bir bölüm olarak gösterir. Yeni bir üretim motoru İCAT
    ETMEZ -- ``task.result.output``'u (``ResearchAgent``/``_research_section``
    ile AYNI desen) AYNEN okur."""

    header = "Media"
    note = _task_note(task)
    if note:
        return f"{header}\n{note}"

    output = task.result.output if task.result else ""
    return f"{header}\n{output}"


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


def _veri_var_mi(value: bool, detail: str = "") -> str:
    """Sprint 33B: bir departmanın kanıtı YOKSA bunu açıkça "veri yok"
    olarak belirtir (bkz. Sprint 33B kabul kriteri) -- sessizce
    atlanmaz/varmış gibi davranılmaz."""

    if not value:
        return "veri yok"
    return detail or "var"


def _ceo_section(mission: Mission, tasks_by_department: dict[str, Task]) -> str:
    """CEO'nun departman sonuçlarından ürettiği nihai karar.

    Sprint 33B: CEO artık yalnızca Evaluation.candidates'a değil, AYNI
    hedef repo için toplanmış TÜM kanıta (Target repo -> GitHub metadata
    -> README özeti -> Research -> Evaluation -> Sandbox -> Integration)
    bakar; eksik bir departmanın verisi açıkça "veri yok" olarak
    işaretlenir (başka bir repodan veri KULLANILMAZ). Nihai karar
    yalnızca üç değerden biridir: ONAYLA / İNSAN İNCELEMESİ / REDDET.
    Yeni bir puanlama/analiz İCAT ETMEZ -- yalnızca zaten hesaplanmış
    alanlara (Evaluation'ın candidate kararları -- bkz.
    ``_ceo_candidate_decision``, Sandbox PASS/FAIL, Integration
    merge_ready, GitHub'ın bulduğu somut adaylar) dayalı basit,
    deterministik bir karar ağacıdır.
    """

    target_label = _target_repo_label(mission)

    github_task = tasks_by_department.get("github")
    github_data = (github_task.metadata.get("report") if github_task else None) or {}
    github_top = github_data.get("top") or []
    github_ok = github_task is not None and _task_note(github_task) is None and bool(github_top)

    readme_summary = github_data.get("readme_summary")
    readme_ok = readme_summary is not None

    research_task = tasks_by_department.get("research")
    research_ok = research_task is not None and _task_note(research_task) is None

    eval_task = tasks_by_department.get("evaluation")
    eval_data = (eval_task.metadata.get("report") if eval_task else None) or {}
    candidates = eval_data.get("candidates") or []
    evaluation_ok = bool(candidates)

    sandbox_task = tasks_by_department.get("sandbox")
    sandbox_data = (sandbox_task.metadata.get("report") if sandbox_task else None) or {}
    sandbox_result = sandbox_data.get("result")
    sandbox_ok = sandbox_result is not None
    sandbox_pass = sandbox_ok and _sandbox_verdict(sandbox_result) == "PASS"

    integration_task = tasks_by_department.get("integration")
    integration_data = (integration_task.metadata.get("report") if integration_task else None) or {}
    integration_plan = integration_data.get("plan")
    integration_ok = integration_plan is not None
    merge_ready = bool(integration_plan and integration_plan.merge_ready)

    evidence_lines = [
        f"Target repo: {target_label}",
        f"GitHub: {_veri_var_mi(github_ok, f'{len(github_top)} aday bulundu')}",
        "README özeti: "
        + _veri_var_mi(readme_ok, (readme_summary or {}).get("purpose", "")[:80] if readme_ok else ""),
        f"Research: {_veri_var_mi(research_ok)}",
        f"Evaluation: {_veri_var_mi(evaluation_ok, f'{len(candidates)} aday değerlendirildi')}",
        f"Sandbox: {_veri_var_mi(sandbox_ok, _sandbox_verdict(sandbox_result) if sandbox_ok else '')}",
        "Integration: "
        + _veri_var_mi(integration_ok, "merge'e hazır" if merge_ready else "merge'e hazır değil"),
    ]

    # Sprint 18: bu mission'ın Evaluation departmanı AI Validation
    # Pipeline (her aday için ÖNER/BEKLET/REDDET, bkz. yukarıdaki
    # Evaluation bölümü) çalıştırdıysa, CEO'nun nihai kararı bu GERÇEK
    # kararlardan türetilir (candidate-level karar mantığı DEĞİŞTİRİLMEDİ,
    # bkz. ``_ceo_candidate_decision``).
    decision_counts = {"ÖNER": 0, "BEKLET": 0, "REDDET": 0}
    for candidate in candidates:
        decision, _ = _ceo_candidate_decision(
            candidate["evaluation"], candidate["sandbox_verdict"], candidate.get("integration_plan"),
        )
        decision_counts[decision] += 1

    if candidates:
        primary_repo = candidates[0]["repo"].full_name
        if decision_counts["ÖNER"] > 0:
            final_decision = "ONAYLA"
            reason = f"{primary_repo}: Evaluation/Sandbox/Integration üçü de olumlu (bkz. Evaluation tablosu)."
        elif decision_counts["REDDET"] == len(candidates):
            final_decision = "REDDET"
            reason = f"{primary_repo}: değerlendirilen {len(candidates)} adayın hiçbiri uygun bulunmadı."
        else:
            final_decision = "İNSAN İNCELEMESİ"
            reason = f"{primary_repo}: kısmen olumlu bulgular var, insan gözden geçirmesi gerekiyor."
    elif github_ok:
        # Sprint 33B düzeltmesi (KANITLANMIŞ SORUN #3): Evaluation
        # çalışmadıysa CEO artık GitHub'ın bulduğu somut adayı SESSİZCE
        # yok saymıyor -- gerekçede ADIYLA anılır, ama Evaluation/Sandbox/
        # Integration kanıtı olmadan asla ONAYLA verilmez.
        primary_repo = github_top[0]["repo"].full_name
        final_decision = "İNSAN İNCELEMESİ"
        reason = (
            f"{primary_repo}: GitHub gerçek bir aday buldu ama Evaluation/Sandbox/Integration "
            "veri yok -- risksiz onay için yeterli kanıt yok."
        )
    else:
        final_decision = "REDDET"
        reason = "Hiçbir departman somut bir repo adayı üretmedi (veri yok)."

    completed = sum(1 for task in mission.tasks if task.status == TaskStatus.COMPLETED)
    total = len(mission.tasks)
    result_line = (
        f"{completed}/{total} departman gerçek sonuçla tamamlandı "
        f"(risk={mission.risk_level}, confidence=%{mission.confidence:.0f})."
    )

    discovery_task = tasks_by_department.get("ai_discovery")
    if discovery_task is not None:
        discovery_data = discovery_task.metadata.get("report") or {}
        discovery_top = discovery_data.get("top") or []
        discovery_free_count = sum(1 for item in discovery_top if item.get("cost_advantage", 0) >= 90)
        result_line += (
            f" AI Discovery: {discovery_data.get('total_found', 0)} yeni aday "
            f"({discovery_free_count} ücretsiz/açık-kaynak sinyalli)."
        )

    if final_decision == "ONAYLA":
        next_step = "İnsan onayıyla Integration bölümündeki entegrasyon sırasını uygula."
    elif final_decision == "İNSAN İNCELEMESİ":
        next_step = (
            "Yukarıdaki kanıt zincirini (GitHub/README/Research/Evaluation/Sandbox/Integration) "
            "insan gözden geçirmesiyle doğrula."
        )
    else:
        next_step = "Mevcut kanıtlar yetersiz — farklı bir aday/kategori için mission'ı tekrar çalıştır."

    lines = ["CEO", "", "Kanıt zinciri:"]
    lines.extend(f"  {index}. {line}" for index, line in enumerate(evidence_lines, start=1))
    lines.append("")
    lines.append(f"Öneri: {final_decision} — {reason}")
    lines.append(f"Sonuç: {result_line}")
    lines.append(f"Sonraki adım: {next_step}")
    return "\n".join(lines)


_RECOVERY_MARKER_LABELS = {
    "__same_method_retry__": "aynı yöntem",
    "__ladder_exhausted__": "-",
}


def _recovery_section(mission: Mission) -> str:
    """Sprint 42 (AUTONOMOUS GOAL EXECUTION -- "provider'ı değil hedefi
    koru"): bir görev BAŞARISIZ olduğunda JARVIS'in kendi kendine sorması
    gereken 5 soruya (ORİJİNAL HEDEF NE? / ŞU ANA KADAR NE TAMAMLANDI? /
    NE KALDI? / NEYİN BAŞARISIZ OLMASI BENİ DURDURDU? / AYNI HEDEFE BAŞKA
    NASIL ULAŞABİLİRİM?) verdiği GERÇEK cevapları gösterir. Yeni bir
    değerlendirme İCAT ETMEZ -- yalnızca ZATEN hesaplanmış
    ``mission.recovery``'yi (bkz. ``src.mission.recovery.recover_mission``)
    okur."""

    header = "RECOVERY (HEDEF KORUMA)"
    recovery = mission.recovery

    if recovery is None or not recovery.ran:
        return f"{header}\nBu mission'da hiç başarısız görev olmadı -- kurtarma hiç tetiklenmedi."

    completed_titles = [task.title for task in mission.tasks if task.status == TaskStatus.COMPLETED]
    still_failed_titles = [
        task.title for task in mission.tasks if task.id in recovery.still_failed_task_ids
    ]
    remaining_items = still_failed_titles + list(getattr(recovery, "remaining_goals", ()))
    failure_reasons = sorted({attempt.failure_class.value for attempt in recovery.attempts})
    alt_methods = sorted({
        attempt.provider_tried for attempt in recovery.attempts
        if attempt.provider_tried and not attempt.provider_tried.startswith("__")
    })

    lines = [
        header, "",
        f"ORİJİNAL HEDEF NE? {recovery.goal or mission.title}",
        "ŞU ANA KADAR NE TAMAMLANDI? " + (", ".join(completed_titles) if completed_titles else "hiçbiri"),
        "NE KALDI? " + (", ".join(remaining_items) if remaining_items else "hiçbir şey (tümü kurtarıldı)"),
        "NEYİN BAŞARISIZ OLMASI BENİ DURDURDU? " + (", ".join(failure_reasons) if failure_reasons else "bilinmiyor"),
        "AYNI HEDEFE BAŞKA NASIL ULAŞABİLİRİM? " + (
            f"denenen alternatifler: {', '.join(alt_methods)}" if alt_methods
            else "ücretsiz/yerel bir alternatif bulunamadı"
        ),
        "", "Kurtarma denemeleri:",
    ]

    for attempt in recovery.attempts:
        provider = _RECOVERY_MARKER_LABELS.get(attempt.provider_tried or "", attempt.provider_tried or "-")
        status = "başarılı" if attempt.succeeded else "başarısız"
        lines.append(f"  - [{attempt.department}] {attempt.step.value} ({provider}): {status} -- {attempt.note}")

    if recovery.resolved_task_ids:
        lines.append("")
        lines.append(f"Kurtarılan görev sayısı: {len(recovery.resolved_task_ids)}")
    if recovery.resumed_task_ids:
        lines.append(
            f"Kurtarma sonrası devam eden (checkpoint/resume) görev sayısı: {len(recovery.resumed_task_ids)}"
        )

    if recovery.discovery_runs:
        lines.append("")
        lines.append("Hedefe özgü kaynak keşfi (goal-driven discovery):")
        for run in recovery.discovery_runs:
            if run.ran:
                lines.append(f'  - [{run.department}] odak: "{run.focus}" -> {len(run.candidates)} aday bulundu.')
            else:
                lines.append(f"  - [{run.department}] çalışmadı: {run.reason}")

    if recovery.evaluated_candidates or recovery.sandboxed_candidates or recovery.integrated_candidates or recovery.used_candidates:
        lines.extend([
            "",
            "Capability continuation:",
            f"  - EVALUATION: {len(recovery.evaluated_candidates)} aday",
            f"  - SANDBOX: {len(recovery.sandboxed_candidates)} aday",
            f"  - SAFE INTEGRATION: {len(recovery.integrated_candidates)} aday",
            f"  - SAFE USE / ORIGINAL GOAL RESUME: {len(recovery.used_candidates)} aday",
        ])

    # Mission repair (ROOT CAUSE C): the counts above alone cannot explain
    # why a candidate count SHRANK between stages (real Swiss-Insider-Shorts
    # failure: "3 candidates found -> Evaluation 1 -> Sandbox 0 -> ... 0",
    # with no evidence for the other 2). Every discovered candidate keeps an
    # explicit terminal status (see ``src.mission.recovery`` CANDIDATE_*
    # constants) -- list every one, not just the ones that survived.
    if mission.capability_candidates:
        lines.append("")
        lines.append("Capability candidate evidence (her aday, düşürülmeden):")
        for candidate in mission.capability_candidates:
            label = str(
                candidate.get("title") or candidate.get("url")
                or candidate.get("repository_url") or "(bilinmeyen aday)"
            )
            status = str(candidate.get("status") or "DISCOVERED")
            reason = candidate.get("status_reason")
            line = f"  - {label}: {status}"
            if reason:
                line += f" -- {reason}"
            lines.append(line)

    if recovery.approval_required:
        lines.append("")
        lines.append("KULLANICI ONAYI GEREKİYOR:")
        for item in recovery.approval_required:
            lines.append(f"  - [{item['department']}] NEYE İHTİYAÇ VAR: {item['need']}")
            lines.append(f"    NEDEN: {item['why']}")
            lines.append(f"    ÜCRETSİZ ALTERNATİFLER NEDEN YETMEDİ: {item['why_free_insufficient']}")

    return "\n".join(lines)
