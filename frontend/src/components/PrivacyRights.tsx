import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createMyRequest,
  getMyAccessLog,
  getMyExport,
  getMyRequests,
  listConsents,
  revokeConsent,
  type AccessLog,
  type AccessLogEntry,
  type ConsentRecord,
  type DataSubjectRequest,
  type DataSubjectRequestType,
} from "../api";
import { formatDateTime } from "../ui";

const PAGE_SIZE = 20;

const PURPOSE_LABELS: Record<string, string> = {
  prior_auth_evidence: "Insurance prior-authorization evidence",
  continuity_of_care: "Continuity of care across facilities",
  research_trial: "Research / clinical trial",
};

const REQUEST_LABELS: Record<DataSubjectRequestType, string> = {
  correction: "Correct something in my record",
  erasure: "Erase my data",
  grievance: "Raise a grievance",
  nominee: "Nominate someone to act for me",
};

/** Same "14 Oct, 12:54" (en-IN) format as the rest of the desk. */
function when(value: string | null): string {
  if (!value) {
    return "—";
  }
  const formatted = formatDateTime(value);
  return formatted === "—" ? value : formatted;
}

type AccessRow =
  | { kind: "entry"; entry: AccessLogEntry }
  | { kind: "self"; key: string; count: number; label: string; latest: string; earliest: string; day: string };

function dayKey(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value.slice(0, 10) : parsed.toDateString();
}

function dayLabel(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (parsed.toDateString() === today.toDateString()) return "today";
  if (parsed.toDateString() === yesterday.toDateString()) return "yesterday";
  return `on ${parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`;
}

/** Collapse consecutive identical rows of your own activity (same action, same day) into one. */
export function collapseAccessLog(entries: AccessLogEntry[]): AccessRow[] {
  const rows: AccessRow[] = [];
  for (const entry of entries) {
    const isSelf = entry.actor_category === "you" && entry.outcome === "allowed";
    const last = rows[rows.length - 1];
    const day = dayKey(entry.occurred_at);
    if (isSelf && last && last.kind === "self" && last.day === day && last.label === entry.action_label) {
      last.count += 1;
      last.earliest = entry.occurred_at;
      continue;
    }
    if (isSelf) {
      rows.push({
        kind: "self",
        key: entry.event_id,
        count: 1,
        label: entry.action_label,
        latest: entry.occurred_at,
        earliest: entry.occurred_at,
        day,
      });
    } else {
      rows.push({ kind: "entry", entry });
    }
  }
  return rows;
}

const ACTOR_LABEL: Record<AccessLogEntry["actor_category"], string> = {
  you: "You",
  care_team: "Care team",
  care_team_emergency: "Care team (emergency access)",
  system: "System",
  other_patient: "Another patient",
  unknown: "Unknown",
};

