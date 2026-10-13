import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import {
  getDocument,
  getPatient,
  getLifelongSummary,
  getPatientEssentials,
  getPatientTimeline,
  getPolicies,
  preparePacket,
  type EvidencePacket,
  type LifelongSummary,
  type PatientDetail,
  type PatientEssentials,
  type PolicySummary,
  type TimelineEvent,
} from "../api";
import {
  conditionLabel,
  criterionStatusClass,
  criterionStatusLabel,
  documentationRiskClass,
  essentialsStatusLabel,
  noteTypeLabel,
  policyOptionLabel,
} from "../labels";
import { AgentTrace } from "../components/AgentTrace";
import { printEvidencePacket } from "../printSheet";
import { pushRecentPatient } from "../recentPatients";
import { useRole } from "../roleContext";

type ChartTab = "file" | "notes" | "labs" | "meds" | "imaging" | "procedures";

const TYPE_LABELS: Record<string, string> = {
  clinical_note: "Note",
  lab_result: "Lab",
  medication: "Medication",
  procedure: "Procedure",
  imaging_study: "Imaging",
  claim: "Claim",
};

function formatWhen(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function visitGapHref(
  patientId: string,
  gap: { label: string; focus: string; specialty_hint?: string; draft_suggestion?: string },
): string {
  const params = new URLSearchParams({
    patient: patientId,
    focus: gap.focus,
    gap: gap.label,
  });
  if (gap.specialty_hint) {
    params.set("specialty", gap.specialty_hint);
  }
  if (gap.draft_suggestion) {
    params.set("draft", gap.draft_suggestion.slice(0, 800));
  }
  return `/visit?${params.toString()}`;
}

function essentialsVisitHref(
  patientId: string,
  section: { key: string; label: string; action: string },
): string {
  const focus =
    section.key === "labs"
      ? "labs"
      : section.key === "medications"
        ? "meds"
        : section.key === "conditions"
          ? "diagnoses"
          : "note";
  const specialty =
    focus === "labs" ? "Laboratory" : focus === "meds" ? "Pharmacy" : "General medicine";
  return visitGapHref(patientId, {
    label: section.action || section.label,
    focus,
    specialty_hint: specialty,
  });
}


function ageYears(dob: string): number | null {
  const born = new Date(dob);
  if (Number.isNaN(born.getTime())) {
    return null;
  }
  const today = new Date();
  let age = today.getFullYear() - born.getFullYear();
  const m = today.getMonth() - born.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < born.getDate())) {
    age -= 1;
  }
  return age >= 0 ? age : null;
}

