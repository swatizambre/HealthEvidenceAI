"""In-product AI help desk for doctors and PA coordinators.

Conversational answers are grounded in product FAQ + optional open-chart facts.
Never diagnoses, approves, or denies coverage. LLM phrases from provided contexts;
deterministic FAQ remains the fallback when no live model is available.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import LLMUnavailable
from app.core.safety import DISCLAIMER, contains_unsafe_decision_language
from app.schemas.api import HelpChatRequest, HelpChatResponse, HelpTopicOut

logger = logging.getLogger("healthevidence.help_desk")

HELP_TOPICS: tuple[HelpTopicOut, ...] = (
    HelpTopicOut(
        id="start",
        title="Where to start",
        prompt="I am new here — where should I start on this desk?",
    ),
    HelpTopicOut(
        id="workflow",
        title="Roles by facility (India)",
        prompt="How do PHC, CHC, district, and city hospital desks use this?",
    ),
    HelpTopicOut(
        id="reviews",
        title="Reviews / senior sign-off",
        prompt="When should a senior clinician use Reviews?",
    ),
    HelpTopicOut(
        id="essentials",
        title="Must-have chart items",
        prompt="What should be on the chart before I prepare an evidence pack?",
    ),
    HelpTopicOut(
        id="packet",
        title="Evidence pack & percent ready",
        prompt="What does percent ready and paperwork risk mean?",
    ),
    HelpTopicOut(
        id="gaps",
        title="Add missing notes",
        prompt="How do I add a missing item with a visit note?",
    ),
    HelpTopicOut(
        id="specialties",
        title="Departments",
        prompt="Which specialties or departments are supported?",
    ),
    HelpTopicOut(
        id="safety",
        title="Safety limits",
        prompt="Does this tool approve or deny insurance authorization?",
    ),
)

_ONBOARDING_REPLY = (
    "Welcome — here is the fastest path on this India cashless / TPA desk:\n"
    "1) Work queue — pick the most overdue case (IRDAI clocks).\n"
    "2) Open the case — fill checklist gaps, run Pre-auth form, answer TPA queries.\n"
    "3) Patients → open a chart → Must-have items → Prepare evidence pack when needed.\n"
    "4) Visit note — add missing clinical notes/labs under the right facility + department.\n"
    "5) Reviews — consultant / senior MO confirms citations (staff cannot final-sign).\n"
    "Set Facility + Demo sign-in role in Desk settings. "
    "This product organizes paperwork only — it does not diagnose or decide coverage."
)

# Explicit topic_id per FAQ — never rely on list index alignment.
_FAQ: tuple[tuple[str, tuple[str, ...], str, list[str]], ...] = (
    (
        "start",
        (
            "hi",
            "hello",
            "hey",
            "start",
            "begin",
            "platform",
            "new here",
            "first time",
            "getting started",
            "get started",
            "where to",
            "where should",
            "how to use",
            "onboard",
            "introduction",
            "welcome",
            "what do i do",
            "from where",
        ),
        _ONBOARDING_REPLY,
        ["/", "/patients", "/visit", "/reviews"],
    ),
    (
        "workflow",
        (
            "workflow",
            "prepare",
            "packet",
            "how do i",
            "steps",
            "end to end",
            "doctor",
            "senior",
            "junior",
            "staff",
            "role",
            "resident",
            "hospital",
            "clinic",
            "government",
            "facility",
            "phc",
            "chc",
            "district",
            "taluk",
            "rural",
            "ayushman",
            "cashless",
            "tpa",
            "referral",
            "pre-auth",
            "preauth",
            "work queue",
            "case workspace",
        ),
        (
            "India desks — rural referral ladder and city hospitals:\n"
            "PHC / sub-centre: MO or ANM documents the visit; "
            "prepare a thin pack before referral up.\n"
            "CHC / taluk / district: close gaps from lower facilities; "
            "clerks assemble cashless / TPA checklists.\n"
            "Urban multispecialty / medical college: records desk preps; "
            "PG/resident drafts; consultant uses Reviews.\n"
            "Records / TPA desk clerk:\n"
            "1) Work queue → open urgent case (or Patients → chart → Prepare evidence pack).\n"
            "2) Visit note with correct facility + department "
            "(Medicine, Ortho, Casualty…).\n"
            "3) Re-check pack / pre-auth form → hand to senior MO / consultant.\n"
            "Junior doctor / PG / MO (junior): same prep; "
            "cannot final-sign — ask consultant / senior MO.\n"
            "Consultant / senior MO: Reviews → confirm citations or send back.\n"
            "Set Facility in Desk settings (PHC → city hospital). Still documentation only — "
            "never approves, denies, or diagnoses."
        ),
        ["/", "/reviews", "/patients", "/visit"],
    ),
    (
        "essentials",
        ("essential", "completeness", "missing on chart", "allerg", "vital", "chart ready", "must-have"),
        (
            "Must-have chart items help every role see what is already on file:\n"
            "conditions, meds, labs, notes, imaging, procedures, plus allergy/vital hints.\n"
            "Missing or thin rows open Visit note or the matching chart section.\n"
            "Staff/residents then Prepare evidence pack; "
            "seniors use this list to see if the file is coherent.\n"
            "This is chart completeness for paperwork — not a clinical exam."
        ),
        ["/patients"],
    ),
    (
        "packet",
        (
            "readiness",
            "documentation risk",
            "doc risk",
            "prep minute",
            "next action",
            "scorecard",
            "percent ready",
            "evidence pack",
            "packet",
        ),
        (
            "Prepare evidence pack is the staff/resident prep step.\n"
            "Percent ready = how many checklist items already have chart support.\n"
            "Documentation risk flags an incomplete evidence pack before handoff — not a denial prediction.\n"
            "Minutes estimate how long the open items may take.\n"
            "Start here is the highest-impact missing item. Always re-check after a visit note.\n"
            "Prepare evidence pack never auto-signs the senior step in Reviews."
        ),
        ["/patients"],
    ),
    (
        "gaps",
        ("gap", "missing", "document", "visit note", "lab", "close", "encounter"),
        (
            "Add missing items from the evidence pack or case checklist → Visit note.\n"
            "The form prefills focus (labs/meds/diagnoses/note) and department when linked.\n"
            "Save, then re-check the pack / discharge check on the same case.\n"
            "Ask Help chat about this patient when a chart is open for chart-based coaching."
        ),
        ["/visit"],
    ),
    (
        "reviews",
        ("review", "citation", "acknowledge", "human", "clinician", "hitl", "senior", "resident"),
        (
            "Reviews is the clinician desk.\n"
            "Residents/staff may check the evidence; only senior clinicians (or admin) can "
            "confirm or mark needs more notes.\n"
            "Prepare evidence pack never auto-signs that step.\n"
            "Those actions organize the case only — never coverage decisions."
        ),
        ["/reviews"],
    ),
    (
        "specialties",
        ("specialty", "specialties", "cardiology", "oncology", "ortho", "gynecology", "department"),
        (
            "Hospital departments are supported across ~40 service lines "
            "(cardiology, ortho, oncology, OB/GYN, urology, surgery, and more).\n"
            "Tag department on Visit note; filter the chart file by specialty.\n"
            "Policies drive checklist content; departments organize the file."
        ),
        ["/visit"],
    ),
    (
        "safety",
        ("approve", "deny", "coverage", "diagnosis", "clinical use", "payer", "submit", "prescribe"),
        (
            "HealthEvidence AI does not approve, deny, diagnose, prescribe, or submit "
            "cashless / TPA / insurance authorization.\n"
            "It helps gather chart evidence for Indian PHC→district and city hospital desks: "
            "must-have items, open items, citations, and a summary for review.\n"
            "A licensed clinician / insurer remains responsible for care and coverage decisions.\n"
            f"{DISCLAIMER}"
        ),
        ["/"],
    ),
    (
        "workflow",
        ("today", "worklist", "needs attention", "pa desk", "clinician queue", "finding a case"),
        (
            "Work queue lists cashless cases for this facility, most urgent first "
            "(overdue IRDAI clocks, then least time left).\n"
            "Open a case to edit details, run checklist / pre-auth form, answer TPA queries, "
            "or send for senior review.\n"
            "Set Facility (PHC, CHC, district, city hospital…) + Role in Desk settings."
        ),
        ["/"],
    ),
    (
        "start",
        ("help", "chat", "assistant", "ai"),
        (
            "This Help chat is an AI desk guide. It answers how-to questions from product "
            "workflow knowledge and, when a patient chart is open, can summarize must-have "
            "chart items from stored records.\n"
            "It will not diagnose, prescribe, approve, or deny.\n"
            "Ask naturally — for example “where should I start?” or “how do I answer a TPA query?”."
        ),
        ["/"],
    ),
)


def list_help_topics() -> list[HelpTopicOut]:
    return list(HELP_TOPICS)


def answer_help(
    payload: HelpChatRequest,
    *,
    session: Session | None = None,
    settings: Settings | None = None,
) -> HelpChatResponse:
    question = (payload.message or "").strip()
    if len(question) < 2:
        return HelpChatResponse(
            reply=(
                "Ask anything about the desk — for example where to start, how to prepare "
                "a pre-auth, how to answer a TPA query, or what is still missing on a chart."
            ),
            matched_topic="start",
            suggested_links=["/", "/patients", "/visit", "/reviews"],
            context_used=[],
            disclaimer=DISCLAIMER,
        )

    if contains_unsafe_decision_language(question) or _looks_like_forbidden_clinical(question):
        topic_id, reply, links = _match_faq("approve deny diagnosis coverage")
        return HelpChatResponse(
            reply=reply
            or (
                "I can only help with evidence prep workflow — not diagnosis, prescribing, "
                f"or coverage decisions. {DISCLAIMER}"
            ),
            matched_topic=topic_id or "safety",
            suggested_links=links or ["/"],
            context_used=["safety"],
            disclaimer=DISCLAIMER,
        )

    topic_id, faq_reply, links = _match_faq(question)
    context_used: list[str] = []
    if topic_id:
        context_used.append(f"faq:{topic_id}")

    chart_block = ""
    if session is not None and payload.patient_id and _wants_chart_context(question):
        chart_block, chart_links = _chart_context_block(
            session, payload.patient_id, settings=settings
        )
        if chart_block:
            links = chart_links + [link for link in links if link not in chart_links]
            context_used.append("patient_essentials")
            topic_id = topic_id or "essentials"

    grounded = _compose_grounded(
        question=question,
        faq_reply=faq_reply,
        chart_block=chart_block,
        pathname=payload.pathname,
    )
    if not grounded.strip():
        grounded = _ONBOARDING_REPLY
        topic_id = topic_id or "start"
        links = links or ["/", "/patients", "/visit", "/reviews"]
        context_used.append("faq:start")

    history = _history_lines(list(payload.history or []))
    phrased, ai_source = _ai_compose_reply(
        question,
        grounded,
        history=history,
        settings=settings,
    )
    if ai_source:
        context_used.append(ai_source)
    if contains_unsafe_decision_language(phrased):
        phrased = grounded
        context_used.append("safety_fallback")

    links = _enrich_links(links or ["/", "/patients", "/visit", "/reviews"], payload)
    return HelpChatResponse(
        reply=phrased.strip(),
        matched_topic=topic_id,
        suggested_links=links[:6],
        context_used=context_used,
        disclaimer=DISCLAIMER,
    )


def _compose_grounded(
    *,
    question: str,
    faq_reply: str,
    chart_block: str,
    pathname: str | None,
) -> str:
    parts: list[str] = []
    if faq_reply:
        parts.append(faq_reply)
    elif _looks_like_greeting_or_start(question):
        parts.append(_ONBOARDING_REPLY)
    if chart_block:
        parts.append(chart_block)
    if pathname and pathname.startswith("/"):
        parts.append(f"User is currently on page: {pathname}")
    if not parts:
        # Still give the model / fallback a product map for free-form questions.
        parts.append(_ONBOARDING_REPLY)
        parts.append(_product_map_context())
    return "\n\n".join(parts)


def _product_map_context() -> str:
    return (
        "Product map: Work queue (/) = urgency-sorted cashless cases; "
        "Cases = full list; case workspace = checklist, pre-auth form, queries, discharge; "
        "Reviews = senior clinician sign-off; Patients = charts + evidence pack; "
        "Visit note = add documentation. Desk settings sets Facility + role."
    )


def _looks_like_greeting_or_start(question: str) -> bool:
    lower = question.lower()
    return any(
        token in lower
        for token in (
            "hi",
            "hello",
            "hey",
            "start",
            "begin",
            "platform",
            "where to",
            "getting started",
            "new here",
            "first time",
            "how to use",
        )
    )


def _enrich_links(links: list[str], payload: HelpChatRequest) -> list[str]:
    ordered: list[str] = []

    def _add(path: str) -> None:
        if path and path not in ordered:
            ordered.append(path)

    if payload.pathname and payload.pathname.startswith("/"):
        _add(payload.pathname)
    if payload.patient_id:
        params = []
        if payload.policy_id:
            params.append(f"policy={payload.policy_id}")
        if payload.case_id:
            params.append(f"case={payload.case_id}")
        chart = f"/patients/{payload.patient_id}"
        _add(chart)
        if params:
            _add(f"{chart}?prepare=1&{'&'.join(params)}")
        else:
            _add(f"{chart}?prepare=1")
        _add(f"/visit?patient={payload.patient_id}")
    if payload.case_id:
        _add(f"/cases/{payload.case_id}")
        _add(f"/reviews?case={payload.case_id}")
    for link in links:
        _add(link)
    return ordered


def _looks_like_forbidden_clinical(question: str) -> bool:
    lower = question.lower()
    return any(
        token in lower
        for token in (
            "diagnose",
            "what disease",
            "what cancer",
            "prescribe",
            "dosage",
            "should i operate",
            "is it malignant",
            "approve this",
            "deny this",
        )
    )


def _wants_chart_context(question: str) -> bool:
    lower = question.lower()
    return any(
        token in lower
        for token in (
            "this patient",
            "this chart",
            "essentials",
            "missing",
            "what do i still need",
            "completeness",
            "allerg",
            "labs",
            "medications",
            "summary",
            "brief",
            "ready for",
        )
    )


def _chart_context_block(
    session: Session,
    patient_id: str,
    *,
    settings: Settings | None,
) -> tuple[str, list[str]]:
    del settings
    try:
        from app.services.records import get_patient_essentials

        essentials = get_patient_essentials(session, patient_id)
    except Exception:
        return "", []

    lines = [
        f"Open chart grounding for {patient_id}:",
        essentials.doctor_brief,
        f"Structured essentials present: {essentials.completeness_percent}%",
        "Sections:",
    ]
    for section in essentials.sections:
        highlight = f" — {', '.join(section.highlights[:2])}" if section.highlights else ""
        lines.append(f"- {section.label}: {section.status} ({section.count}){highlight}")
        if section.note:
            lines.append(f"  note: {section.note}")
    if essentials.next_actions:
        lines.append("Suggested next actions:")
        for action in essentials.next_actions:
            lines.append(f"- {action}")
    lines.append(
        "Use Prepare evidence pack next for the payer checklist. "
        "This is chart completeness for evidence prep — not a clinical diagnosis."
    )
    return "\n".join(lines), [
        f"/patients/{patient_id}",
        f"/patients/{patient_id}?prepare=1",
        "/visit",
    ]


def _match_faq(question: str) -> tuple[str | None, str, list[str]]:
    lower = question.lower()
    best_score = 0
    best: tuple[str | None, str, list[str]] = (None, "", [])
    for topic_id, keywords, answer, links in _FAQ:
        score = sum(1 for key in keywords if key in lower)
        if score > best_score:
            best_score = score
            best = (topic_id, answer, list(links))
    if best_score == 0:
        return None, "", []
    return best


def _history_lines(history: list[Any]) -> list[str]:
    lines: list[str] = []
    for item in history[-6:]:
        if hasattr(item, "role") and hasattr(item, "content"):
            role = str(item.role or "").strip().lower()
            text = str(item.content or "").strip()
        elif isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            text = str(item.get("content") or item.get("text") or "").strip()
        else:
            continue
        if role not in {"user", "assistant"} or not text:
            continue
        lines.append(f"{role}: {text[:400]}")
    return lines


def _ai_compose_reply(
    question: str,
    grounded: str,
    *,
    history: list[str],
    settings: Settings | None,
) -> tuple[str, str | None]:
    """Ask a live LLM to answer conversationally from grounded product facts."""
    if settings is None:
        return grounded, None

    contexts = [grounded, _product_map_context()]
    if history:
        contexts.append("Recent chat:\n" + "\n".join(history))

    prompt = (
        "You are Desk Help for HealthEvidence AI — an India cashless / TPA paperwork desk.\n"
        "Write a friendly, clear chat reply (short paragraphs or numbered steps, max ~180 words).\n"
        "Answer the user's question using ONLY the grounded contexts below.\n"
        "If they are new or asking where to start, give a concrete first 3–5 steps with screen names.\n"
        "Do not invent features, APIs, or clinical advice.\n"
        "Do not diagnose, prescribe, approve, deny, or decide coverage.\n"
        "Do not say you are only a keyword FAQ; you are the desk assistant.\n"
        f"User question: {question}"
    )

    try:
        from app.agents.providers import build_llm

        for name in settings.llm_provider_chain():
            if name.strip().lower() == "local":
                # Local provider only echoes contexts — keep deterministic grounded text.
                continue
            try:
                provider = build_llm(settings, name)
                text = provider.complete_report(prompt, contexts).strip()
                if not text:
                    continue
                if contains_unsafe_decision_language(text):
                    logger.info("help_ai_rejected_unsafe provider=%s", name)
                    continue
                return text, f"ai:{getattr(provider, 'name', name)}"
            except (LLMUnavailable, ValueError) as exc:
                logger.debug("help_ai_provider_failed provider=%s err=%s", name, exc)
                continue
    except Exception as exc:  # noqa: BLE001 — never block help on model errors
        logger.warning("help_ai_unavailable err=%s", str(exc)[:160])
    return grounded, None
