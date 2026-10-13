import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  assignCase,
  getCaseAudit,
  getCases,
  getDocument,
  getPolicy,
  resumeReview,
  reviewCase,
  seniorReviewAssist,
  type AuthCase,
  type CaseAuditEvent,
  type PolicyDetail,
  type Review,
  type SeniorReviewAssist,
} from "../api";
import { formatLiveAge, useLiveRefresh } from "../hooks/useLiveRefresh";
import {
  caseStatusLabel,
  coverageLabel,
  criterionStatusClass,
  criterionStatusLabel,
  deskFacingText,
  documentTypeLabel,
  procedureDisplayName,
  sourceDisplay,
} from "../labels";
import { useRole } from "../roleContext";
import { AgentTrace } from "../components/AgentTrace";
import { printEvidencePacket } from "../printSheet";

type CriterionStatus = Review["criteria"][number]["status"] | "PENDING";
type CaseStatus = NonNullable<AuthCase["status"]>;
type QueueFilter = "open" | "all" | CaseStatus;

type ChecklistRow = {
  criterion_id: string;
  criterion: string;
  status: CriterionStatus;
  reason: string;
  evidence: Review["criteria"][number]["evidence"];
};

function sourceLabel(documentType: string, _documentId: string): string {
  return sourceDisplay(documentType);
}

function statusPlain(status: CriterionStatus): string {
  return criterionStatusLabel(status);
}

function statusTone(status: CriterionStatus): string {
  return criterionStatusClass(status);
}

function caseStatusTone(status: CaseStatus | undefined): string {
  switch (status) {
    case "needs_documentation":
    case "ready_for_human":
      return "warn";
    case "closed_as_draft":
      return "ok";
    default:
      return "neutral";
  }
}

function gapFocus(text: string): { focus: string; label: string; specialty: string } {
  const lower = text.toLowerCase();
  if (lower.includes("lab") || lower.includes("a1c") || lower.includes("laboratory")) {
    return { focus: "labs", label: "Document lab", specialty: "Laboratory" };
  }
  if (lower.includes("medic") || lower.includes("drug") || lower.includes("therapy")) {
    return { focus: "meds", label: "Document medication", specialty: "Pharmacy" };
  }
  if (lower.includes("imaging") || lower.includes("mri") || lower.includes("ct ")) {
    return { focus: "note", label: "Document imaging note", specialty: "Radiology" };
  }
  if (lower.includes("diagnos") || lower.includes("condition")) {
    return { focus: "diagnoses", label: "Document diagnosis", specialty: "General medicine" };
  }
  return { focus: "note", label: "Add visit note", specialty: "General medicine" };
}

function visitGapHref(patientId: string, gap: string, policyId?: string): string {
  const { focus, specialty } = gapFocus(gap);
  const params = new URLSearchParams({
    patient: patientId,
    focus,
    gap,
    specialty,
  });
  if (policyId) {
    params.set("policy", policyId);
  }
  return `/visit?${params.toString()}`;
}

function countByStatus(rows: ChecklistRow[]) {
  return rows.reduce(
    (acc, row) => {
      acc[row.status] = (acc[row.status] || 0) + 1;
      return acc;
    },
    {} as Partial<Record<CriterionStatus, number>>,
  );
}