export function PatientDetailPage() {
  const { patientId = "" } = useParams();
  const {
    canPrepare,
    canDocument,
    canAdjudicate,
    isPatient,
    myPatientId,
    setMyPatientId,
    label: roleLabel,
    facilityLabel,
  } = useRole();
  const [searchParams, setSearchParams] = useSearchParams();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [policyId, setPolicyId] = useState("POL-000001");
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [essentials, setEssentials] = useState<PatientEssentials | null>(null);
  const [lifelong, setLifelong] = useState<LifelongSummary | null>(null);
  const [prepBusy, setPrepBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [specialtyFilter, setSpecialtyFilter] = useState("all");
  const [lifelongDisorder, setLifelongDisorder] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [source, setSource] = useState("");
  const [sourceBusy, setSourceBusy] = useState(false);

  if (isPatient && patientId && patientId.toUpperCase() !== myPatientId) {
    return <Navigate to={`/patients/${myPatientId}`} replace />;
  }

  const tabParam = searchParams.get("tab");
  const autoPrepare = searchParams.get("prepare") === "1";
  const policyParam = searchParams.get("policy") || "";
  const caseParam = searchParams.get("case") || "";
  const tab: ChartTab =
    tabParam === "labs" ||
    tabParam === "meds" ||
    tabParam === "imaging" ||
    tabParam === "notes" ||
    tabParam === "procedures" ||
    tabParam === "file"
      ? tabParam
      : "file";

  useEffect(() => {
    setPatient(null);
    setTimeline([]);
    setPacket(null);
    setEssentials(null);
    setLifelong(null);
    setError("");
    setSpecialtyFilter("all");
    setLifelongDisorder("all");
    setExpandedId(null);
    setSource("");
    Promise.all([
      getPatient(patientId),
      getPatientTimeline(patientId),
      getPolicies(),
      getPatientEssentials(patientId),
      getLifelongSummary(patientId),
    ])
      .then(([body, feed, policyBody, essentialsBody, lifelongBody]) => {
        setPatient(body);
        setTimeline(feed.events);
        setPolicies(policyBody.policies);
        setEssentials(essentialsBody);
        setLifelong(lifelongBody);
        const preferred =
          policyBody.policies.find((item) => item.policy_id === policyParam) ??
          policyBody.policies.find((item) => item.policy_id === "POL-000001") ??
          policyBody.policies[0];
        if (preferred) {
          setPolicyId(preferred.policy_id);
        }
        pushRecentPatient({
          patient_id: body.patient_id,
          display_name: body.demographics.synthetic_name,
        });
      })
      .catch((err: Error) => setError(err.message));
  }, [patientId, policyParam]);

  useEffect(() => {
    if (!autoPrepare || !patient || !policyId || prepBusy || packet) {
      return;
    }
    void runPrepare();
    // Auto-run once when deep-linked with ?prepare=1
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPrepare, patient, policyId]);

  const specialties = useMemo(() => {
    const values = new Set<string>();
    for (const event of timeline) {
      if (event.specialty) {
        values.add(event.specialty);
      }
    }
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }, [timeline]);

  const visibleEvents = useMemo(() => {
    if (specialtyFilter === "all") {
      return timeline;
    }
    return timeline.filter((event) => event.specialty === specialtyFilter);
  }, [timeline, specialtyFilter]);

  const lifelongDisorders = useMemo(() => {
    if (!lifelong) {
      return [];
    }
    if (lifelong.disorders?.length) {
      return lifelong.disorders;
    }
    if (lifelong.by_disorder?.length) {
      return lifelong.by_disorder.map((group) => group.key);
    }
    return [];
  }, [lifelong]);

  const lifelongVisible = useMemo(() => {
    if (!lifelong) {
      return [];
    }
    if (lifelongDisorder === "all") {
      return lifelong.events.slice(0, 8);
    }
    return lifelong.events
      .filter((event) => (event.disorders ?? []).includes(lifelongDisorder))
      .slice(0, 8);
  }, [lifelong, lifelongDisorder]);

  const selectedPolicy = policies.find((item) => item.policy_id === policyId) ?? null;

  function setTab(next: ChartTab) {
    const params = new URLSearchParams(searchParams);
    if (next === "file") {
      params.delete("tab");
    } else {
      params.set("tab", next);
    }
    setSearchParams(params);
  }

  async function runPrepare() {
    if (!patient || !policyId) {
      return;
    }
    setPrepBusy(true);
    setError("");
    setCopied(false);
    try {
      const body = await preparePacket({
        patient_id: patient.patient_id,
        policy_id: policyId,
        procedure: selectedPolicy?.procedure,
        case_id: caseParam || undefined,
      });
      setPacket(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prepare evidence pack");
    } finally {
      setPrepBusy(false);
    }
  }

  async function copyPacket() {
    if (!packet) {
      return;
    }
    try {
      await navigator.clipboard.writeText(packet.packet_summary);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Clipboard copy failed — select the summary text manually.");
    }
  }

  function runPrintPacket() {
    if (!packet || !patient) {
      return;
    }
    printEvidencePacket({
      facilityLabel,
      doctorName: roleLabel,
      roleLabel,
      patientId: packet.patient_id,
      patientName: patient.demographics.synthetic_name,
      caseId: packet.case_id,
      policyTitle: packet.policy_title,
      procedure: packet.procedure,
      readinessPercent: packet.readiness_percent,
      gapCount: packet.gap_count,
      humanReviewRequired: packet.human_review_required,
      criteria: packet.criteria.map((item) => ({
        plain_status: item.plain_status || criterionStatusLabel(item.status),
        criterion: item.criterion,
      })),
      gaps: packet.gaps.map((gap) => ({
        label: gap.label,
        action: gap.action,
      })),
      nextSteps: packet.next_steps,
      pathway: packet.documentation_pathway?.map((step) => ({
        title: step.title,
        detail: step.detail,
      })),
      scorecardNote: packet.readiness_scorecard?.recommendation,
      packetSummary: packet.packet_summary,
      disclaimer: packet.disclaimer,
    });
  }

  async function openSource(documentId: string) {
    setSourceBusy(true);
    setError("");
    try {
      const document = await getDocument(documentId);
      setSource(document.content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open attached document");
    } finally {
      setSourceBusy(false);
    }
  }

  if (error && !patient) {
    return (
      <section className="page">
        <p>
          <Link className="text-link" to="/patients">
            ← Patients
          </Link>
        </p>
        <p className="error" role="alert">
          {error}
        </p>
      </section>
    );
  }

  if (!patient) {
    return <p className="muted">Loading patient file…</p>;
  }

  const age = ageYears(patient.demographics.date_of_birth);
  const conditionPreview = patient.conditions.slice(0, 4);

  return (
    <section className="page chart-page">
      <div className="chart-sticky" id="patient-banner">
        <div className="chart-sticky-top">
          <Link className="text-link" to="/patients">
            ← Patients
          </Link>
          <div className="chart-actions">
            {canPrepare ? (
              <button
                type="button"
                className="btn btn-primary sm"
                disabled={prepBusy || !policyId}
                onClick={() => {
                  document.getElementById("evidence-packet")?.scrollIntoView({
                    behavior: "smooth",
                    block: "start",
                  });
                  void runPrepare();
                }}
              >
                {prepBusy ? "Checking…" : packet ? "Re-check" : "Prepare evidence pack"}
              </button>
            ) : null}
            {canDocument ? (
              <Link
                className="btn btn-ghost sm"
                to={`/visit?patient=${encodeURIComponent(patient.patient_id)}`}
              >
                Visit note
              </Link>
            ) : null}
            <Link
              className="btn btn-ghost sm"
              to={`/reviews?patient=${encodeURIComponent(patient.patient_id)}`}
              title={
                canAdjudicate
                  ? undefined
                  : "View only — final sign-off needs a senior clinician"
              }
            >
              Reviews
            </Link>
          </div>
        </div>
        <div className="chart-identity">
          <div>
            <h1 className="chart-name">{patient.demographics.synthetic_name}</h1>
            <p className="chart-id">{patient.patient_id}</p>
          </div>
          <dl className="chart-facts">
            <div>
              <dt>Age</dt>
              <dd>{age != null ? `${age} yrs` : "—"}</dd>
            </div>
            <div>
              <dt>Sex</dt>
              <dd>{patient.demographics.sex}</dd>
            </div>
            <div>
              <dt>DOB</dt>
              <dd>{patient.demographics.date_of_birth}</dd>
            </div>
            <div>
              <dt>Records</dt>
              <dd>{timeline.length}</dd>
            </div>
          </dl>
        </div>
        <div className="chart-conditions">
          {conditionPreview.length === 0 ? (
            <span className="muted">No conditions recorded</span>
          ) : (
            conditionPreview.map((condition) => (
              <span key={condition} className="chip chip-static">
                {conditionLabel(condition)}
              </span>
            ))
          )}
          {patient.conditions.length > 4 ? (
            <span className="muted">+{patient.conditions.length - 4} more</span>
          ) : null}
          {specialties.length > 0 ? (
            <span className="muted chart-specialty-note">
              {specialties.slice(0, 3).join(" · ")}
              {specialties.length > 3 ? ` +${specialties.length - 3}` : ""}
            </span>
          ) : null}
        </div>
      </div>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {lifelong ? (
        <details className="panel compact lifelong-panel chart-collapse" id="lifelong-history">
          <summary className="chart-collapse-summary">
            <span className="panel-title">Lifelong history</span>
            <span className="muted">
              {lifelong.events.length} past events
              {lifelongDisorders.length ? ` · ${lifelongDisorders.length} topics` : ""}
            </span>
          </summary>
          {lifelong.includes_demo_synthetic ? (
            <p className="error lifelong-demo-banner" role="alert">
              {lifelong.demo_synthetic_disclaimer ||
                "DEMO ONLY — invented example history, not from this patient's chart."}
            </p>
          ) : null}
          <p className="hint lifelong-brief-tight">{lifelong.doctor_brief}</p>
          <div className="lifelong-filter-bar" aria-label="Topic filter">
            <div className="chip-row specialty-filter compact label-filter">
              <button
                type="button"
                className={`chip ${lifelongDisorder === "all" ? "chip-active" : ""}`}
                onClick={() => setLifelongDisorder("all")}
              >
                All
              </button>
              {lifelongDisorders.map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`chip ${lifelongDisorder === label ? "chip-active" : ""}`}
                  onClick={() => setLifelongDisorder(label)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {lifelongVisible.length === 0 ? (
            <p className="muted">No history for this topic yet.</p>
          ) : (
            <ul className="lifelong-list">
              {lifelongVisible.map((event) => (
                <li key={event.event_id} className="lifelong-item">
                  <div className="lifelong-when">
                    {event.occurred_on ? event.occurred_on.slice(0, 4) : "—"}
                  </div>
                  <div className="lifelong-body">
                    <div className="lifelong-top">
                      <strong>{event.title}</strong>
                      <span className="badge neutral">{event.category}</span>
                      {event.demo_synthetic ? (
                        <span className="badge warn">DEMO ONLY</span>
                      ) : null}
                    </div>
                    <p>{event.summary}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="hint">
            {isPatient ? (
              <Link className="text-link" to="/my-record">
                Full lifelong view
              </Link>
            ) : (
              <Link
                className="text-link"
                to={`/my-record?patient=${encodeURIComponent(patient.patient_id)}`}
                onClick={() => setMyPatientId(patient.patient_id)}
              >
                Open lifelong chart for this patient
              </Link>
            )}
          </p>
        </details>
      ) : null}

      <div className="panel essentials-panel compact" id="medical-essentials">
        <div className="review-checklist-head">
          <h2 className="panel-title">
            Must-have chart items
            {essentials ? (
              <span className="muted"> · {essentials.completeness_percent}% ready</span>
            ) : null}
          </h2>
        </div>
        {essentials ? (
          (() => {
            const needsWork = essentials.sections.filter(
              (section) =>
                section.status === "missing" ||
                section.status === "thin" ||
                section.status === "unknown",
            );
            if (needsWork.length === 0) {
              return (
                <p className="muted">
                  Core chart items look complete enough to prepare an evidence pack.
                </p>
              );
            }
            return (
              <div className="essentials-grid essentials-grid-tight">
                {needsWork.map((section) => (
                  <Link
                    key={section.key}
                    className={`essentials-card status-${section.status}`}
                    to={essentialsVisitHref(patient.patient_id, section)}
                    aria-label={`${section.label}: ${essentialsStatusLabel(section.status)}. ${section.action}`}
                  >
                    <span className="essentials-label">{section.label}</span>
                    <strong className="essentials-count">{section.count}</strong>
                    <span
                      className={`badge ${
                        section.status === "thin"
                          ? "warn"
                          : section.status === "missing"
                            ? "bad"
                            : "neutral"
                      }`}
                    >
                      {essentialsStatusLabel(section.status)}
                    </span>
                    <span className="muted essentials-highlight">{section.action}</span>
                  </Link>
                ))}
              </div>
            );
          })()
        ) : (
          <p className="muted">Loading chart items…</p>
        )}
      </div>

      <div className="panel packet-panel compact" id="evidence-packet">
        <div className="packet-intro packet-intro-tight">
          <h2 className="panel-title">Evidence pack</h2>
          {canPrepare && policies.length > 1 ? (
            <label className="field packet-policy-inline">
              <span className="sr-only">Policy</span>
              <select
                value={policyId}
                onChange={(event) => {
                  setPolicyId(event.target.value);
                  setPacket(null);
                }}
              >
                {policies.map((item) => (
                  <option key={item.policy_id} value={item.policy_id}>
                    {policyOptionLabel(item)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {canPrepare ? (
            <button
              type="button"
              className="btn btn-primary sm"
              onClick={() => void runPrepare()}
              disabled={prepBusy || !policyId}
            >
              {prepBusy
                ? "Checking…"
                : packet
                  ? "Re-check evidence pack"
                  : "Prepare evidence pack"}
            </button>
          ) : (
            <p className="hint">Preparing an evidence pack needs a care-team sign-in.</p>
          )}
        </div>

        {packet ? (
          <div className="packet-result packet-result-tight">
            <div className="readiness-meter" aria-label={`Evidence pack ${packet.readiness_percent}% ready`}>
              <div className="readiness-meter-top">
                <strong>{packet.readiness_percent}% of checklist covered</strong>
                <span className="muted">
                  {packet.gap_count} open item{packet.gap_count === 1 ? "" : "s"}
                  {packet.estimated_prep_minutes != null
                    ? ` · ~${packet.estimated_prep_minutes} min to finish`
                    : ""}
                </span>
              </div>
              <div className="readiness-track">
                <div
                  className={`readiness-fill ${packet.readiness_percent >= 80 ? "ok" : "warn"}`}
                  style={{ width: `${Math.max(packet.readiness_percent, 4)}%` }}
                />
              </div>
              <div className="result-badges">
                {packet.human_review_required ? (
                  <span className="badge warn">Needs senior review</span>
                ) : (
                  <span className="badge ok">Ready to send for review</span>
                )}
                <span className={`badge ${documentationRiskClass(packet.documentation_risk)}`}>
                  {packet.documentation_risk === "high"
                    ? "Likely returned for more notes"
                    : packet.documentation_risk === "moderate"
                      ? "Still incomplete"
                      : "Ready for review"}
                </span>
              </div>
            </div>

            <AgentTrace
              steps={packet.agent_trace || []}
              scoringPath={packet.scoring_path}
              aiBrief={packet.ai_brief}
              mcpTools={packet.mcp_tools_used}
              compact
              collapsed
            />

            {packet.readiness_scorecard ? (
              <div className="review-next packet-next-tight" aria-label="Ready to send">
                <p className="eyebrow">Ready to send for review?</p>
                <strong>
                  {packet.readiness_scorecard.handoff_readiness_percent}% ready to send
                </strong>
                <p className="muted">{packet.readiness_scorecard.recommendation}</p>
                {packet.readiness_scorecard.blockers?.length ? (
                  <ul className="muted">
                    {packet.readiness_scorecard.blockers.slice(0, 4).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {packet.readiness_scorecard.pace_note ? (
                  <p className="muted">{packet.readiness_scorecard.pace_note}</p>
                ) : null}
              </div>
            ) : null}

            {packet.documentation_pathway && packet.documentation_pathway.length > 0 ? (
              <div className="review-next packet-next-tight" aria-label="What to do next">
                <p className="eyebrow">What to do next</p>
                {packet.pathway_summary ? <p className="muted">{packet.pathway_summary}</p> : null}
                <ol className="muted">
                  {packet.documentation_pathway.slice(0, 6).map((step) => (
                    <li key={`${step.step}-${step.title}`}>
                      <strong>{step.title}</strong>
                      {step.detail ? ` — ${step.detail}` : ""}
                    </li>
                  ))}
                </ol>
                {packet.critic_summary ? <p className="muted">{packet.critic_summary}</p> : null}
              </div>
            ) : null}

            {packet.next_best_action ? (
              <div className="review-next packet-next-tight" aria-label="Next documentation step">
                <div className="next-best-row">
                  <div>
                    <p className="eyebrow">
                      Start here · about {packet.next_best_action.estimated_minutes} min
                    </p>
                    <strong>{packet.next_best_action.label}</strong>
                  </div>
                  {packet.next_best_action.draft_suggestion ? (
                    <p className="hint ai-draft-preview" role="status">
                      {packet.next_best_action.draft_source?.startsWith("ai:")
                        ? "AI draft · "
                        : "Draft · "}
                      {packet.next_best_action.draft_suggestion}
                    </p>
                  ) : null}
                  <div className="home-actions">
                    <Link
                      className="btn btn-primary sm"
                      to={visitGapHref(packet.patient_id, packet.next_best_action)}
                    >
                      {packet.next_best_action.draft_suggestion
                        ? "Use AI draft in visit note"
                        : "Add visit note"}
                    </Link>
                    <button
                      type="button"
                      className="btn btn-ghost sm"
                      onClick={() => runPrintPacket()}
                    >
                      Print / Save as PDF
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="home-actions">
                <p className="muted">Nothing left open on this checklist.</p>
                <button
                  type="button"
                  className="btn btn-ghost sm"
                  onClick={() => runPrintPacket()}
                >
                  Print / Save as PDF
                </button>
              </div>
            )}

            {packet.gaps.length > 1 ? (
              <details className="packet-details">
                <summary>
                  Other open items
                  <span className="muted"> · {packet.gaps.length - (packet.next_best_action ? 1 : 0)}</span>
                </summary>
                <ul className="gap-list gap-list-tight">
                  {packet.gaps
                    .filter(
                      (gap) =>
                        !packet.next_best_action ||
                        gap.label !== packet.next_best_action.label ||
                        gap.focus !== packet.next_best_action.focus,
                    )
                    .map((gap) => (
                      <li key={`${gap.focus}-${gap.label}`}>
                        <div className="gap-copy">
                          <span>{gap.label}</span>
                          <span className="muted">
                            ~{gap.estimated_minutes ?? 8} min
                            {gap.draft_source?.startsWith("ai:") ? " · AI draft" : ""}
                          </span>
                        </div>
                        <Link
                          className="btn btn-ghost sm"
                          to={visitGapHref(packet.patient_id, gap)}
                        >
                          {gap.draft_suggestion ? "Use draft" : "Fix"}
                        </Link>
                      </li>
                    ))}
                </ul>
              </details>
            ) : null}

            <details className="packet-details">
              <summary>
                Full checklist · summary to copy
                <span className="muted"> · {packet.criteria.length} items</span>
              </summary>
              <ol className="review-checklist">
                {packet.criteria.map((item, index) => (
                  <li className="criterion-card" key={item.criterion_id}>
                    <div className="criterion-card-head">
                      <span className="criterion-index">{index + 1}</span>
                      <div className="criterion-main">
                        <h3>
                          <span className={`status ${criterionStatusClass(item.status)}`}>
                            {item.plain_status || criterionStatusLabel(item.status)}
                          </span>{" "}
                          {item.criterion}
                        </h3>
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              <div className="packet-handoff">
                <div className="home-actions">
                  <button
                    type="button"
                    className="btn btn-ghost sm"
                    onClick={() => void copyPacket()}
                  >
                    {copied ? "Copied" : "Copy summary"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost sm"
                    onClick={() => runPrintPacket()}
                  >
                    Print / Save as PDF
                  </button>
                  <Link
                    className="btn btn-ghost sm"
                    to={`/reviews?case=${encodeURIComponent(packet.case_id)}`}
                  >
                    Open in Reviews
                  </Link>
                </div>
                <pre className="note source-body">{packet.packet_summary}</pre>
              </div>
            </details>
          </div>
        ) : (
          <p className="muted">
            {canPrepare
              ? "Check the checklist once, then add the top missing item to the chart."
              : "Sign in as care team to prepare an evidence pack."}
          </p>
        )}
      </div>

      <div className="history-block" id="history-documents">
        <div className="history-head">
          <h2 className="panel-title">Chart file</h2>
        </div>

      <div className="mode-tabs" role="tablist" aria-label="Chart sections">
        {(
          [
            ["file", "Chart file"],
            ["notes", "Notes"],
            ["labs", "Labs"],
            ["meds", "Medications"],
            ["imaging", "Imaging"],
            ["procedures", "Procedures"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            className={`mode-tab ${tab === id ? "active" : ""}`}
            aria-selected={tab === id}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "file" ? (
        <div className="panel patient-file">
          {specialties.length > 1 ? (
            <div className="chip-row specialty-filter compact" aria-label="Specialty filter">
              <button
                type="button"
                className={`chip ${specialtyFilter === "all" ? "chip-active" : ""}`}
                onClick={() => setSpecialtyFilter("all")}
              >
                All
              </button>
              {specialties.map((specialty) => (
                <button
                  key={specialty}
                  type="button"
                  className={`chip ${specialtyFilter === specialty ? "chip-active" : ""}`}
                  onClick={() => setSpecialtyFilter(specialty)}
                >
                  {specialty}
                </button>
              ))}
            </div>
          ) : null}

          {visibleEvents.length === 0 ? (
            <p className="muted">No records for this specialty yet.</p>
          ) : (
            <ol className="file-timeline">
              {visibleEvents.map((event) => {
                const open = expandedId === event.event_id;
                return (
                  <li key={event.event_id} className="file-entry">
                    <button
                      type="button"
                      className="file-entry-toggle linkish"
                      onClick={() => setExpandedId(open ? null : event.event_id)}
                      aria-expanded={open}
                    >
                      <span className="file-when">{formatWhen(event.timestamp)}</span>
                      <span className="file-type">
                        {TYPE_LABELS[event.event_type] || event.event_type}
                      </span>
                      <strong className="file-title">{event.title || event.event_id}</strong>
                      <span className="badge neutral">{event.specialty || "General medicine"}</span>
                    </button>
                    {open ? (
                      <div className="file-entry-body">
                        <p className="muted">{event.description}</p>
                        {event.document_id ? (
                          <button
                            type="button"
                            className="btn btn-ghost sm"
                            disabled={sourceBusy}
                            onClick={() => openSource(event.document_id!)}
                          >
                            {sourceBusy ? "Opening…" : "Open document"}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          )}

          {source ? (
            <div className="source-panel" style={{ marginTop: 14 }}>
              <div className="review-checklist-head">
                <h3 className="panel-title">Document</h3>
                <button type="button" className="btn btn-ghost sm" onClick={() => setSource("")}>
                  Close
                </button>
              </div>
              <pre className="note source-body">{source}</pre>
            </div>
          ) : null}
        </div>
      ) : null}

      {tab === "notes" ? (
        <div className="panel">
          <h2 className="panel-title">Clinical notes</h2>
          {patient.clinical_notes.length === 0 ? <p className="muted">No notes recorded.</p> : null}
          {patient.clinical_notes.map((note) => (
            <article className="note-block" key={note.note_id}>
              <p className="note-meta">
                {noteTypeLabel(note.note_type)} · {formatWhen(note.authored_at)}
              </p>
              <pre className="note">{note.content}</pre>
            </article>
          ))}
        </div>
      ) : null}

      {tab === "labs" ? (
        <div className="panel">
          <h2 className="panel-title">Laboratory results</h2>
          {patient.labs.length === 0 ? <p className="muted">None recorded.</p> : null}
          <ul className="plain-list">
            {patient.labs.map((item) => (
              <li key={item.lab_id}>
                {item.test_name}: {item.value} {item.unit}
                <span className="muted"> · {formatWhen(item.collected_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {tab === "meds" ? (
        <div className="panel">
          <h2 className="panel-title">Medications</h2>
          {patient.medications.length === 0 ? <p className="muted">None recorded.</p> : null}
          <ul className="plain-list">
            {patient.medications.map((item) => (
              <li key={item.medication_id}>
                {item.name}
                <span className="muted">
                  {" "}
                  · {item.dose} · {item.status}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {tab === "imaging" ? (
        <div className="panel">
          <h2 className="panel-title">Imaging</h2>
          {patient.imaging.length === 0 ? <p className="muted">No imaging recorded.</p> : null}
          <ul className="plain-list">
            {patient.imaging.map((study) => (
              <li key={study.imaging_id}>
                {study.modality} · {study.body_part} · {study.description}
                <span className="muted"> · {formatWhen(study.study_date)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {tab === "procedures" ? (
        <div className="panel compact">
          <h2 className="panel-title">Procedures</h2>
          {patient.procedures.length === 0 ? <p className="muted">None recorded.</p> : null}
          <ul className="plain-list">
            {patient.procedures.map((item) => (
              <li key={item.procedure_id}>
                {item.name}
                <span className="muted"> · {formatWhen(item.performed_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      </div>
    </section>
  );
}
