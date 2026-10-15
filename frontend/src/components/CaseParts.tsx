/** Shared case pieces used by the case workspace and senior Reviews. */
import { Fragment, useState, type ReactNode } from "react";
import { reportTypeFor, type ChecklistGroup, type ChecklistItem, type DeskCitation, type Stage } from "../deskApi";
import { useI18n, type MessageKey } from "../i18n";
import { documentTypeLabel } from "../labels";
import { Button, ButtonLink, Icon, ItemStatusPill, formatDate } from "../ui";

export const ILLUSTRATIVE_NOTE = "Illustrative field set — confirm with each insurer/TPA.";

const GROUP_ORDER: ChecklistGroup[] = ["form", "clinical", "documents"];

const GROUP_LABEL: Record<ChecklistGroup, string> = {
  form: "Form fields",
  clinical: "Clinical evidence",
  documents: "Documents",
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Wrap each occurrence of `terms` in <mark> (case-insensitive, longest term first). */
export function Highlighted({ text, terms }: { text: string; terms?: string[] }) {
  const wanted = (terms ?? [])
    .map((term) => term.trim())
    .filter((term) => term.length >= 3)
    .sort((a, b) => b.length - a.length);
  if (wanted.length === 0) {
    return <>{text}</>;
  }
  const pattern = new RegExp(`(${wanted.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? <mark key={index}>{part}</mark> : <Fragment key={index}>{part}</Fragment>,
      )}
    </>
  );
}

export function Citations({
  citations,
  highlight,
}: {
  citations: DeskCitation[];
  /** Values to mark inside the excerpt (diagnosis, ICD code, amount). */
  highlight?: string[];
}) {
  if (citations.length === 0) {
    return null;
  }
  return (
    <ul className="citations" aria-label="Chart citations">
      {citations.map((citation, index) => (
        <li key={`${citation.document_id}-${citation.chunk_id}-${index}`} className="citation">
          <blockquote>
            <Highlighted text={citation.excerpt} terms={highlight} />
          </blockquote>
          <p className="citation-meta">
            <Icon name="doc" size={12} />
            <span>{documentTypeLabel(citation.source)}</span>
            {citation.date ? <span>{formatDate(citation.date)}</span> : null}
            <span className="citation-id">{citation.document_id}</span>
          </p>
        </li>
      ))}
    </ul>
  );
}

/** Where a missing item's "To fix" button leads. Optional: Reviews shows hints only. */
export type ChecklistFixActions = {
  patientId: string;
  caseId: string;
  policyId?: string | null;
  onEditCase?: () => void;
};

function visitLink(actions: ChecklistFixActions, item: ChecklistItem, focus: "note" | "document"): string {
  const params = new URLSearchParams({ patient: actions.patientId, case: actions.caseId, focus });
  if (actions.policyId) params.set("policy", actions.policyId);
  params.set("gap", item.label);
  if (focus === "document") params.set("doctype", reportTypeFor(item.label));
  return `/visit?${params.toString()}`;
}

function FixAction({ item, actions }: { item: ChecklistItem; actions?: ChecklistFixActions }) {
  if (!actions) return null;
  if (item.group === "form") {
    return actions.onEditCase ? (
      <Button size="sm" icon="edit" onClick={actions.onEditCase}>
        Edit case details
      </Button>
    ) : null;
  }
  if (item.group === "documents" && item.status === "MISSING") {
    return (
      <ButtonLink size="sm" icon="doc" to={visitLink(actions, item, "document")}>
        Attach document
      </ButtonLink>
    );
  }
  return (
    <ButtonLink size="sm" icon="note" to={visitLink(actions, item, "note")}>
      Add visit note
    </ButtonLink>
  );
}

function ChecklistRow({ item, actions }: { item: ChecklistItem; actions?: ChecklistFixActions }) {
  const open = item.status !== "SUPPORTED";
  const hasAction = Boolean(actions && (item.group !== "form" || actions.onEditCase));
  const fix: ReactNode = open && hasAction ? <FixAction item={item} actions={actions} /> : null;
  return (
    <li className={`check-item check-${item.status.toLowerCase()}`}>
      <div className="check-head">
        <ItemStatusPill status={item.status} onCase={item.group === "form"} />
        <p className="check-label">
          {item.label}
          {!item.required ? <span className="tag">Optional</span> : null}
        </p>
      </div>
      {item.reason && (open || item.group !== "form") ? <p className="check-reason">{item.reason}</p> : null}
      {open && (item.fix_hint || fix) ? (
        <div className="check-fix">
          <Icon name="arrow-right" size={14} />
          <span>
            <strong>To fix:</strong> {item.fix_hint}
          </span>
          {fix ? <span className="check-fix-action">{fix}</span> : null}
        </div>
      ) : null}
      <Citations citations={item.citations} />
      {item.status === "SUPPORTED" && item.citations.length === 0 && item.group !== "form" ? (
        <p className="check-reason muted">No excerpt attached to this item.</p>
      ) : null}
    </li>
  );
}

/** Checklist grouped as form / clinical / documents, citations shown inline. */
export function Checklist({ items, actions }: { items: ChecklistItem[]; actions?: ChecklistFixActions }) {
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [formExpanded, setFormExpanded] = useState<boolean | null>(null);
  const visible = onlyOpen ? items.filter((item) => item.status !== "SUPPORTED") : items;

  return (
    <div className="checklist">
      <div className="checklist-bar">
        <p className="muted small">{ILLUSTRATIVE_NOTE}</p>
        <label className="switch">
          <input type="checkbox" checked={onlyOpen} onChange={(event) => setOnlyOpen(event.target.checked)} />
          <span>Show open items only</span>
        </label>
      </div>
      {visible.length === 0 ? (
        <p className="muted">Every required item is supported by the chart.</p>
      ) : null}
      {GROUP_ORDER.map((group) => {
        const groupItems = visible.filter((item) => item.group === group);
        if (groupItems.length === 0) {
          return null;
        }
        const all = items.filter((item) => item.group === group);
        const supported = all.filter((item) => item.status === "SUPPORTED").length;
        if (group === "form") {
          const openCount = all.length - supported;
          // Form fields collapse to one summary line; open fields keep it expanded by default.
          const expanded = formExpanded ?? (openCount > 0 || onlyOpen);
          return (
            <section key={group} className="check-group" aria-label={GROUP_LABEL[group]}>
              <button
                type="button"
                className="check-summary"
                aria-expanded={expanded}
                aria-controls="checklist-form-fields"
                onClick={() => setFormExpanded(!expanded)}
              >
                <Icon name="chevron-down" className={expanded ? "is-flipped" : undefined} />
                <ItemStatusPill status={openCount === 0 ? "SUPPORTED" : "MISSING"} onCase />
                <span className="check-summary-text">
                  {supported} of {all.length} form fields on case
                  {openCount > 0 ? <span className="muted"> · {openCount} missing</span> : null}
                </span>
              </button>
              {expanded ? (
                <ul className="check-list" id="checklist-form-fields">
                  {groupItems.map((item) => (
                    <ChecklistRow key={item.item_id} item={item} actions={actions} />
                  ))}
                </ul>
              ) : null}
            </section>
          );
        }
        return (
          <section key={group} className="check-group" aria-label={GROUP_LABEL[group]}>
            <h3 className="check-group-title">
              {GROUP_LABEL[group]}
              <span className="muted">
                {supported} of {all.length} supported
              </span>
            </h3>
            <ul className="check-list">
              {groupItems.map((item) => (
                <ChecklistRow key={item.item_id} item={item} actions={actions} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

type StepId = "draft" | "ready" | "sent" | "query" | "approved" | "discharge" | "closed";

const STEPS: StepId[] = ["draft", "ready", "sent", "query", "approved", "discharge", "closed"];

const STAGE_STEP: Record<Stage, StepId> = {
  draft: "draft",
  ready_to_send: "ready",
  sent: "sent",
  query: "query",
  approved: "approved",
  enhancement: "approved",
  discharge_pending: "discharge",
  discharge_sent: "discharge",
  closed: "closed",
};

/** Draft → Ready → Sent → Query → Approved → Discharge → Closed. */
export function StageStepper({ stage, hadQuery }: { stage: Stage; hadQuery: boolean }) {
  const { t } = useI18n();
  const current = STEPS.indexOf(STAGE_STEP[stage]);
  return (
    <ol className="stepper" aria-label="Case stage">
      {STEPS.map((step, index) => {
        const skipped = step === "query" && index < current && !hadQuery;
        const state = index < current ? (skipped ? "skipped" : "done") : index === current ? "current" : "todo";
        return (
          <li key={step} className={`step step-${state}`} aria-current={state === "current" ? "step" : undefined}>
            <span className="step-marker" aria-hidden="true">
              {state === "done" ? <Icon name="check" size={12} /> : index + 1}
            </span>
            <span className="step-label">{t(`step.${step}` as MessageKey)}</span>
            <span className="sr-only">
              {state === "done" ? " (done)" : state === "current" ? " (current)" : state === "skipped" ? " (not needed)" : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
