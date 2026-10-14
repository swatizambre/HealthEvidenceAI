import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getCases, resumeReview, seniorReviewAssist, type AuthCase } from "../api";
import { Checklist } from "../components/CaseParts";
import {
  PAYER_LABEL,
  deskErrorMessage,
  getCaseWorkspace,
  getDeskWorklist,
  isEndpointMissing,
  type CaseWorkspace,
  type WorklistItem,
} from "../deskApi";
import { formatLiveAge, useLiveRefresh } from "../hooks/useLiveRefresh";
import { procedureDisplayName } from "../labels";
import { useRole } from "../roleContext";
import {
  Button,
  ButtonLink,
  EmptyState,
  Icon,
  Money,
  Notice,
  ReadinessMeter,
  ReviewPill,
  Skeleton,
  StagePill,
  StatusPill,
  Tabs,
  ageSex,
  useToast,
} from "../ui";

type Filter = "awaiting" | "sent_back" | "open";

const FILTER_MATCH: Record<Filter, (item: AuthCase) => boolean> = {
  awaiting: (item) => item.status === "ready_for_human",
  sent_back: (item) => item.status === "needs_documentation",
  open: (item) => item.status !== "closed_as_draft",
};

export function ReviewsPage() {
  const { canAdjudicate } = useRole();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("case") || "";
  const filterParam = searchParams.get("queue");
  const filter: Filter = filterParam === "sent_back" || filterParam === "open" ? filterParam : "awaiting";

  const [cases, setCases] = useState<AuthCase[] | null>(null);
  const [desk, setDesk] = useState<Map<string, WorklistItem>>(new Map());
  const [listError, setListError] = useState("");
  const [ws, setWs] = useState<CaseWorkspace | null>(null);
  const [wsError, setWsError] = useState<{ message: string; missing: boolean } | null>(null);
  const [notes, setNotes] = useState("");
  const [deciding, setDeciding] = useState<"acknowledged" | "needs_documentation" | null>(null);
  const [assistBusy, setAssistBusy] = useState(false);

  const loadList = useCallback(async () => {
    try {
      const [legacy, worklist] = await Promise.all([
        getCases(),
        getDeskWorklist({ limit: 200 }).catch(() => null),
      ]);
      setCases(legacy.cases);
      if (worklist) {
        setDesk(new Map(worklist.items.map((item) => [item.case_id, item])));
      }
      setListError("");
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Could not load cases.");
    }
  }, []);

  const { lastUpdatedAt, refreshNow, pushConnected } = useLiveRefresh(loadList, {
    intervalMs: 60_000,
    enabled: deciding === null,
  });

  const visible = useMemo(() => (cases ?? []).filter(FILTER_MATCH[filter]), [cases, filter]);
  const counts = useMemo(
    () => ({
      awaiting: (cases ?? []).filter(FILTER_MATCH.awaiting).length,
      sent_back: (cases ?? []).filter(FILTER_MATCH.sent_back).length,
      open: (cases ?? []).filter(FILTER_MATCH.open).length,
    }),
    [cases],
  );
  const selected = (cases ?? []).find((item) => item.case_id === selectedId) ?? null;

  const select = useCallback(
    (caseId: string, nextFilter: Filter = filter) => {
      const params = new URLSearchParams(searchParams);
      if (caseId) params.set("case", caseId);
      else params.delete("case");
      if (nextFilter === "awaiting") params.delete("queue");
      else params.set("queue", nextFilter);
      setSearchParams(params, { replace: true });
    },
    [filter, searchParams, setSearchParams],
  );

  // Open the first case in the queue when nothing is selected (desktop reading order).
  useEffect(() => {
    if (!selectedId && visible.length > 0 && window.matchMedia("(min-width: 960px)").matches) {
      select(visible[0].case_id);
    }
  }, [selectedId, visible, select]);

  const loadWorkspace = useCallback(async (caseId: string) => {
    setWs(null);
    setWsError(null);
    try {
      setWs(await getCaseWorkspace(caseId));
    } catch (err) {
      setWsError({ message: deskErrorMessage(err, "Could not load this case."), missing: isEndpointMissing(err) });
    }
  }, []);

  useEffect(() => {
    setNotes("");
    if (selectedId) {
      void loadWorkspace(selectedId);
    } else {
      setWs(null);
      setWsError(null);
    }
  }, [selectedId, loadWorkspace]);

  const runId = ws?.review.run_id || selected?.last_run_id || "";
  const awaiting = ws ? ws.review.state === "awaiting_senior" : selected?.status === "ready_for_human";
  const openRequired = ws ? ws.checklist.filter((item) => item.required && item.status !== "SUPPORTED").length : 0;

  async function decide(decision: "acknowledged" | "needs_documentation") {
    if (!runId) return;
    if (decision === "needs_documentation" && notes.trim().length < 3) {
      toast.show("Add a note saying what is still needed before sending back.", "danger");
      return;
    }
    setDeciding(decision);
    try {
      await resumeReview(runId, { decision, notes: notes.trim() });
      toast.show(decision === "acknowledged" ? "Checklist confirmed" : "Sent back to the desk", "success");
      const remaining = visible.filter((item) => item.case_id !== selectedId);
      await loadList();
      setNotes("");
      select(remaining[0]?.case_id ?? "");
    } catch (err) {
      toast.show(err instanceof Error ? err.message : "Could not record your decision.", "danger");
    } finally {
      setDeciding(null);
    }
  }

  async function draftNote() {
    if (!ws) return;
    setAssistBusy(true);
    try {
      const assist = await seniorReviewAssist({
        patient_id: ws.patient.patient_id,
        case_id: ws.case.case_id,
        procedure: ws.case.proposed_treatment,
        criteria: ws.checklist.map((item) => ({ criterion: item.label, status: item.status, reason: item.reason })),
        missing_evidence: ws.checklist.filter((item) => item.status !== "SUPPORTED").map((item) => item.label),
      });
      setNotes(assist.suggested_clinician_note || assist.briefing);
    } catch (err) {
      toast.show(err instanceof Error ? err.message : "Could not draft a note.", "danger");
    } finally {
      setAssistBusy(false);
    }
  }

  return (
    <section className="page page-wide">
      <header className="page-head">
        <div>
          <h1 className="page-title">Reviews</h1>
          <p className="page-sub">
            Confirm each checklist against the cited chart excerpts, or send it back with a note. Confirming is not an
            insurance approval.
            <span className="live-stamp">
              {formatLiveAge(lastUpdatedAt, pushConnected)}
              <button type="button" className="text-link" onClick={refreshNow}>
                Refresh
              </button>
            </span>
          </p>
        </div>
      </header>

      <div className="review-layout">
        <aside className="review-queue" aria-label="Review queue">
          <Tabs
            items={[
              { id: "awaiting", label: "Awaiting senior", count: cases ? counts.awaiting : undefined },
              { id: "sent_back", label: "Sent back", count: cases ? counts.sent_back : undefined },
              { id: "open", label: "All", count: cases ? counts.open : undefined },
            ]}
            active={filter}
            onChange={(id) => select("", id)}
            label="Review queue filter"
            idPrefix="review"
          />
          <div id="review-panel" role="tabpanel" aria-labelledby={`review-tab-${filter}`}>
            {listError ? <Notice tone="danger" title="Could not load cases">{listError}</Notice> : null}
            {!cases && !listError ? <Skeleton lines={5} label="Loading review queue" /> : null}
            {cases && visible.length === 0 ? (
              <EmptyState icon="check" title={filter === "awaiting" ? "Nothing waiting for you" : "No cases here"}>
                {filter === "awaiting"
                  ? "Cases appear here when the desk sends a checklist for senior review."
                  : "Try another filter."}
              </EmptyState>
            ) : null}
            {visible.length > 0 ? (
              <ul className="queue-list">
                {visible.map((item) => {
                  const enriched = desk.get(item.case_id);
                  const active = item.case_id === selectedId;
                  return (
                    <li key={item.case_id}>
                      <button
                        type="button"
                        className={`queue-item${active ? " is-active" : ""}`}
                        aria-current={active ? "true" : undefined}
                        onClick={() => select(item.case_id)}
                      >
                        <span className="queue-item-top">
                          <strong>{enriched?.patient_name || item.patient_id}</strong>
                          {enriched ? <span className="num muted small">{Math.round(enriched.readiness_percent)}%</span> : null}
                        </span>
                        <span className="queue-item-sub">
                          {enriched?.proposed_treatment || procedureDisplayName(item.procedure)}
                        </span>
                        <span className="queue-item-sub muted">
                          {item.case_id}
                          {enriched?.insurer_name ? `, ${enriched.insurer_name}` : ""}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        </aside>

        <div className="review-detail">
          {!selectedId ? (
            <EmptyState icon="folder" title="Select a case">
              Pick a case from the queue to see its checklist and cited chart excerpts.
            </EmptyState>
          ) : wsError ? (
            <>
              <Notice tone={wsError.missing ? "warning" : "danger"} title="Checklist not available">
                {wsError.message}
              </Notice>
              {selected ? (
                <p className="muted">
                  Case {selected.case_id} for{" "}
                  <Link to={`/patients/${encodeURIComponent(selected.patient_id)}`}>{selected.patient_id}</Link>.
                </p>
              ) : null}
            </>
          ) : !ws ? (
            <Skeleton lines={8} label="Loading case" />
          ) : (
            <article className="review-case" aria-label={`Case ${ws.case.case_id}`}>
              <header className="review-case-head">
                <div>
                  <h2 className="section-title">{ws.patient.name}</h2>
                  <p className="case-meta">
                    <span>{ws.patient.mrn ? `MRN ${ws.patient.mrn}` : ws.patient.patient_id}</span>
                    <span>{ageSex(ws.patient.age, ws.patient.sex)}</span>
                    <span>{ws.case.case_id}</span>
                  </p>
                  <p className="review-case-facts">
                    <strong>{ws.case.proposed_treatment || "Treatment not recorded"}</strong>
                    {ws.case.provisional_diagnosis ? `, for ${ws.case.provisional_diagnosis}` : ""}
                    {ws.case.icd10_code ? ` (${ws.case.icd10_code})` : ""}
                  </p>
                  <p className="muted small">
                    {ws.case.insurer_name || PAYER_LABEL[ws.case.payer_type]}
                    {ws.case.tpa_name ? ` via ${ws.case.tpa_name}` : ""}
                    {ws.case.estimated_cost_inr != null ? (
                      <>
                        , estimate <Money value={ws.case.estimated_cost_inr} />
                      </>
                    ) : null}
                  </p>
                </div>
                <div className="review-case-status">
                  <StagePill stage={ws.case.stage} fallbackLabel={ws.case.stage_label} />
                  <ReviewPill state={ws.review.state} />
                  <ButtonLink size="sm" variant="ghost" to={`/cases/${encodeURIComponent(ws.case.case_id)}`}>
                    Open case
                  </ButtonLink>
                </div>
              </header>

              <ReadinessMeter
                percent={ws.readiness.percent}
                label={`${ws.readiness.supported} of ${ws.readiness.required} required items supported${ws.readiness.label ? `, ${ws.readiness.label}` : ""}`}
              />

              <section className="decision" aria-labelledby="decision-title">
                <div className="decision-head">
                  <h3 className="section-title" id="decision-title">
                    Your decision
                  </h3>
                  {awaiting && openRequired > 0 ? (
                    <StatusPill
                      tone="warning"
                      label={`${openRequired} required item${openRequired === 1 ? "" : "s"} not supported`}
                    />
                  ) : null}
                </div>
                {!awaiting ? (
                  <p className="muted">
                    This case is not waiting for senior review
                    {ws.review.by_label ? ` (last: ${ws.review.by_label})` : ""}.
                  </p>
                ) : !canAdjudicate ? (
                  <Notice tone="info">Confirmation needs a consultant or senior MO sign-in.</Notice>
                ) : !runId ? (
                  <Notice tone="warning">
                    No paused review is attached to this case. Ask the desk to send it for senior review again.
                  </Notice>
                ) : (
                  <div className="decision-body">
                    <label className="field decision-note">
                      <span>Note to the desk</span>
                      <textarea
                        rows={2}
                        value={notes}
                        onChange={(event) => setNotes(event.target.value)}
                        placeholder="Required when sending back: say what is missing."
                      />
                    </label>
                    <div className="button-row decision-buttons">
                      <Button size="sm" variant="ghost" loading={assistBusy} onClick={() => void draftNote()}>
                        Draft note
                      </Button>
                      <Button
                        icon="arrow-right"
                        loading={deciding === "needs_documentation"}
                        disabled={deciding !== null}
                        onClick={() => void decide("needs_documentation")}
                      >
                        Send back
                      </Button>
                      <Button
                        variant="primary"
                        icon="check"
                        loading={deciding === "acknowledged"}
                        disabled={deciding !== null}
                        onClick={() => void decide("acknowledged")}
                      >
                        Acknowledge
                      </Button>
                    </div>
                  </div>
                )}
                {awaiting && canAdjudicate && runId ? (
                  <p className="muted small">
                    <Icon name="info" size={12} /> Acknowledging confirms the checklist matches the chart. It is not an
                    approval or denial of care.
                  </p>
                ) : null}
              </section>

              <Checklist items={ws.checklist} />

            </article>
          )}
        </div>
      </div>
    </section>
  );
}
