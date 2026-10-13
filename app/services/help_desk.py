"""In-product AI help desk for doctors and PA coordinators.

Workflow guidance + optional chart-grounded answers. Never diagnoses, approves,
or denies coverage. FAQ first; LLM only phrases or answers from provided contexts.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.safety import DISCLAIMER, contains_unsafe_decision_language
from app.schemas.api import HelpChatRequest, HelpChatResponse, HelpTopicOut

HELP_TOPICS: tuple[HelpTopicOut, ...] = (
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

# Explicit topic_id per FAQ — never rely on list index alignment.
_FAQ: tuple[tuple[str, tuple[str, ...], str, list[str]], ...] = (
    (
        "workflow",
        (
            "workflow",
            "prepare",
            "packet",
            "how do i",
            "get started",
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
            "1) Patients → chart → Must-have items → Prepare evidence pack.\n"
            "2) Visit note with correct facility + department "
            "(Medicine, Ortho, Casualty…).\n"
            "3) Re-check pack → hand to senior MO / consultant.\n"
            "Junior doctor / PG / MO (junior): same prep; "
            "cannot final-sign — ask consultant / senior MO.\n"
            "Consultant / senior MO: Today → Needs clinician review / Reviews → "
            "confirm citations or send back.\n"
            "Set Facility in the top bar (PHC → city hospital). Still documentation only — "
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
            "Add missing items from the evidence pack or Today → Notes still needed → Add note.\n"
            "The form prefills focus (labs/meds/diagnoses/note) and department when linked.\n"
            "Save, then Re-check evidence pack on the same case.\n"
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
        ("today", "worklist", "needs attention", "pa desk", "clinician queue"),
        (
            "Today is one facility desk — lanes reorder by role:\n"
            "• Consultant / senior MO / admin — Needs your review first, then notes\n"
            "• Records / TPA clerk — Notes still needed + waiting to prepare first\n"
            "• Junior doctor / PG — Review + prep (senior still final-signs)\n"
            "Same facility queue until assignment exists (then “My patients / my queue”).\n"
            "Set Facility (PHC, CHC, district, city hospital…) + Role in the top bar."
        ),
        ["/"],
    ),
    (
        "workflow",
        ("help", "chat", "assistant", "ai"),
        (
            "This Help chat answers how-to questions and, when a patient chart is open, "
            "can summarize must-have chart items from stored records.\n"
            "It will not diagnose, prescribe, approve, or deny.\n"
            "Use topic chips for staff, resident, or senior questions."
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
                "Ask how to run end-to-end prep, what chart essentials are missing, "
                "how to close gaps, or what this tool never does."
            ),
            matched_topic=None,
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

    topic_id, reply, links = _match_faq(question)
    context_used: list[str] = []
    if topic_id:
        context_used.append(f"faq:{topic_id}")

    chart_reply = None
    if session is not None and payload.patient_id and _wants_chart_context(question):
        chart_reply, chart_links = _chart_grounded_answer(
            session, payload.patient_id, question, settings=settings
        )
        if chart_reply:
            reply = chart_reply if not reply else f"{chart_reply}\n\n---\nWorkflow tip:\n{reply}"
            links = chart_links + [link for link in links if link not in chart_links]
            context_used.append("patient_essentials")
            topic_id = topic_id or "essentials"

    if topic_id is None and chart_reply is None:
        reply = (
            "I help with product workflow and chart essentials (not clinical advice).\n"
            "Try: end-to-end prep, missing essentials, close gaps, Reviews, specialties, "
            "or whether this tool approves care."
        )
        links = ["/", "/patients", "/visit", "/reviews"]

    grounded = reply
    phrased = _maybe_phrase(question, grounded, settings=settings)
    if contains_unsafe_decision_language(phrased):
        phrased = grounded
        context_used.append("safety_fallback")

    links = _enrich_links(links, payload)
    return HelpChatResponse(
        reply=phrased,
        matched_topic=topic_id,
        suggested_links=links[:6],
        context_used=context_used,
        disclaimer=DISCLAIMER,
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


def _chart_grounded_answer(
    session: Session,
    patient_id: str,
    question: str,
    *,
    settings: Settings | None,
) -> tuple[str | None, list[str]]:
    try:
        from app.services.records import get_patient_essentials

        essentials = get_patient_essentials(session, patient_id)
    except Exception:
        return None, []

    lines = [
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
    grounded = "\n".join(lines)
    phrased = _maybe_phrase(question, grounded, settings=settings)
    if contains_unsafe_decision_language(phrased):
        phrased = grounded
    return phrased, [f"/patients/{patient_id}", f"/patients/{patient_id}?prepare=1", "/visit"]


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


def _maybe_phrase(question: str, answer: str, *, settings: Settings | None) -> str:
    if settings is None:
        return answer
    try:
        from app.agents.providers import build_llm

        llm = build_llm(settings)
        if getattr(llm, "name", "") in {"local", ""}:
            return answer
        prompt = (
            "You are HealthEvidence AI help for doctors and PA coordinators. "
            "Rephrase the grounded answer clearly and briefly. "
            "Do not add clinical advice, diagnoses, prescriptions, approvals, or denials. "
            "Do not invent features. Keep the same facts.\n"
            f"User question: {question}\n"
            f"Grounded answer:\n{answer}"
        )
        text = llm.complete_report(prompt, [answer]).strip()
        return text or answer
    except Exception:
        return answer
