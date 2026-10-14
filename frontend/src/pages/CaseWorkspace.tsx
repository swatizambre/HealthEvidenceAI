import { FormEvent, useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { getCases, reviewCase } from "../api";
import { Checklist, Citations, ILLUSTRATIVE_NOTE, StageStepper } from "../components/CaseParts";
import {
  PAYER_LABEL,
  deskErrorMessage,
  getCaseWorkspace,
  getDischargeCheck,
  getPreauthForm,
  isEndpointMissing,
  maskPolicy,
  patchCase,
  postStageAction,
  type AdmissionType,
  type CaseEditable,
  type CaseWorkspace,
  type ChecklistOpenItem,
  type DeskCitation,
  type DischargeCheck,
  type DischargeFinding,
  type FindingSeverity,
  type PayerType,
  type PreauthField,
  type PreauthForm,
  type StageAction,
} from "../deskApi";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { documentTypeLabel } from "../labels";
import { useRole } from "../roleContext";
import {
  Button,
  ButtonLink,
  ClockChip,
  Drawer,
  EmptyState,
  Icon,
  Money,
  Notice,
  ReadinessMeter,
  ReviewPill,
  SeverityPill,
  Skeleton,
  StagePill,
  StatusPill,
  Tabs,
  ageSex,
  clockState,
  formatDate,
  formatDateTime,
  formatDateTimeLong,
  humanize,
  useNow,
  useToast,
  type ButtonVariant,
  type IconName,
} from "../ui";

type TabId = "checklist" | "form" | "queries" | "discharge" | "timeline";
const TAB_IDS: TabId[] = ["checklist", "form", "queries", "discharge", "timeline"];

/** Drawers collect details; dialogs confirm irreversible steps with a summary. */
type StageKind =
  | "record_query"
  | "answer_query"
  | "request_enhancement"
  | "record_approval"
  | "mark_sent"
  | "mark_discharge_sent"
  | "close";

type DrawerKind = "edit" | StageKind;

const CONFIRM_KINDS: ReadonlySet<StageKind> = new Set<StageKind>([
  "record_approval",
  "mark_sent",
  "mark_discharge_sent",
  "close",
]);

type ActionId =
  | "send_for_review"
  | "mark_sent"
  | "record_query"
  | "answer_query"
  | "record_approval"
  | "request_enhancement"
  | "start_discharge"
  | "run_discharge_check"
  | "mark_discharge_sent"
  | "close";

type ActionSpec = { id: ActionId; label: string; icon: IconName; variant?: ButtonVariant };

type NextActions = { primary: ActionSpec | null; secondary: ActionSpec[]; note: string };

function blockerCount(discharge: DischargeCheck | null): number {
  return discharge ? discharge.findings.filter((finding) => finding.severity === "blocker").length : 0;
}

/** Only stage-appropriate actions; every irreversible one opens a confirm dialog ("…"). */
function nextActions(ws: CaseWorkspace, discharge: DischargeCheck | null): NextActions {
  const { stage } = ws.case;
  const review = ws.review.state;
  const openQuery = ws.queries.some((query) => !query.responded_at);
  const recordApproval: ActionSpec = { id: "record_approval", label: "Record approval…", icon: "check" };
  const recordQuery: ActionSpec = { id: "record_query", label: "Record query", icon: "question" };
  const answerQuery: ActionSpec = { id: "answer_query", label: "Answer query", icon: "edit" };
  const markSent: ActionSpec = { id: "mark_sent", label: "Mark sent to TPA…", icon: "send" };
  switch (stage) {
    case "draft":
      if (review === "awaiting_senior") {
        return { primary: null, secondary: [], note: "Waiting for a consultant to confirm the checklist." };
      }
      if (review === "acknowledged") {
        return {
          primary: markSent,
          secondary: [],
          note: "Senior confirmed. Send through the insurer/TPA portal, then record it here.",
        };
      }
      return {
        primary: { id: "send_for_review", label: "Send for senior review", icon: "check" },
        secondary: [],
        note:
          review === "needs_documentation"
            ? "Sent back for more documentation. Fix the open items, then send again."
            : "Close the open checklist items, then send for a consultant to confirm.",
      };
    case "ready_to_send":
      return {
        primary: markSent,
        secondary: [],
        note: "Send through the insurer/TPA portal, then record it here to start the 1-hour clock.",
      };
    case "sent":
    case "enhancement":
    case "query":
      if (openQuery) {
        return {
          primary: answerQuery,
          secondary: [],
          note: "The TPA raised a query. Answer it before the response clock runs out; record the decision after.",
        };
      }
      return {
        primary: recordApproval,
        secondary: [recordQuery],
        note:
          stage === "enhancement"
            ? "Enhancement requested. Record the revised approved amount when it arrives."
            : stage === "query"
              ? "Query answered. Waiting for the TPA decision."
              : "Waiting for the insurer/TPA decision.",
      };
    case "approved":
      return {
        primary: { id: "start_discharge", label: "Start discharge", icon: "doc" },
        secondary: [{ id: "request_enhancement", label: "Request enhancement", icon: "alert" }],
        note: "Approved. Request an enhancement if costs will exceed the approved amount.",
      };
    case "discharge_pending": {
      if (!discharge) {
        return {
          primary: { id: "run_discharge_check", label: "Run discharge check", icon: "check" },
          secondary: [],
          note: "Check the discharge summary and final bill against the pre-auth before sending.",
        };
      }
      const blockers = blockerCount(discharge);
      if (blockers > 0) {
        return {
          primary: { id: "mark_discharge_sent", label: "Send with override…", icon: "alert", variant: "danger" },
          secondary: [{ id: "run_discharge_check", label: "Re-run check", icon: "check" }],
          note: `The discharge check found ${blockers} blocker${blockers === 1 ? "" : "s"}. Fix and re-run the check, or send with a recorded override reason.`,
        };
      }
      return {
        primary: { id: "mark_discharge_sent", label: "Mark discharge sent…", icon: "send" },
        secondary: [],
        note: "Discharge check passed. Send the final request, then record it here.",
      };
    }
    case "discharge_sent":
      return {
        primary: { id: "close", label: "Close case…", icon: "check" },
        secondary: [],
        note: "Waiting for final approval (IRDAI: 3 hours).",
      };
    case "closed":
      return { primary: null, secondary: [], note: "This case is closed." };
    default: {
      const never: never = stage;
      return { primary: null, secondary: [], note: String(never) };
    }
  }
}

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function parseAmount(value: string): number | null {
  const digits = value.replace(/[^\d]/g, "");
  return digits ? Number(digits) : null;
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function openChecklistItems(ws: CaseWorkspace): ChecklistOpenItem[] {
  return ws.checklist
    .filter((item) => item.required && item.status !== "SUPPORTED" && item.group !== "form")
    .map((item) => ({ item_id: item.item_id, label: item.label, group: item.group, status: item.status }));
}

/** One next-step line in the case header when a clock has run out. */
function overdueMessage(ws: CaseWorkspace, discharge: DischargeCheck | null, now: number): string {
  if (!clockState(ws.case.clock, now).overdue) return "";
  switch (ws.case.stage) {
    case "discharge_pending":
      if (!discharge) return "Discharge request overdue — run discharge check and send";
      return blockerCount(discharge) > 0
        ? "Discharge request overdue — fix the blockers or send with an override reason"
        : "Discharge request overdue — send the discharge request now";
    case "query":
      return "Query reply overdue — answer the TPA query now";
    case "draft":
    case "ready_to_send":
      return ws.review.state === "awaiting_senior"
        ? "Preparation overdue — waiting for senior confirmation"
        : "Preparation overdue — send the pre-auth request";
    default:
      return "";
  }
}

export function CaseWorkspacePage() {
  const { caseId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { canCheckEvidence, canAdjudicate } = useRole();
  const toast = useToast();
  const now = useNow(30_000);

  const tabParam = searchParams.get("tab") || "";
  const tab: TabId = (TAB_IDS as string[]).includes(tabParam) ? (tabParam as TabId) : "checklist";

  const [ws, setWs] = useState<CaseWorkspace | null>(null);
  const [loadError, setLoadError] = useState<{ message: string; missing: boolean } | null>(null);
  const [form, setForm] = useState<PreauthForm | null>(null);
  const [formError, setFormError] = useState("");
  const [discharge, setDischarge] = useState<DischargeCheck | null>(null);
  const [dischargeError, setDischargeError] = useState("");
  const [dischargeBusy, setDischargeBusy] = useState(false);
  const [busy, setBusy] = useState<ActionId | "save" | null>(null);
  const [drawer, setDrawer] = useState<DrawerKind | null>(null);
  const [drawerError, setDrawerError] = useState("");

  const load = useCallback(async () => {
    try {
      const body = await getCaseWorkspace(caseId);
      setWs(body);
      setLoadError(null);
    } catch (err) {
      setLoadError({ message: deskErrorMessage(err, "Could not open this case."), missing: isEndpointMissing(err) });
    }
  }, [caseId]);

  useLiveRefresh(load, { intervalMs: 60_000, enabled: drawer === null && busy === null });

  useEffect(() => {
    setWs(null);
    setForm(null);
    setDischarge(null);
    setLoadError(null);
    void load();
  }, [load]);

  useEffect(() => {
    if (tab !== "form" || form) return;
    let cancelled = false;
    setFormError("");
    getPreauthForm(caseId)
      .then((body) => {
        if (!cancelled) setForm(body);
      })
      .catch((err: unknown) => {
        if (!cancelled) setFormError(deskErrorMessage(err, "Could not load the pre-auth form."));
      });
    return () => {
      cancelled = true;
    };
  }, [tab, form, caseId]);

  const runDischargeCheck = useCallback(async () => {
    setDischargeBusy(true);
    setDischargeError("");
    try {
      setDischarge(await getDischargeCheck(caseId));
    } catch (err) {
      setDischargeError(deskErrorMessage(err, "Could not run the discharge check."));
    } finally {
      setDischargeBusy(false);
    }
  }, [caseId]);

  useEffect(() => {
    if (tab === "discharge" && !discharge && !dischargeBusy && !dischargeError) {
      void runDischargeCheck();
    }
  }, [tab, discharge, dischargeBusy, dischargeError, runDischargeCheck]);

  function setTab(next: TabId) {
    const params = new URLSearchParams(searchParams);
    if (next === "checklist") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  function openDrawer(kind: DrawerKind) {
    setDrawerError("");
    setDrawer(kind);
  }

  async function applyStage(body: StageAction, success: string): Promise<boolean> {
    setDrawerError("");
    try {
      const next = await postStageAction(caseId, body);
      setWs(next);
      setForm(null);
      toast.show(success, "success");
      return true;
    } catch (err) {
      const message = deskErrorMessage(err, "Could not update the case.");
      if (drawer) setDrawerError(message);
      else toast.show(message, "danger");
      return false;
    }
  }

  async function sendForReview() {
    if (!ws) return;
    let policyId = ws.case.policy_id || "";
    let procedure = ws.case.procedure || ws.case.proposed_treatment;
    if (!policyId) {
      const legacy = await getCases();
      const match = legacy.cases.find((item) => item.case_id === ws.case.case_id);
      policyId = match?.policy_id || "";
      procedure = match?.procedure || procedure;
    }
    if (!policyId) {
      throw new Error("This case has no checklist linked yet, so it cannot be sent for review.");
    }
    await reviewCase({
      patient_id: ws.patient.patient_id,
      policy_id: policyId,
      procedure,
      case_id: ws.case.case_id,
      interactive: true,
    });
    await load();
    toast.show("Sent for senior review", "success");
  }

  async function runAction(id: ActionId) {
    if (!ws) return;
    switch (id) {
      case "record_query":
      case "answer_query":
      case "record_approval":
      case "request_enhancement":
      case "mark_sent":
      case "mark_discharge_sent":
      case "close":
        openDrawer(id);
        if (id === "answer_query") setTab("queries");
        if (id === "mark_discharge_sent") setTab("discharge");
        return;
      case "run_discharge_check":
        setTab("discharge");
        setDischarge(null);
        setDischargeError("");
        await runDischargeCheck();
        return;
      case "send_for_review":
        setBusy(id);
        try {
          await sendForReview();
        } catch (err) {
          toast.show(err instanceof Error ? err.message : "Could not send for review.", "danger");
        } finally {
          setBusy(null);
        }
        return;
      case "start_discharge":
        setBusy(id);
        await applyStage({ action: "start_discharge" }, "Discharge started");
        setBusy(null);
        return;
      default: {
        const never: never = id;
        return never;
      }
    }
  }

  if (loadError && !ws) {
    return (
      <section className="page">
        <Breadcrumb caseId={caseId} />
        <Notice
          tone={loadError.missing ? "warning" : "danger"}
          title={loadError.missing ? "Case workspace not available yet" : "Could not open this case"}
          action={
            <Button size="sm" onClick={() => void load()}>
              Try again
            </Button>
          }
        >
          {loadError.message}
        </Notice>
      </section>
    );
  }

  if (!ws) {
    return (
      <section className="page">
        <Breadcrumb caseId={caseId} />
        <Skeleton lines={6} label="Loading case" />
      </section>
    );
  }

  const c = ws.case;
  const actions = nextActions(ws, discharge);
  const openQueries = ws.queries.filter((query) => !query.responded_at);
  const readinessDetail = `${ws.readiness.supported} of ${ws.readiness.required} required items supported`;
  const primaryAllowed =
    actions.primary && (actions.primary.id !== "send_for_review" || canCheckEvidence);
  const checklistOpen = ws.readiness.missing + ws.readiness.unknown + ws.readiness.not_supported;
  const overdue = overdueMessage(ws, discharge, now);

  return (
    <section className="page case-page">
      <Breadcrumb caseId={c.case_id} />

      <header className="case-head">
        <div className="case-identity">
          <h1 className="page-title">{ws.patient.name}</h1>
          <p className="case-meta">
            <span>{ws.patient.mrn ? `MRN ${ws.patient.mrn}` : ws.patient.patient_id}</span>
            <span>{ageSex(ws.patient.age, ws.patient.sex)}</span>
            <Link to={`/patients/${encodeURIComponent(ws.patient.patient_id)}`}>Open chart</Link>
          </p>
        </div>
        <div className="case-head-status">
          <StagePill stage={c.stage} fallbackLabel={c.stage_label} />
          <ClockChip clock={c.clock} size="lg" showLabel />
        </div>
      </header>

      {overdue ? (
        <Notice tone="danger" title={overdue}>
          <span className="sr-only">Next step. </span>
          {actions.primary && primaryAllowed ? `Use “${actions.primary.label.replace(/…$/, "")}” below.` : null}
        </Notice>
      ) : null}

      <div className="case-summary">
        <dl className="facts">
          <Fact label="Treatment">{c.proposed_treatment || <span className="missing-text">Not recorded</span>}</Fact>
          <Fact label="Provisional diagnosis">
            {c.provisional_diagnosis || <span className="missing-text">Not recorded</span>}
            {c.icd10_code ? <span className="code"> {c.icd10_code}</span> : null}
          </Fact>
          <Fact label="Insurer / TPA">
            {c.insurer_name || PAYER_LABEL[c.payer_type]}
            {c.tpa_name ? <span className="muted"> via {c.tpa_name}</span> : null}
          </Fact>
          <Fact label="Policy">{maskPolicy(c.policy_number) || <span className="missing-text">Not recorded</span>}</Fact>
          <Fact label="Admission">
            {c.admission_type === "emergency" ? "Emergency" : "Planned"}
            {c.admitted_at ? <span className="muted">, {formatDateTime(c.admitted_at)}</span> : null}
          </Fact>
          <Fact label="Treating doctor">{c.treating_doctor || <span className="missing-text">Not recorded</span>}</Fact>
          <Fact label="Estimate">
            <Money value={c.estimated_cost_inr} />
          </Fact>
          <Fact label="Approved">
            <Money value={c.approved_amount_inr} />
          </Fact>
        </dl>
        <Button size="sm" variant="ghost" icon="edit" className="no-print" onClick={() => openDrawer("edit")}>
          Edit details
        </Button>
      </div>

      <div className="no-print">
        <StageStepper stage={c.stage} hadQuery={ws.queries.length > 0} />
      </div>

      <div className="action-bar no-print">
        <div className="action-bar-readiness">
          <ReadinessMeter percent={ws.readiness.percent} label={ws.readiness.label} size="lg" />
          <p className="muted small">{readinessDetail}</p>
        </div>
        <div className="action-bar-review">
          <ReviewPill state={ws.review.state} />
          {ws.review.by_label ? (
            <p className="muted small">
              {ws.review.by_label}
              {ws.review.at ? `, ${formatDateTime(ws.review.at)}` : ""}
            </p>
          ) : null}
        </div>
        <div className="action-bar-next">
          <p className="next-note">{actions.note}</p>
          <div className="button-row">
            {actions.secondary.map((action) => (
              <Button
                key={action.id}
                icon={action.icon}
                loading={busy === action.id || (action.id === "run_discharge_check" && dischargeBusy)}
                onClick={() => void runAction(action.id)}
              >
                {action.label}
              </Button>
            ))}
            {actions.primary && primaryAllowed ? (
              <Button
                variant={actions.primary.variant ?? "primary"}
                icon={actions.primary.icon}
                loading={busy === actions.primary.id || (actions.primary.id === "run_discharge_check" && dischargeBusy)}
                onClick={() => {
                  if (actions.primary) void runAction(actions.primary.id);
                }}
              >
                {actions.primary.label}
              </Button>
            ) : null}
            {ws.review.state === "awaiting_senior" && canAdjudicate ? (
              <ButtonLink variant="primary" icon="check" to={`/reviews?case=${encodeURIComponent(c.case_id)}`}>
                Review now
              </ButtonLink>
            ) : null}
          </div>
        </div>
      </div>

      {c.stage === "draft" && ws.review.state === "needs_documentation" && ws.review.notes ? (
        <Notice tone="warning" title={`Sent back${ws.review.by_label ? ` by ${ws.review.by_label}` : ""}`}>
          {ws.review.notes}
        </Notice>
      ) : null}

      <div className="no-print">
        <Tabs
          items={[
            { id: "checklist", label: checklistOpen > 0 ? `Checklist · ${checklistOpen} open` : "Checklist ✓" },
            { id: "form", label: "Pre-auth form" },
            { id: "queries", label: "Queries", count: openQueries.length > 0 ? openQueries.length : undefined },
            { id: "discharge", label: "Discharge check" },
            { id: "timeline", label: "Timeline" },
          ]}
          active={tab}
          onChange={setTab}
          label="Case sections"
          idPrefix="case"
        />
      </div>

      <div id="case-panel" role="tabpanel" aria-labelledby={`case-tab-${tab}`} className="tab-panel">
        {tab === "checklist" ? (
          <Checklist
            items={ws.checklist}
            actions={{
              patientId: ws.patient.patient_id,
              caseId: c.case_id,
              policyId: c.policy_id,
              onEditCase: () => openDrawer("edit"),
            }}
          />
        ) : null}
        {tab === "form" ? (
          <PreauthPanel
            form={form}
            error={formError}
            checklistOpen={form?.checklist_open ?? openChecklistItems(ws)}
            onOpenChecklist={() => setTab("checklist")}
          />
        ) : null}
        {tab === "queries" ? (
          <QueriesPanel
            ws={ws}
            onRecord={() => openDrawer("record_query")}
            onAnswer={() => openDrawer("answer_query")}
          />
        ) : null}
        {tab === "discharge" ? (
          <DischargePanel
            check={discharge}
            error={dischargeError}
            busy={dischargeBusy}
            onRun={() => {
              setDischarge(null);
              setDischargeError("");
              void runDischargeCheck();
            }}
          />
        ) : null}
        {tab === "timeline" ? <TimelinePanel ws={ws} /> : null}
      </div>

      <EditDrawer
        open={drawer === "edit"}
        ws={ws}
        onClose={() => setDrawer(null)}
        onSaved={(next) => {
          setWs(next);
          setForm(null);
          setDrawer(null);
          toast.show("Case details saved", "success");
        }}
      />
      <StageDrawer
        kind={drawer === "edit" ? null : drawer}
        ws={ws}
        discharge={discharge}
        error={drawerError}
        onClose={() => setDrawer(null)}
        onSubmit={async (body, success) => {
          const ok = await applyStage(body, success);
          if (ok) setDrawer(null);
        }}
      />
    </section>
  );
}

function Breadcrumb({ caseId }: { caseId: string }) {
  return (
    <nav className="breadcrumb no-print" aria-label="Breadcrumb">
      <Link to="/cases">Cases</Link>
      <Icon name="arrow-right" size={12} />
      <span aria-current="page">{caseId}</span>
    </nav>
  );
}

/** Raw API values → what a TPA form shows ("15 Oct 2026, 08:54", "Male", "TPA", "Planned"). */
function displayValue(field: PreauthField): string {
  const value = field.value ?? "";
  const keepIfUnparsed = (formatted: string) => (formatted === "—" ? value : formatted);
  switch (field.key) {
    case "admitted_at":
      return keepIfUnparsed(formatDateTimeLong(value));
    case "date_of_birth":
    case "expected_delivery_date":
    case "injury_date":
      return keepIfUnparsed(formatDate(value));
    case "sex":
    case "admission_type":
    case "room_type":
      return humanize(value);
    case "payer_type":
      return PAYER_LABEL[value as PayerType] ?? humanize(value);
    default:
      return value;
  }
}

function PreauthPanel({
  form,
  error,
  checklistOpen,
  onOpenChecklist,
}: {
  form: PreauthForm | null;
  error: string;
  checklistOpen: ChecklistOpenItem[];
  onOpenChecklist: () => void;
}) {
  if (error) {
    return <Notice tone="warning" title="Pre-auth form not available">{error}</Notice>;
  }
  if (!form) {
    return <Skeleton lines={8} label="Loading pre-auth form" />;
  }
  const fieldsMissing = form.missing_required.length;
  const itemsOpen = checklistOpen.length;
  const fieldsPart =
    fieldsMissing === 0 ? "Form fields complete" : `${plural(fieldsMissing, "required field")} missing`;
  const checklistPart =
    itemsOpen === 0 ? "checklist complete" : `${plural(itemsOpen, "checklist item")} missing`;
  const ready = fieldsMissing === 0 && itemsOpen === 0;
  return (
    <div className="preauth print-area">
      <div className="preauth-head">
        <div>
          <h2 className="section-title">Cashless pre-authorization request</h2>
          <p className="muted small">
            {/illustrative/i.test(form.form_version)
              ? `${form.form_version}. Confirm with each insurer/TPA.`
              : `${form.form_version}. ${ILLUSTRATIVE_NOTE}`}
          </p>
        </div>
        <Button icon="print" className="no-print" onClick={() => window.print()}>
          Print / Save PDF
        </Button>
      </div>
      <Notice
        tone={ready ? "success" : "warning"}
        title={`${fieldsPart} · ${checklistPart}${ready ? "" : " — fix before sending"}`}
        action={
          itemsOpen > 0 ? (
            <Button size="sm" className="no-print" onClick={onOpenChecklist}>
              Open checklist
            </Button>
          ) : undefined
        }
      >
        {fieldsMissing > 0 || itemsOpen > 0 ? (
          <ul className="banner-list">
            {form.missing_required.map((label) => (
              <li key={`field-${label}`}>{label}</li>
            ))}
            {checklistOpen.map((item) => (
              <li key={`item-${item.item_id}`}>Checklist: {item.label}</li>
            ))}
          </ul>
        ) : null}
      </Notice>
      {form.sections.map((section) => (
        <section key={section.title} className="form-section">
          <h3>{section.title}</h3>
          <dl className="form-fields">
            {section.fields.map((field) => {
              const missing = field.source === "missing" || !field.value;
              return (
                <div
                  key={field.key}
                  className={`form-field${missing && field.required ? " is-missing" : ""}${field.warning ? " has-warning" : ""}`}
                >
                  <dt>
                    {field.label}
                    {field.required ? <span className="req" aria-label="required">*</span> : null}
                  </dt>
                  <dd>
                    {missing ? (
                      field.required ? (
                        <span className="missing-text">
                          <Icon name="alert" size={12} />
                          Missing
                        </span>
                      ) : (
                        <span className="muted">Not provided</span>
                      )
                    ) : (
                      <span className="form-value">{displayValue(field)}</span>
                    )}
                    {!missing ? (
                      <span className="field-source">{field.source === "chart" ? "From chart" : "From case"}</span>
                    ) : null}
                    {!missing && field.hint ? <span className="field-hint-tag no-print">{field.hint}</span> : null}
                    {field.warning ? (
                      <span className="field-warning">
                        <Icon name="alert" size={12} />
                        {field.warning}
                      </span>
                    ) : null}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      ))}
      {form.attachments.length > 0 ? (
        <section className="form-section">
          <h3>Supporting documents</h3>
          <ul className="attachments">
            {form.attachments.map((item) => (
              <li key={item.label}>
                <StatusPill
                  tone={item.status === "SUPPORTED" ? "success" : "danger"}
                  icon={item.status === "SUPPORTED" ? "check" : "x"}
                  label={item.status === "SUPPORTED" ? "Attached" : "Missing"}
                />
                <span>{item.label}</span>
                {item.citations.length ? (
                  <span className="muted small">
                    {item.citations.length} source{item.citations.length === 1 ? "" : "s"}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function QueriesPanel({
  ws,
  onRecord,
  onAnswer,
}: {
  ws: CaseWorkspace;
  onRecord: () => void;
  onAnswer: () => void;
}) {
  const canRecord = ["sent", "query", "enhancement"].includes(ws.case.stage);
  return (
    <div className="queries">
      <div className="section-bar">
        <h2 className="section-title">Insurer / TPA queries</h2>
        {canRecord ? (
          <Button size="sm" icon="question" onClick={onRecord}>
            Record query
          </Button>
        ) : null}
      </div>
      {ws.queries.length === 0 ? (
        <EmptyState icon="question" title="No queries">
          When the TPA asks for more information, record it here to start the response clock.
        </EmptyState>
      ) : (
        <ol className="query-list">
          {ws.queries.map((query) => (
            <li key={query.query_id} className={`query${query.responded_at ? "" : " is-open"}`}>
              <div className="query-head">
                <strong>{query.query_id}</strong>
                <span className="muted small">Raised {formatDateTime(query.raised_at)}</span>
                {query.responded_at ? (
                  <StatusPill tone="success" label={`Answered ${formatDateTime(query.responded_at)}`} />
                ) : (
                  <StatusPill
                    tone="warning"
                    icon="clock"
                    label={query.response_due_at ? `Reply due ${formatDateTime(query.response_due_at)}` : "Awaiting reply"}
                  />
                )}
              </div>
              <p className="query-text">{query.text}</p>
              {query.response ? (
                <p className="query-response">
                  <span className="muted small">Our reply</span>
                  {query.response}
                </p>
              ) : (
                <Button size="sm" variant="primary" icon="edit" onClick={onAnswer}>
                  Answer query
                </Button>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const SEVERITY_RANK: Record<FindingSeverity, number> = { blocker: 0, warning: 1, info: 2 };
const ICD_PATTERN = /\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b/g;

/** Values worth marking in a finding's excerpt: the found/expected text, ICD codes, ₹ amounts. */
function findingTerms(finding: DischargeFinding): string[] {
  const terms: string[] = [];
  for (const raw of [finding.found, finding.expected]) {
    const value = (raw || "").replace(/^[≤≥<>]\s*/, "").trim();
    if (!value || value === "none" || value === "—") continue;
    terms.push(value);
    terms.push(...(value.match(ICD_PATTERN) ?? []));
    const withoutCode = value.replace(/\s*\([^)]*\)\s*$/, "").trim();
    if (withoutCode && withoutCode !== value) terms.push(withoutCode);
  }
  return terms;
}

function citationKey(citation: DeskCitation): string {
  return `${citation.document_id}|${citation.excerpt}`;
}

function DischargePanel({
  check,
  error,
  busy,
  onRun,
}: {
  check: DischargeCheck | null;
  error: string;
  busy: boolean;
  onRun: () => void;
}) {
  // Most severe first; each distinct excerpt is shown once (later findings point back to it).
  const ordered = check
    ? [...check.findings].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
    : [];
  const seen = new Set<string>();
  const rows = ordered.map((finding) => {
    const fresh: DeskCitation[] = [];
    const repeated: DeskCitation[] = [];
    for (const citation of finding.citations) {
      const key = citationKey(citation);
      if (seen.has(key)) repeated.push(citation);
      else {
        seen.add(key);
        fresh.push(citation);
      }
    }
    return { finding, fresh, repeated };
  });
  const blockers = blockerCount(check);
  return (
    <div className="discharge">
      <div className="section-bar">
        <div>
          <h2 className="section-title">Discharge consistency check</h2>
          <p className="muted small">Discharge summary vs pre-auth vs final bill, and required discharge documents.</p>
        </div>
        <Button size="sm" icon="check" loading={busy} onClick={onRun}>
          Re-run check
        </Button>
      </div>
      {error ? <Notice tone="warning" title="Discharge check not available">{error}</Notice> : null}
      {!check && !error ? <Skeleton lines={4} label="Running discharge check" /> : null}
      {check ? (
        <>
          {check.status === "ok" ? (
            <Notice tone="success" title="No problems found">Ready to send the discharge request.</Notice>
          ) : (
            <Notice
              tone={check.status === "blockers" ? "danger" : "warning"}
              title={
                check.status === "blockers"
                  ? `${plural(blockers, "blocker")} to fix before sending`
                  : "Warnings to review before sending"
              }
            />
          )}
          <ul className="findings">
            {rows.map(({ finding, fresh, repeated }, index) => (
              <li key={`${finding.code}-${index}`} className={`finding finding-${finding.severity}`}>
                <div className="finding-head">
                  <SeverityPill severity={finding.severity} />
                  <strong>{finding.message}</strong>
                </div>
                {finding.expected || finding.found ? (
                  <dl className="finding-compare">
                    <div>
                      <dt>Pre-auth / expected</dt>
                      <dd>{finding.expected || "—"}</dd>
                    </div>
                    <div>
                      <dt>Found at discharge</dt>
                      <dd>{finding.found || "—"}</dd>
                    </div>
                  </dl>
                ) : null}
                <Citations citations={fresh} highlight={findingTerms(finding)} />
                {repeated.length > 0 ? (
                  <p className="citation-ref">
                    <Icon name="doc" size={12} />
                    {repeated
                      .map((citation) => `Same ${documentTypeLabel(citation.source).toLowerCase()} (${citation.document_id}) as above`)
                      .join("; ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

function TimelinePanel({ ws }: { ws: CaseWorkspace }) {
  if (ws.timeline.length === 0) {
    return <EmptyState icon="clock" title="No activity yet" />;
  }
  const entries = [...ws.timeline].sort((a, b) => b.at.localeCompare(a.at));
  return (
    <ol className="timeline">
      {entries.map((entry, index) => (
        <li key={`${entry.at}-${index}`}>
          <time dateTime={entry.at}>{formatDateTime(entry.at)}</time>
          <div>
            <p>{entry.event}</p>
            {entry.actor_label ? <p className="muted small">{entry.actor_label}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function EditDrawer({
  open,
  ws,
  onClose,
  onSaved,
}: {
  open: boolean;
  ws: CaseWorkspace;
  onClose: () => void;
  onSaved: (next: CaseWorkspace) => void;
}) {
  const c = ws.case;
  const [values, setValues] = useState(() => initialValues(ws));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setValues(initialValues(ws));
      setError("");
    }
    // Reset only when the drawer opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function set<K extends keyof EditValues>(key: K, value: EditValues[K]) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const body: CaseEditable = {
      payer_type: values.payer_type,
      insurer_name: values.insurer_name.trim(),
      tpa_name: values.tpa_name.trim(),
      admission_type: values.admission_type,
      admitted_at: fromLocalInput(values.admitted_at),
      expected_discharge_at: fromLocalInput(values.expected_discharge_at),
      treating_doctor: values.treating_doctor.trim(),
      provisional_diagnosis: values.provisional_diagnosis.trim(),
      icd10_code: values.icd10_code.trim().toUpperCase(),
      proposed_treatment: values.proposed_treatment.trim(),
      estimated_cost_inr: parseAmount(values.estimated_cost_inr),
    };
    if (values.policy_number.trim()) {
      body.policy_number = values.policy_number.trim();
    }
    try {
      onSaved(await patchCase(c.case_id, body));
    } catch (err) {
      setError(deskErrorMessage(err, "Could not save case details."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer
      open={open}
      title="Edit case details"
      onClose={onClose}
      footer={
        <div className="button-row">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="case-edit-form" loading={saving}>
            Save details
          </Button>
        </div>
      }
    >
      <form id="case-edit-form" className="stack-form" onSubmit={onSubmit}>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <fieldset>
          <legend>Payer</legend>
          <label className="field">
            <span>Payer type</span>
            <select value={values.payer_type} onChange={(e) => set("payer_type", e.target.value as PayerType)}>
              {(Object.keys(PAYER_LABEL) as PayerType[]).map((key) => (
                <option key={key} value={key}>
                  {PAYER_LABEL[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Insurer</span>
            <input value={values.insurer_name} onChange={(e) => set("insurer_name", e.target.value)} placeholder="e.g. Star Health" />
          </label>
          <label className="field">
            <span>TPA (optional)</span>
            <input value={values.tpa_name} onChange={(e) => set("tpa_name", e.target.value)} placeholder="e.g. Medi Assist" />
          </label>
          <label className="field">
            <span>Policy number</span>
            <input
              value={values.policy_number}
              onChange={(e) => set("policy_number", e.target.value)}
              placeholder={c.policy_number ? `Current ${maskPolicy(c.policy_number)}; leave blank to keep` : ""}
              autoComplete="off"
            />
          </label>
        </fieldset>
        <fieldset>
          <legend>Admission</legend>
          <label className="field">
            <span>Admission type</span>
            <select value={values.admission_type} onChange={(e) => set("admission_type", e.target.value as AdmissionType)}>
              <option value="planned">Planned</option>
              <option value="emergency">Emergency</option>
            </select>
          </label>
          <label className="field">
            <span>Admitted at</span>
            <input type="datetime-local" value={values.admitted_at} onChange={(e) => set("admitted_at", e.target.value)} />
          </label>
          <label className="field">
            <span>Expected discharge</span>
            <input
              type="datetime-local"
              value={values.expected_discharge_at}
              onChange={(e) => set("expected_discharge_at", e.target.value)}
            />
          </label>
        </fieldset>
        <fieldset>
          <legend>Clinical</legend>
          <label className="field">
            <span>Treating doctor</span>
            <input value={values.treating_doctor} onChange={(e) => set("treating_doctor", e.target.value)} />
          </label>
          <label className="field">
            <span>Provisional diagnosis</span>
            <input value={values.provisional_diagnosis} onChange={(e) => set("provisional_diagnosis", e.target.value)} />
          </label>
          <label className="field">
            <span>ICD-10 code</span>
            <input value={values.icd10_code} onChange={(e) => set("icd10_code", e.target.value)} placeholder="e.g. H25.9" />
          </label>
          <label className="field">
            <span>Proposed treatment</span>
            <input value={values.proposed_treatment} onChange={(e) => set("proposed_treatment", e.target.value)} />
          </label>
          <label className="field">
            <span>Estimated cost (₹)</span>
            <input
              inputMode="numeric"
              value={values.estimated_cost_inr}
              onChange={(e) => set("estimated_cost_inr", e.target.value)}
              placeholder="e.g. 85000"
            />
          </label>
        </fieldset>
      </form>
    </Drawer>
  );
}

type EditValues = {
  payer_type: PayerType;
  insurer_name: string;
  tpa_name: string;
  policy_number: string;
  admission_type: AdmissionType;
  admitted_at: string;
  expected_discharge_at: string;
  treating_doctor: string;
  provisional_diagnosis: string;
  icd10_code: string;
  proposed_treatment: string;
  estimated_cost_inr: string;
};

function initialValues(ws: CaseWorkspace): EditValues {
  const c = ws.case;
  return {
    payer_type: c.payer_type,
    insurer_name: c.insurer_name || "",
    tpa_name: c.tpa_name || "",
    policy_number: "",
    admission_type: c.admission_type,
    admitted_at: toLocalInput(c.admitted_at),
    expected_discharge_at: toLocalInput(c.expected_discharge_at),
    treating_doctor: c.treating_doctor || "",
    provisional_diagnosis: c.provisional_diagnosis || "",
    icd10_code: c.icd10_code || "",
    proposed_treatment: c.proposed_treatment || "",
    estimated_cost_inr: c.estimated_cost_inr != null ? String(c.estimated_cost_inr) : "",
  };
}

const STAGE_TITLE: Record<StageKind, string> = {
  record_query: "Record TPA query",
  answer_query: "Answer TPA query",
  request_enhancement: "Request enhancement",
  record_approval: "Record approval?",
  mark_sent: "Mark sent to TPA?",
  mark_discharge_sent: "Mark discharge sent?",
  close: "Close this case?",
};

const STAGE_SUBMIT: Record<StageKind, string> = {
  record_query: "Record query",
  answer_query: "Answer query",
  request_enhancement: "Request enhancement",
  record_approval: "Record approval",
  mark_sent: "Mark sent",
  mark_discharge_sent: "Mark discharge sent",
  close: "Close case",
};

const OVERRIDE_MIN = 10;

function SummaryRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * Stage steps. Detail-gathering steps open a drawer; irreversible steps (record approval,
 * mark sent, mark discharge sent, close) open a confirm dialog with a summary.
 */
function StageDrawer({
  kind,
  ws,
  discharge,
  error,
  onClose,
  onSubmit,
}: {
  kind: StageKind | null;
  ws: CaseWorkspace;
  discharge: DischargeCheck | null;
  error: string;
  onClose: () => void;
  onSubmit: (body: StageAction, success: string) => Promise<void>;
}) {
  const openQueries = ws.queries.filter((query) => !query.responded_at);
  const [text, setText] = useState("");
  const [hours, setHours] = useState("24");
  const [amount, setAmount] = useState("");
  const [queryId, setQueryId] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setText("");
    setHours("24");
    setQueryId(openQueries[0]?.query_id ?? "");
    setAmount("");
    // Reset only when the drawer kind changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  if (!kind) {
    return null;
  }

  const c = ws.case;
  const blockers = discharge ? discharge.findings.filter((finding) => finding.severity === "blocker") : [];
  const override = kind === "mark_discharge_sent" && blockers.length > 0;
  const confirm = CONFIRM_KINDS.has(kind);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!kind) return;
    setSaving(true);
    try {
      switch (kind) {
        case "record_query":
          await onSubmit(
            { action: "record_query", text: text.trim(), response_due_hours: Number(hours) || 24 },
            "Query recorded. Response clock started.",
          );
          break;
        case "answer_query":
          await onSubmit({ action: "answer_query", query_id: queryId, response: text.trim() }, "Query answered");
          break;
        case "record_approval":
          await onSubmit(
            { action: "record_approval", approved_amount_inr: parseAmount(amount) ?? 0 },
            "Approval recorded",
          );
          break;
        case "request_enhancement":
          await onSubmit(
            { action: "request_enhancement", revised_estimate_inr: parseAmount(amount) ?? 0, reason: text.trim() },
            "Enhancement requested",
          );
          break;
        case "mark_sent":
          await onSubmit({ action: "mark_sent" }, "Marked sent to TPA. Decision clock started.");
          break;
        case "mark_discharge_sent":
          await onSubmit(
            override
              ? { action: "mark_discharge_sent", override_reason: text.trim() }
              : { action: "mark_discharge_sent" },
            override ? "Discharge sent with override. Reason saved on the timeline." : "Discharge marked as sent",
          );
          break;
        case "close":
          await onSubmit({ action: "close" }, "Case closed");
          break;
        default: {
          const never: never = kind;
          return never;
        }
      }
    } finally {
      setSaving(false);
    }
  }

  const needsText =
    kind === "record_query" || kind === "answer_query" || kind === "request_enhancement" || override;
  const minText = override ? OVERRIDE_MIN : 3;
  const needsAmount = kind === "record_approval" || kind === "request_enhancement";
  const disabled =
    (needsText && text.trim().length < minText) ||
    (needsAmount && !parseAmount(amount)) ||
    (kind === "answer_query" && !queryId);
  const textLabel =
    kind === "record_query"
      ? "Query from the insurer/TPA"
      : kind === "answer_query"
        ? "Our response"
        : kind === "request_enhancement"
          ? "Reason for enhancement"
          : "Override reason (required: why send despite the blockers?)";
  const submitLabel = override ? "Send with override" : STAGE_SUBMIT[kind];
  const submitVariant: ButtonVariant = override ? "danger" : "primary";
  const title = override ? "Send discharge with override?" : STAGE_TITLE[kind];
  const payer = `${c.insurer_name || PAYER_LABEL[c.payer_type]}${c.tpa_name ? ` via ${c.tpa_name}` : ""}`;

  return (
    <Drawer
      open
      variant={confirm ? "dialog" : "drawer"}
      title={title}
      onClose={onClose}
      footer={
        <div className="button-row">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant={submitVariant} type="submit" form="stage-form" loading={saving} disabled={disabled}>
            {submitLabel}
          </Button>
        </div>
      }
    >
      <form id="stage-form" className="stack-form" onSubmit={submit}>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {confirm ? (
          <dl className="confirm-summary">
            <SummaryRow label="Patient">
              {ws.patient.name} <span className="muted">({c.case_id})</span>
            </SummaryRow>
            <SummaryRow label="Insurer / TPA">{payer}</SummaryRow>
            <SummaryRow label="Treatment">{c.proposed_treatment || "Not recorded"}</SummaryRow>
            <SummaryRow label="Estimate">
              <Money value={c.estimated_cost_inr} />
            </SummaryRow>
            {kind === "close" || kind === "mark_discharge_sent" ? (
              <SummaryRow label="Approved">
                <Money value={c.approved_amount_inr} />
              </SummaryRow>
            ) : null}
            {kind === "mark_sent" ? (
              <SummaryRow label="Senior review">{ws.review.by_label || "Confirmed"}</SummaryRow>
            ) : null}
          </dl>
        ) : null}
        {kind === "answer_query" ? (
          openQueries.length === 0 ? (
            <p className="muted">There are no open queries on this case.</p>
          ) : (
            <label className="field">
              <span>Query</span>
              <select value={queryId} onChange={(e) => setQueryId(e.target.value)}>
                {openQueries.map((query) => (
                  <option key={query.query_id} value={query.query_id}>
                    {query.query_id}: {query.text.slice(0, 80)}
                  </option>
                ))}
              </select>
            </label>
          )
        ) : null}
        {kind === "answer_query" && queryId ? (
          <blockquote className="quoted">{openQueries.find((query) => query.query_id === queryId)?.text}</blockquote>
        ) : null}
        {override ? (
          <div className="confirm-blockers">
            <p className="confirm-blockers-title">
              <Icon name="alert" size={14} />
              The discharge check found {plural(blockers.length, "blocker")}:
            </p>
            <ul>
              {blockers.map((finding, index) => (
                <li key={`${finding.code}-${index}`}>{finding.message}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {needsAmount ? (
          <label className="field">
            <span>{kind === "record_approval" ? "Approved amount (₹)" : "Revised estimate (₹)"}</span>
            <input
              inputMode="numeric"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={kind === "record_approval" ? "As on the approval letter" : undefined}
              required
            />
            {parseAmount(amount) ? (
              <span className="field-hint">
                <Money value={parseAmount(amount)} />
              </span>
            ) : null}
          </label>
        ) : null}
        {needsText ? (
          <label className="field">
            <span>{textLabel}</span>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={override ? 3 : 5} required />
            {override && text.trim().length < OVERRIDE_MIN ? (
              <span className="field-hint">At least {OVERRIDE_MIN} characters. Saved on the case timeline.</span>
            ) : null}
          </label>
        ) : null}
        {kind === "record_query" ? (
          <label className="field">
            <span>Reply due within (hours)</span>
            <input inputMode="numeric" value={hours} onChange={(e) => setHours(e.target.value.replace(/[^\d]/g, ""))} />
          </label>
        ) : null}
        {confirm ? (
          <Notice tone="warning" title="This step can't be undone from the desk.">
            {kind === "mark_sent"
              ? "Only mark it sent after submitting on the insurer/TPA portal. The 1-hour decision clock (IRDAI) starts now."
              : kind === "record_approval"
                ? "Record the amount exactly as on the insurer/TPA approval letter. The case moves to Approved."
                : kind === "mark_discharge_sent"
                  ? "The 3-hour final approval clock (IRDAI) starts when you mark it sent."
                  : "The case leaves the work queue and the timeline is kept for audit."}
          </Notice>
        ) : null}
      </form>
    </Drawer>
  );
}