function AccessLogSection() {
  const [log, setLog] = useState<AccessLog | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getMyAccessLog({ limit: PAGE_SIZE, offset })
      .then((body) => {
        if (!cancelled) {
          setLog(body);
          setError("");
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [offset]);

  const rows = log ? collapseAccessLog(log.entries) : [];

  return (
    <section className="panel" aria-labelledby="access-title">
      <h2 className="section-title" id="access-title">
        Who looked at my record
      </h2>
      <p className="muted small">Every time someone opens your record, it is logged here. Access by hospital staff is shown in bold.</p>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {!log && !error ? <p className="muted">Loading…</p> : null}
      {log ? (
        <>
          {rows.length === 0 ? (
            <p className="muted">No one has opened your record yet.</p>
          ) : (
            <ul className="access-log">
              {rows.map((row) =>
                row.kind === "self" ? (
                  <li key={row.key} className="access-self">
                    <span>
                      {`You: ${(row.label || "viewed your record").replace(/^\w/, (ch) => ch.toLowerCase())}`}
                      {row.count > 1 ? (
                        <span className="count-badge" aria-label={`${row.count} times ${dayLabel(row.latest)}`}>
                          ×{row.count}
                        </span>
                      ) : null}
                    </span>
                    <span className="muted small">
                      {row.count > 1 && row.earliest !== row.latest
                        ? `${when(row.earliest)} – ${when(row.latest).split(", ").pop() ?? ""}`
                        : when(row.latest)}
                    </span>
                  </li>
                ) : (
                  <li
                    key={row.entry.event_id}
                    className={`access-other${row.entry.outcome === "denied" ? " access-denied" : ""}`}
                  >
                    <span>
                      <strong>{row.entry.actor_label || ACTOR_LABEL[row.entry.actor_category]}</strong>
                      <br />
                      {row.entry.action_label}
                    </span>
                    <span className="access-meta">
                      <span className={`pill ${row.entry.outcome === "denied" ? "pill-danger" : "pill-neutral"}`}>
                        {row.entry.outcome === "denied" ? "Blocked" : "Allowed"}
                      </span>
                      <span className="muted small">{when(row.entry.occurred_at)}</span>
                    </span>
                  </li>
                ),
              )}
            </ul>
          )}
          <div className="button-row">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={offset + PAGE_SIZE >= log.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older
            </button>
            <span className="muted small">
              {log.total} event{log.total === 1 ? "" : "s"} in total
            </span>
          </div>
          {log.disclaimer ? <p className="fine-print">{log.disclaimer}</p> : null}
        </>
      ) : null}
    </section>
  );
}

function ExportSection() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onDownload() {
    setBusy(true);
    setError("");
    try {
      const body = await getMyExport();
      const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const patient = typeof body.patient_id === "string" ? body.patient_id : "record";
      link.download = `my-health-record-${patient}-${body.generated_at.slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2 className="section-title">Download my data</h2>
      <p className="muted">
        A complete copy of your record (visits, labs, medicines, consents, requests) as a JSON file.
      </p>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      <button type="button" className="btn btn-primary" disabled={busy} onClick={onDownload}>
        {busy ? "Preparing…" : "Download my data"}
      </button>
    </section>
  );
}

function ConsentSection({ patientId }: { patientId: string }) {
  const [consents, setConsents] = useState<ConsentRecord[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async () => {
    try {
      const body = await listConsents(patientId);
      setConsents(body.consents);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load consents");
    }
  }, [patientId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onRevoke(consent: ConsentRecord) {
    const reason = window.prompt(
      "Withdraw this consent? Tell us why (at least 3 characters).",
      "I no longer consent",
    );
    if (!reason || reason.trim().length < 3) {
      return;
    }
    setBusyId(consent.consent_id);
    try {
      await revokeConsent(patientId, consent.consent_id, reason.trim());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not withdraw consent");
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="panel">
      <h2 className="section-title">My consents</h2>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {consents.length === 0 ? (
        <p className="muted">No consents on file.</p>
      ) : (
        <ul className="consent-list">
          {consents.map((consent) => (
            <li key={consent.consent_id}>
              <div>
                <p>
                  <strong>{PURPOSE_LABELS[consent.purpose] ?? consent.purpose}</strong>
                </p>
                <p className="muted small">
                  Given {when(consent.granted_at)}, {consent.method.replace("_", " ")}. Ref {consent.consent_id}, notice{" "}
                  {consent.notice_version}
                </p>
              </div>
              <div className="consent-actions">
                {consent.active ? (
                  <span className="pill pill-success">Active</span>
                ) : consent.revoked_at ? (
                  <span className="pill pill-neutral">Withdrawn {when(consent.revoked_at)}</span>
                ) : (
                  <span className="pill pill-warning">Expired</span>
                )}
                {consent.active ? (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={busyId === consent.consent_id}
                    onClick={() => void onRevoke(consent)}
                  >
                    Withdraw
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">
        Withdrawing stops new records being added under that consent. Records already in your
        chart are kept as required by medical-record retention law.
      </p>
    </section>
  );
}

function RequestsSection() {
  const [requests, setRequests] = useState<DataSubjectRequest[]>([]);
  const [requestType, setRequestType] = useState<DataSubjectRequestType>("correction");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const body = await getMyRequests();
      setRequests(body.requests);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load requests");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await createMyRequest({ request_type: requestType, details: details.trim() });
      setNotice(`Request ${created.request_id} submitted.`);
      setDetails("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit request");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2 className="section-title">Requests</h2>
      <form className="stack-form" onSubmit={onSubmit}>
        <label className="field">
          <span>Request type</span>
          <select
            value={requestType}
            onChange={(e) => setRequestType(e.target.value as DataSubjectRequestType)}
          >
            {(Object.keys(REQUEST_LABELS) as DataSubjectRequestType[]).map((key) => (
              <option key={key} value={key}>
                {REQUEST_LABELS[key]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Details</span>
          <textarea
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            rows={3}
            minLength={3}
            maxLength={4000}
            required
          />
        </label>
        <div className="button-row">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || details.trim().length < 3}
          >
            {busy ? "Submitting…" : "Submit request"}
          </button>
          {requestType === "erasure" ? (
            <span className="muted small">
              Medical records usually must be kept for a legal retention period; the facility will
              explain what can be erased or restricted.
            </span>
          ) : null}
        </div>
      </form>
      {notice ? <p className="muted small" role="status">{notice}</p> : null}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {requests.length === 0 ? (
        <p className="muted">No requests yet.</p>
      ) : (
        <ul className="request-list">
          {requests.map((item) => (
            <li key={item.request_id} className="request-item">
              <div className="event-when">{when(item.created_at).split(",")[0]}</div>
              <div className="request-body">
                <div className="request-top">
                  <strong>{item.request_id}</strong>
                  <span className="pill pill-neutral">{item.request_type}</span>
                  <span
                    className={`pill ${
                      item.status === "resolved" ? "pill-success" : item.status === "rejected" ? "pill-danger" : "pill-warning"
                    }`}
                  >
                    {item.status.replace("_", " ")}
                  </span>
                </div>
                <p>{item.details}</p>
                {item.resolution_note ? <p className="muted small">{item.resolution_note}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Patient self-service privacy rights (DPDP / HIPAA). Patient sign-ins only. */
export function PrivacyRights({ patientId }: { patientId: string }) {
  return (
    <section className="privacy-rights" aria-label="Privacy and my rights">
      <AccessLogSection />
      <ExportSection />
      <ConsentSection patientId={patientId} />
      <RequestsSection />
    </section>
  );
}