export function AuthorizationPage() {
  const { canAdjudicate, role, label: roleLabel, facilityLabel } = useRole();
  const [searchParams, setSearchParams] = useSearchParams();
  const [cases, setCases] = useState<AuthCase[]>([]);
  const [caseId, setCaseId] = useState("");
  const [policy, setPolicy] = useState<PolicyDetail | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [auditEvents, setAuditEvents] = useState<CaseAuditEvent[]>([]);
  const [claimBusy, setClaimBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [source, setSource] = useState<{
    document_id: string;
    document_type: string;
    content: string;
  } | null>(null);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingCases, setLoadingCases] = useState(true);
  const [query, setQuery] = useState("");
  const [queueFilter, setQueueFilter] = useState<QueueFilter>(() => {
    const raw = searchParams.get("queue");
    if (raw === "clinician" || raw === "ready_for_human") {
      return "ready_for_human";
    }
    if (
      raw === "needs_documentation" ||
      raw === "queued" ||
      raw === "closed_as_draft" ||
      raw === "open" ||
      raw === "all"
    ) {
      return raw;
    }
    // Deep-linked case: keep Open so the case stays visible. Empty Reviews: senior first.
    if (searchParams.get("case") || searchParams.get("patient")) {
      return "open";
    }
    return "ready_for_human";
  });
  const [focusFilter, setFocusFilter] = useState<"all" | "gaps">("all");
  const [resumeNotes, setResumeNotes] = useState("");
  const [resumeBusy, setResumeBusy] = useState(false);
  const [seniorAssist, setSeniorAssist] = useState<SeniorReviewAssist | null>(null);
  const [seniorAssistBusy, setSeniorAssistBusy] = useState(false);
  const [seniorAssistError, setSeniorAssistError] = useState("");
  const [seniorAssistEdited, setSeniorAssistEdited] = useState(false);
  const seniorAssistFor = useRef<string | null>(null);

  function patchSeniorAssist(patch: Partial<SeniorReviewAssist>) {
    setSeniorAssist((prev) => (prev ? { ...prev, ...patch } : prev));
    setSeniorAssistEdited(true);
  }

  function patchSeniorFocus(
    index: number,
    patch: Partial<SeniorReviewAssist["focus_items"][number]>,
  ) {
    setSeniorAssist((prev) => {
      if (!prev) {
        return prev;
      }
      const focus_items = prev.focus_items.map((item, i) =>
        i === index ? { ...item, ...patch } : item,
      );
      return { ...prev, focus_items };
    });
    setSeniorAssistEdited(true);
  }

  function removeSeniorFocus(index: number) {
    setSeniorAssist((prev) => {
      if (!prev) {
        return prev;
      }
      return { ...prev, focus_items: prev.focus_items.filter((_, i) => i !== index) };
    });
    setSeniorAssistEdited(true);
  }

  function addSeniorFocus() {
    setSeniorAssist((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        focus_items: [
          ...prev.focus_items,
          { title: "New focus item", detail: "", severity: "moderate" },
        ],
      };
    });
    setSeniorAssistEdited(true);
  }

  function setSeniorDeskAction(action: "needs_documentation" | "acknowledge_after_check") {
    patchSeniorAssist({
      recommended_desk_action: action,
      recommended_desk_action_label:
        action === "needs_documentation"
          ? "Send back for more notes"
          : "Confirm checklist reviewed (after spot-check)",
    });
  }
  const autoRanFor = useRef<string | null>(null);
  const initialDeepLinkCase = useRef(searchParams.get("case"));
  const workspaceRef = useRef<HTMLDivElement | null>(null);

  const patientFilter = searchParams.get("patient") || "";
  const selected = cases.find((item) => item.case_id === caseId) ?? null;

  useEffect(() => {
    if (!caseId) {
      setAuditEvents([]);
      return;
    }
    let cancelled = false;
    getCaseAudit(caseId)
      .then((body) => {
        if (!cancelled) {
          setAuditEvents(body.events || []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAuditEvents([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [caseId, review?.run_id, review?.awaiting_human_review]);

  async function claimSelectedCase() {
    if (!selected || claimBusy) {
      return;
    }
    setClaimBusy(true);
    setError("");
    try {
      // Demo sign-in subjects are role names; claim with a stable desk subject.
      await assignCase(selected.case_id, `desk:${role}`);
      const body = await getCaseAudit(selected.case_id);
      setAuditEvents(body.events || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not claim case");
    } finally {
      setClaimBusy(false);
    }
  }

  useEffect(() => {
    const raw = searchParams.get("queue");
    if (!raw) {
      return;
    }
    if (raw === "clinician" || raw === "ready_for_human") {
      setQueueFilter("ready_for_human");
      return;
    }
    if (
      raw === "needs_documentation" ||
      raw === "queued" ||
      raw === "closed_as_draft" ||
      raw === "open" ||
      raw === "all"
    ) {
      setQueueFilter(raw);
    }
  }, [searchParams]);

  const loadCases = useCallback(async () => {
    try {
      const body = await getCases();
      setCases(body.cases);
      const fromQuery = searchParams.get("case");
      const patient = searchParams.get("patient");
      setCaseId((current) => {
        if (fromQuery && body.cases.some((item) => item.case_id === fromQuery)) {
          return fromQuery;
        }
        if (patient) {
          const match = body.cases.find((item) => item.patient_id === patient);
          if (match) {
            return match.case_id;
          }
        }
        if (current && body.cases.some((item) => item.case_id === current)) {
          return current;
        }
        return body.cases[0]?.case_id ?? "";
      });
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh cases");
    } finally {
      setLoadingCases(false);
    }
  }, [searchParams]);

  const { lastUpdatedAt, refreshNow, pushConnected } = useLiveRefresh(loadCases, {
    intervalMs: 60_000,
    enabled: !busy && !resumeBusy && !claimBusy,
  });

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 5_000);
    return () => window.clearInterval(id);
  }, []);
  void tick;

  useEffect(() => {
    const fromQuery = searchParams.get("case");
    const patient = searchParams.get("patient");
    if (!cases.length) {
      return;
    }
    if (fromQuery && cases.some((item) => item.case_id === fromQuery)) {
      setCaseId(fromQuery);
      return;
    }
    if (patient) {
      const match = cases.find((item) => item.patient_id === patient);
      if (match) {
        setCaseId(match.case_id);
      }
    }
  }, [cases, searchParams]);

  useEffect(() => {
    if (!selected) {
      setPolicy(null);
      setReview(null);
      return;
    }
    setReview(null);
    setSource(null);
    setFocusFilter("all");
    setError("");
    getPolicy(selected.policy_id)
      .then(setPolicy)
      .catch((err: Error) => setError(err.message));
  }, [selected?.case_id, selected?.policy_id]);

  useEffect(() => {
    if (!caseId) {
      return;
    }
    const next = new URLSearchParams(searchParams);
    if (next.get("case") === caseId) {
      return;
    }
    next.set("case", caseId);
    setSearchParams(next, { replace: true });
  }, [caseId, searchParams, setSearchParams]);

  const filteredCases = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return cases.filter((item) => {
      if (patientFilter && item.patient_id !== patientFilter) {
        return false;
      }
      const status = item.status || "queued";
      if (queueFilter === "open" && status === "closed_as_draft") {
        return false;
      }
      if (
        queueFilter !== "open" &&
        queueFilter !== "all" &&
        status !== queueFilter
      ) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return (
        item.case_id.toLowerCase().includes(needle) ||
        item.patient_id.toLowerCase().includes(needle) ||
        item.procedure.toLowerCase().includes(needle) ||
        item.policy_title.toLowerCase().includes(needle) ||
        caseStatusLabel(status).toLowerCase().includes(needle)
      );
    });
  }, [cases, patientFilter, query, queueFilter]);

  const checklist: ChecklistRow[] = useMemo(() => {
    if (review) {
      return review.criteria.map((criterion) => ({
        criterion_id: criterion.criterion_id,
        criterion: criterion.criterion,
        status: criterion.status,
        reason: criterion.reason,
        evidence: criterion.evidence,
      }));
    }
    if (policy) {
      return policy.criteria.map((criterion) => ({
        criterion_id: criterion.criterion_id,
        criterion: criterion.description,
        status: "PENDING" as const,
        reason: "",
        evidence: [],
      }));
    }
    return [];
  }, [policy, review]);

  const counts = countByStatus(checklist);
  const visibleChecklist =
    focusFilter === "gaps" && review
      ? checklist.filter((row) => row.status !== "SUPPORTED")
      : checklist;

  async function refreshCases() {
    const body = await getCases();
    setCases(body.cases);
  }

  async function runReview(target = selected) {
    if (!target) {
      return;
    }
    setBusy(true);
    setError("");
    setSource(null);
    try {
      const body = await reviewCase({
        patient_id: target.patient_id,
        policy_id: target.policy_id,
        procedure: target.procedure,
        case_id: target.case_id,
        interactive: true,
      });
      setReview(body);
      await refreshCases();
      window.setTimeout(() => {
        workspaceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 50);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Review failed. Check that the API is running.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function completeHumanStep(decision?: "acknowledged" | "needs_documentation") {
    if (!review?.run_id) {
      return;
    }
    const fromAssist =
      seniorAssist?.recommended_desk_action === "acknowledge_after_check"
        ? "acknowledged"
        : seniorAssist?.recommended_desk_action === "needs_documentation"
          ? "needs_documentation"
          : undefined;
    const chosen = decision ?? fromAssist ?? "needs_documentation";
    setResumeBusy(true);
    setError("");
    try {
      const body = await resumeReview(review.run_id, {
        decision: chosen,
        notes: resumeNotes.trim(),
        senior_assist: seniorAssist
          ? {
              ...seniorAssist,
              suggested_clinician_note:
                resumeNotes.trim() || seniorAssist.suggested_clinician_note,
              edited: seniorAssistEdited,
            }
          : undefined,
      });
      setReview(body);
      setResumeNotes("");
      setSeniorAssist(null);
      setSeniorAssistEdited(false);
      seniorAssistFor.current = null;
      await refreshCases();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record clinician step");
    } finally {
      setResumeBusy(false);
    }
  }

  async function loadSeniorAssist(current: Review, { force = false }: { force?: boolean } = {}) {
    if (force && seniorAssistEdited) {
      const ok = window.confirm(
        "Replace your edited AI review with a fresh assist? Your edits will be lost.",
      );
      if (!ok) {
        return;
      }
    }
    const key = `${current.run_id || current.case_id || ""}:${current.patient_id}`;
    setSeniorAssistBusy(true);
    setSeniorAssistError("");
    try {
      const criticNotes = (current.agent_trace || [])
        .filter((step) => /critic|flag|weak|uncited/i.test(`${step.agent} ${step.detail}`))
        .map((step) => step.detail)
        .filter(Boolean)
        .slice(0, 8);
      const body = await seniorReviewAssist({
        patient_id: current.patient_id,
        case_id: current.case_id,
        procedure: current.procedure || "Evidence pack documentation",
        criteria: current.criteria.map((row) => ({
          criterion: row.criterion,
          status: row.status,
          reason: row.reason || "",
        })),
        missing_evidence: current.missing_evidence || [],
        contradictions: (current.contradictions || []).map(
          (item) => item.description || item.criterion,
        ),
        critic_notes: criticNotes,
        report_summary: current.report_summary || "",
      });
      setSeniorAssist(body);
      setSeniorAssistEdited(false);
      seniorAssistFor.current = key;
      if (body.suggested_clinician_note) {
        setResumeNotes(body.suggested_clinician_note);
      }
    } catch (err) {
      setSeniorAssistError(
        err instanceof Error ? err.message : "Could not load AI review assist",
      );
      setSeniorAssist(null);
      setSeniorAssistEdited(false);
    } finally {
      setSeniorAssistBusy(false);
    }
  }

  useEffect(() => {
    if (!canAdjudicate || !review?.awaiting_human_review) {
      if (!review?.awaiting_human_review) {
        setSeniorAssist(null);
        setSeniorAssistEdited(false);
        seniorAssistFor.current = null;
      }
      return;
    }
    const key = `${review.run_id || review.case_id || ""}:${review.patient_id}`;
    if (seniorAssistFor.current === key) {
      return;
    }
    void loadSeniorAssist(review);
    // Auto-load once per paused HITL review for seniors.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    canAdjudicate,
    review?.run_id,
    review?.case_id,
    review?.patient_id,
    review?.awaiting_human_review,
  ]);

  useEffect(() => {
    if (!selected || loadingCases || busy || review || !policy) {
      return;
    }
    const target = initialDeepLinkCase.current;
    if (!target || target !== selected.case_id || autoRanFor.current === target) {
      return;
    }
    autoRanFor.current = target;
    void runReview(selected);
    // Auto-run once for the case that opened this page via deep link.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.case_id, loadingCases, busy, review, policy]);

  useEffect(() => {
    // Deep-linked closed drafts vanish under the default "open" filter — show all so the case stays visible.
    if (selected?.status === "closed_as_draft" && queueFilter === "open") {
      setQueueFilter("all");
    }
  }, [selected?.case_id, selected?.status, queueFilter]);

  async function openSource(documentId: string) {
    setError("");
    setSourceBusy(true);
    try {
      const document = await getDocument(documentId);
      setSource({
        document_id: document.document_id,
        document_type: document.document_type,
        content: document.content,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the source document");
    } finally {
      setSourceBusy(false);
    }
  }

  function selectCase(nextId: string) {
    setCaseId(nextId);
  }

  function clearPatientFilter() {
    const next = new URLSearchParams(searchParams);
    next.delete("patient");
    if (caseId) {
      next.set("case", caseId);
    }
    setSearchParams(next, { replace: true });
  }

  return (
    <section className="page">
      <header className="page-header split">
        <div>
          <p className="eyebrow">Prior authorization</p>
          <h1 className="page-title">Reviews</h1>
          <p className="page-subtitle">
            Confirm checklist items against the chart, or return the case for more documentation.
            Residents may prepare; seniors confirm. Never approves or denies care.
          </p>
          <p className="live-stamp">
            <span aria-live="polite">{formatLiveAge(lastUpdatedAt, pushConnected)}</span>
            {" · "}
            <button type="button" className="text-link" onClick={refreshNow}>
              Refresh now
            </button>
          </p>
        </div>
        <div className="home-actions">
          <Link className="btn btn-ghost" to="/">
            Today
          </Link>
          <Link className="btn btn-ghost" to="/visit">
            Add visit note
          </Link>
        </div>
      </header>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {loadingCases ? <p className="muted">Loading cases…</p> : null}

      {!loadingCases && cases.length === 0 ? (
        <div className="empty">
          <h2>No review cases</h2>
          <p>Add a visit note to create a case, then return here.</p>
          <Link className="btn btn-primary" to="/visit">
            Add visit note
          </Link>
        </div>
      ) : null}

      {cases.length > 0 ? (
        <div className="review-layout">
          <aside className="panel review-queue" aria-label="Case queue">
            <div className="review-queue-head">
              <h2 className="panel-title">Case queue</h2>
              <span className="muted">{filteredCases.length}</span>
            </div>

            <label className="search-field">
              <span className="sr-only">Filter cases</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter by case, patient, procedure…"
              />
            </label>

            <div className="mode-tabs" role="tablist" aria-label="Case status filter">
              {(
                [
                  ["ready_for_human", "For review"],
                  ["needs_documentation", "Needs notes"],
                  ["queued", "Waiting"],
                  ["open", "Open"],
                  ["all", "All"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`mode-tab ${queueFilter === value ? "active" : ""}`}
                  onClick={() => {
                    setQueueFilter(value);
                    const next = new URLSearchParams(searchParams);
                    next.set("queue", value);
                    setSearchParams(next, { replace: true });
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            {patientFilter ? (
              <div className="chip-row">
                <span className="chip-label">Patient</span>
                <button type="button" className="chip chip-active" onClick={clearPatientFilter}>
                  {patientFilter} ×
                </button>
              </div>
            ) : null}

            {filteredCases.length === 0 ? (
              <p className="muted">No cases match this filter.</p>
            ) : (
              <ul className="worklist review-case-list">
                {filteredCases.map((item) => {
                  const active = item.case_id === caseId;
                  return (
                    <li key={item.case_id}>
                      <button
                        type="button"
                        className={`worklist-link linkish review-case ${active ? "active" : ""}`}
                        onClick={() => selectCase(item.case_id)}
                        aria-current={active ? "true" : undefined}
                      >
                        <strong>{procedureDisplayName(item.procedure)}</strong>
                        <span>
                          {item.patient_id}
                          {item.policy_title ? ` · ${item.policy_title}` : ""}
                        </span>
                        <span className={`badge ${caseStatusTone(item.status)}`}>
                          {caseStatusLabel(item.status)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </aside>

          <div className="review-workspace" ref={workspaceRef}>
            {!selected ? (
              <div className="empty soft">
                <p>Select a case from the queue to start the checklist.</p>
              </div>
            ) : (
              <>
                <div className="panel review-case-card">
                  <div className="review-case-top">
                    <div>
                      <p className="eyebrow">Evidence pack review</p>
                      <h2 className="review-case-title">
                        {procedureDisplayName(selected.procedure)}
                      </h2>
                      <p className="muted">
                        Patient{" "}
                        <Link className="text-link" to={`/patients/${selected.patient_id}`}>
                          {selected.patient_id}
                        </Link>
                        {" · "}
                        {selected.policy_title &&
                        !/catalog|dynamic/i.test(selected.policy_title)
                          ? selected.policy_title
                          : "Prior authorization evidence checklist"}
                      </p>
                      <div className="home-actions" style={{ marginTop: "0.5rem" }}>
                        <button
                          type="button"
                          className="btn btn-ghost sm"
                          disabled={claimBusy}
                          onClick={() => void claimSelectedCase()}
                        >
                          {claimBusy ? "Claiming…" : "Claim for my queue"}
                        </button>
                      </div>
                      <p className="case-status-line">
                        <span className={`badge ${caseStatusTone(selected.status)}`}>
                          {caseStatusLabel(selected.status)}
                        </span>
                        {selected.lifecycle_note ? (
                          <span className="muted"> · {selected.lifecycle_note}</span>
                        ) : null}
                      </p>
                    </div>
                    <button
                      className="btn btn-primary"
                      type="button"
                      onClick={() => runReview()}
                      disabled={busy}
                    >
                      {busy
                        ? "Checking chart…"
                        : review
                          ? "Re-check evidence pack"
                          : "Check evidence pack"}
                    </button>
                  </div>

                  {busy ? (
                    <p className="muted pulse review-progress">
                      Matching the insurance checklist to this patient’s chart…
                    </p>
                  ) : null}

                  {review ? (
                    <div className="review-outcome">
                      <AgentTrace
                        steps={review.agent_trace || []}
                        scoringPath={review.scoring_path}
                        aiBrief={review.report_summary || undefined}
                        compact
                        collapsed
                      />
                      <div className="home-actions">
                        <button
                          type="button"
                          className="btn btn-ghost sm"
                          onClick={() =>
                            printEvidencePacket({
                              facilityLabel,
                              doctorName: roleLabel,
                              roleLabel,
                              patientId: selected.patient_id,
                              patientName: "",
                              caseId: selected.case_id,
                              procedure: procedureDisplayName(selected.procedure),
                              policyTitle:
                                selected.policy_title &&
                                !/catalog|dynamic/i.test(selected.policy_title)
                                  ? selected.policy_title
                                  : "Prior authorization evidence checklist",
                              readinessPercent: Math.round(
                                (counts.SUPPORTED || 0) /
                                  Math.max(review.criteria.length, 1) *
                                  100,
                              ),
                              gapCount:
                                (counts.MISSING || 0) +
                                (counts.UNKNOWN || 0) +
                                (counts.NOT_SUPPORTED || 0),
                              humanReviewRequired: Boolean(review.human_review_required),
                              criteria: review.criteria.map((item) => ({
                                plain_status: criterionStatusLabel(item.status),
                                criterion: item.criterion,
                              })),
                              gaps: (review.missing_evidence || []).map((gap) => ({
                                label: gap,
                                minutes: 8,
                              })),
                              nextSteps: [],
                              disclaimer: review.disclaimer,
                            })
                          }
                        >
                          Print / Save as PDF
                        </button>
                        <Link
                          className="btn btn-ghost sm"
                          to={`/patients/${selected.patient_id}?prepare=1`}
                        >
                          Open chart pack
                        </Link>
                      </div>
                      {auditEvents.length > 0 ? (
                        <details className="packet-details audit-trail">
                          <summary>
                            Activity trail
                            <span className="muted"> · {auditEvents.length}</span>
                          </summary>
                          <ol className="plain-list">
                            {auditEvents.slice(0, 12).map((event) => (
                              <li key={event.event_id}>
                                <strong>{event.action.replace(/_/g, " ")}</strong>
                                <span className="muted">
                                  {" "}
                                  · {event.actor}
                                  {event.detail ? ` · ${event.detail}` : ""}
                                </span>
                              </li>
                            ))}
                          </ol>
                        </details>
                      ) : null}
                      <div className="result-badges">
                        <span className={`badge ${review.human_review_required ? "warn" : "ok"}`}>
                          {review.human_review_required
                            ? "Needs clinician review"
                            : "No senior step required"}
                        </span>
                        <span className="badge neutral">{coverageLabel(review.evidence_coverage)}</span>
                        {counts.SUPPORTED ? (
                          <span className="badge ok">
                            {counts.SUPPORTED} found in chart
                          </span>
                        ) : null}
                        {(counts.MISSING || 0) + (counts.UNKNOWN || 0) + (counts.NOT_SUPPORTED || 0) >
                        0 ? (
                          <span className="badge warn">
                            {(counts.MISSING || 0) +
                              (counts.UNKNOWN || 0) +
                              (counts.NOT_SUPPORTED || 0)}{" "}
                            open items
                          </span>
                        ) : null}
                      </div>

                      {review.human_review_required ? (
                        <div className="review-next">
                          <h3 className="panel-title">
                            {review.awaiting_human_review
                              ? "Clinician action needed"
                              : "Next step"}
                          </h3>
                          <p className="muted">
                            {review.human_review_reason ||
                              "One or more checklist items are missing, unclear, or conflicting. Add notes to the chart, or record that a clinician has reviewed — this is not an approval or denial."}
                          </p>

                          {review.awaiting_human_review ? (
                            <div className="hitl-box">
                              {canAdjudicate ? (
                                <>
                                  <div className="senior-ai-assist" aria-live="polite">
                                    <div className="senior-ai-assist-head">
                                      <h4 className="panel-title">Intelligent review assist</h4>
                                      <div className="senior-ai-assist-actions">
                                        {seniorAssistEdited ? (
                                          <span className="badge warn">Edited by you</span>
                                        ) : null}
                                        <button
                                          type="button"
                                          className="btn btn-ghost sm"
                                          disabled={seniorAssistBusy}
                                          onClick={() =>
                                            void loadSeniorAssist(review, { force: true })
                                          }
                                        >
                                          {seniorAssistBusy ? "Refreshing…" : "Reset to AI"}
                                        </button>
                                      </div>
                                    </div>
                                    <p className="hint">
                                      Edit anything below before recording your desk step. AI is a
                                      draft only.
                                    </p>
                                    {seniorAssistError ? (
                                      <p className="hint" role="alert">
                                        {seniorAssistError}
                                      </p>
                                    ) : null}
                                    {seniorAssistBusy && !seniorAssist ? (
                                      <p className="muted">Prioritizing what to check…</p>
                                    ) : null}
                                    {seniorAssist ? (
                                      <>
                                        <label className="field">
                                          <span>Review briefing</span>
                                          <textarea
                                            className="senior-ai-briefing-input"
                                            value={seniorAssist.briefing}
                                            onChange={(event) =>
                                              patchSeniorAssist({ briefing: event.target.value })
                                            }
                                            rows={3}
                                          />
                                        </label>
                                        <div className="senior-ai-focus-edit">
                                          <div className="senior-ai-assist-head">
                                            <span className="field-label">Focus queue</span>
                                            <button
                                              type="button"
                                              className="btn btn-ghost sm"
                                              onClick={addSeniorFocus}
                                            >
                                              Add item
                                            </button>
                                          </div>
                                          {seniorAssist.focus_items.length === 0 ? (
                                            <p className="muted">No focus items — add one if needed.</p>
                                          ) : (
                                            <ol className="senior-ai-focus">
                                              {seniorAssist.focus_items.map((item, index) => (
                                                <li key={`focus-${index}`}>
                                                  <div className="senior-ai-focus-row">
                                                    <select
                                                      aria-label="Severity"
                                                      value={item.severity}
                                                      onChange={(event) =>
                                                        patchSeniorFocus(index, {
                                                          severity: event.target.value,
                                                        })
                                                      }
                                                    >
                                                      <option value="high">high</option>
                                                      <option value="moderate">moderate</option>
                                                      <option value="low">low</option>
                                                    </select>
                                                    <button
                                                      type="button"
                                                      className="btn btn-ghost sm"
                                                      onClick={() => removeSeniorFocus(index)}
                                                    >
                                                      Remove
                                                    </button>
                                                  </div>
                                                  <input
                                                    type="text"
                                                    aria-label="Focus title"
                                                    value={item.title}
                                                    onChange={(event) =>
                                                      patchSeniorFocus(index, {
                                                        title: event.target.value,
                                                      })
                                                    }
                                                  />
                                                  <textarea
                                                    aria-label="Focus detail"
                                                    value={item.detail}
                                                    rows={2}
                                                    onChange={(event) =>
                                                      patchSeniorFocus(index, {
                                                        detail: event.target.value,
                                                      })
                                                    }
                                                  />
                                                </li>
                                              ))}
                                            </ol>
                                          )}
                                        </div>
                                        <fieldset className="senior-ai-action-field">
                                          <legend>Desk action (your call)</legend>
                                          <label className="choice">
                                            <input
                                              type="radio"
                                              name="senior-desk-action"
                                              checked={
                                                seniorAssist.recommended_desk_action ===
                                                "needs_documentation"
                                              }
                                              onChange={() =>
                                                setSeniorDeskAction("needs_documentation")
                                              }
                                            />
                                            Send back for more notes
                                          </label>
                                          <label className="choice">
                                            <input
                                              type="radio"
                                              name="senior-desk-action"
                                              checked={
                                                seniorAssist.recommended_desk_action ===
                                                "acknowledge_after_check"
                                              }
                                              onChange={() =>
                                                setSeniorDeskAction("acknowledge_after_check")
                                              }
                                            />
                                            Confirm checklist reviewed (after spot-check)
                                          </label>
                                          <p className="hint">
                                            {seniorAssist.source.startsWith("ai:")
                                              ? "Started from AI assist"
                                              : "Started from checklist"}
                                            {seniorAssistEdited ? " · you overrode it" : ""}
                                          </p>
                                        </fieldset>
                                      </>
                                    ) : null}
                                  </div>
                                  <label className="field">
                                    <span>Clinician note (editable)</span>
                                    <textarea
                                      value={resumeNotes}
                                      onChange={(event) => {
                                        setResumeNotes(event.target.value);
                                        setSeniorAssistEdited(true);
                                        setSeniorAssist((prev) =>
                                          prev
                                            ? {
                                                ...prev,
                                                suggested_clinician_note: event.target.value,
                                              }
                                            : prev,
                                        );
                                      }}
                                      rows={3}
                                      placeholder="What is still needed, or why you are closing this draft checklist…"
                                    />
                                  </label>
                                  <div className="home-actions">
                                    <button
                                      type="button"
                                      className={`btn ${
                                        seniorAssist?.recommended_desk_action ===
                                        "needs_documentation"
                                          ? "btn-primary"
                                          : "btn-ghost"
                                      }`}
                                      disabled={resumeBusy}
                                      onClick={() => completeHumanStep("needs_documentation")}
                                    >
                                      {resumeBusy ? "Saving…" : "Needs more notes"}
                                    </button>
                                    <button
                                      type="button"
                                      className={`btn ${
                                        seniorAssist?.recommended_desk_action ===
                                        "acknowledge_after_check"
                                          ? "btn-primary"
                                          : "btn-ghost"
                                      }`}
                                      disabled={resumeBusy}
                                      onClick={() => completeHumanStep("acknowledged")}
                                    >
                                      Confirm checklist reviewed
                                    </button>
                                  </div>
                                  <p className="hint">
                                    Your edited note and chosen desk action are what get recorded.
                                    Never an approval or denial.
                                  </p>
                                </>
                              ) : (
                                <p className="hint" role="status">
                                  Final confirmation needs a senior clinician sign-in.
                                </p>
                              )}
                            </div>
                          ) : (
                            <div className="home-actions">
                              <Link
                                className="btn btn-ghost"
                                to={`/visit?patient=${encodeURIComponent(review.patient_id)}`}
                              >
                                Add visit note
                              </Link>
                              <Link className="btn btn-ghost" to={`/patients/${review.patient_id}`}>
                                Open chart
                              </Link>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="review-next ok-next">
                          <h3 className="panel-title">Checklist looks complete</h3>
                          <p className="muted">
                            The chart covers the required checklist items for this review. Still not an
                            approval or denial — use the cited sources for your own judgment.
                          </p>
                          <div className="home-actions">
                            <Link className="btn btn-ghost" to={`/patients/${review.patient_id}`}>
                              Open chart
                            </Link>
                          </div>
                        </div>
                      )}

                      {review.report_summary ? (
                        <div className="review-summary">
                          <h3 className="panel-title">Summary</h3>
                          <p className="report-summary">
                            {deskFacingText(review.report_summary)}
                          </p>
                        </div>
                      ) : null}

                      {review.missing_evidence.length > 0 ? (
                        <div className="gap-actions">
                          <h3 className="panel-title">Open items to finish</h3>
                          <ul className="gap-list">
                            {review.missing_evidence.map((gap) => {
                              const action = gapFocus(gap);
                              return (
                                <li key={gap}>
                                  <span>{gap}</span>
                                  <Link
                                    className="btn btn-ghost sm"
                                    to={visitGapHref(
                                      review.patient_id,
                                      gap,
                                      review.policy_id,
                                    )}
                                  >
                                    {action.label}
                                  </Link>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    !busy && (
                      <p className="hint">
                        Run the checklist to match each item against this patient’s chart and
                        attach citations.
                      </p>
                    )
                  )}
                </div>

                <div className="panel">
                  <div className="review-checklist-head">
                    <h2 className="panel-title">
                      Insurance checklist
                      {policy ? <span className="muted"> · {policy.payer_name}</span> : null}
                    </h2>
                    {review ? (
                      <div className="mode-tabs" role="tablist" aria-label="Checklist filter">
                        <button
                          type="button"
                          className={`mode-tab ${focusFilter === "all" ? "active" : ""}`}
                          onClick={() => setFocusFilter("all")}
                        >
                          All
                        </button>
                        <button
                          type="button"
                          className={`mode-tab ${focusFilter === "gaps" ? "active" : ""}`}
                          onClick={() => setFocusFilter("gaps")}
                        >
                          Open items
                        </button>
                      </div>
                    ) : null}
                  </div>

                  {!policy && !review ? (
                    <p className="muted">Loading checklist…</p>
                  ) : visibleChecklist.length === 0 ? (
                    <p className="muted">No open checklist items for this case.</p>
                  ) : (
                    <ol className="review-checklist">
                      {visibleChecklist.map((row, index) => (
                        <li className="criterion-card" key={row.criterion_id}>
                          <div className="criterion-card-head">
                            <span className="criterion-index">{index + 1}</span>
                            <div className="criterion-main">
                              <h3>
                                <span className={`status ${statusTone(row.status)}`}>
                                  {statusPlain(row.status)}
                                </span>{" "}
                                {row.criterion}
                              </h3>
                              {row.reason ? (
                                <p className="muted">{deskFacingText(row.reason)}</p>
                              ) : null}
                            </div>
                          </div>

                          {row.evidence.length > 0 ? (
                            <ul className="citations">
                              <li className="citation-legend muted">
                                Chart citations used for this checklist item
                              </li>
                              {row.evidence.map((item) => (
                                <li
                                  key={`${item.document_id}-${item.chunk_id}-${item.text_reference}`}
                                >
                                  <p className="citation-source">
                                    {sourceLabel(item.source, item.document_id)}
                                  </p>
                                  <pre className="note">{item.text_reference}</pre>
                                  <button
                                    type="button"
                                    className="btn btn-ghost sm"
                                    onClick={() => openSource(item.document_id)}
                                    disabled={sourceBusy}
                                  >
                                    {sourceBusy ? "Loading…" : "View source"}
                                  </button>
                                </li>
                              ))}
                            </ul>
                          ) : review ? (
                            <p className="muted citation-empty">No citation attached.</p>
                          ) : null}

                          {review?.evidence_panel?.some(
                            (item) => String(item.criterion_id) === row.criterion_id,
                          ) ? (
                            <details className="retrieved-context">
                              <summary>More chart excerpts for context</summary>
                              <ul className="citations">
                                {review.evidence_panel
                                  .filter((item) => String(item.criterion_id) === row.criterion_id)
                                  .map((item) => (
                                    <li key={`${item.document_id}-${item.chunk_id}`}>
                                      <p className="citation-source">
                                        {documentTypeLabel("clinical_note")} excerpt
                                      </p>
                                      <pre className="note">{String(item.content || "")}</pre>
                                    </li>
                                  ))}
                              </ul>
                            </details>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>

                {review?.contradictions.length ? (
                  <div className="panel warn-panel">
                    <h2 className="panel-title">Conflicting chart notes</h2>
                    <p className="hint">
                      Conflicting evidence was found. Resolve in the chart or escalate for clinician
                      review.
                    </p>
                    {review.contradictions.map((item) => (
                      <article key={item.criterion} className="criterion">
                        <h4>{item.criterion}</h4>
                        <p className="muted">{item.description}</p>
                        {item.evidence_a ? <pre className="note">A: {item.evidence_a}</pre> : null}
                        {item.evidence_b ? <pre className="note">B: {item.evidence_b}</pre> : null}
                      </article>
                    ))}
                  </div>
                ) : null}

                {source ? (
                  <div className="panel source-panel" aria-live="polite">
                    <div className="review-checklist-head">
                      <h2 className="panel-title">
                        Source · {documentTypeLabel(source.document_type)}
                      </h2>
                      <button
                        type="button"
                        className="btn btn-ghost sm"
                        onClick={() => setSource(null)}
                      >
                        Close
                      </button>
                    </div>
                    <pre className="note source-body">{source.content}</pre>
                  </div>
                ) : null}

                {review ? <p className="disclaimer">{review.disclaimer}</p> : null}
              </>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
