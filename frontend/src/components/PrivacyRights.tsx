import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createMyRequest,
  getMyAccessLog,
  getMyExport,
  getMyRequests,
  listConsents,
  revokeConsent,
  type AccessLog,
  type ConsentRecord,
  type DataSubjectRequest,
  type DataSubjectRequestType,
} from "../api";

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

function when(value: string | null): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

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

  return (
    <div className="panel">
      <h2 className="panel-title">Who accessed my record</h2>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {log ? (
        <>
          {log.entries.length === 0 ? (
            <p className="muted">No access recorded yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Who</th>
                    <th>What</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {log.entries.map((entry) => (
                    <tr key={entry.event_id}>
                      <td>{when(entry.occurred_at)}</td>
                      <td>{entry.actor_label}</td>
                      <td>{entry.action_label}</td>
                      <td>
                        <span className={`badge ${entry.outcome === "denied" ? "bad" : "ok"}`}>
                          {entry.outcome === "denied" ? "Blocked" : "Allowed"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset + PAGE_SIZE >= log.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older
            </button>
            <span className="muted">
              {log.total} event{log.total === 1 ? "" : "s"}
            </span>
          </div>
          {log.disclaimer ? <p className="hint">{log.disclaimer}</p> : null}
        </>
      ) : null}
    </div>
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
    <div className="panel">
      <h2 className="panel-title">Download my data</h2>
      <p className="muted">
        A complete copy of your record (visits, labs, medicines, consents, requests) as a JSON file.
      </p>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      <button type="button" className="btn btn-primary" disabled={busy} onClick={onDownload}>
        {busy ? "Preparing…" : "Download my data"}
      </button>
    </div>
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
    <div className="panel">
      <h2 className="panel-title">My consents</h2>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {consents.length === 0 ? (
        <p className="muted">No consents on file.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Purpose</th>
                <th>Given</th>
                <th>How</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {consents.map((consent) => (
                <tr key={consent.consent_id}>
                  <td>
                    {PURPOSE_LABELS[consent.purpose] ?? consent.purpose}
                    <div className="hint">
                      {consent.consent_id} · notice {consent.notice_version}
                    </div>
                  </td>
                  <td>{when(consent.granted_at)}</td>
                  <td>{consent.method.replace("_", " ")}</td>
                  <td>
                    {consent.active ? (
                      <span className="badge ok">Active</span>
                    ) : consent.revoked_at ? (
                      <span className="badge neutral">Withdrawn {when(consent.revoked_at)}</span>
                    ) : (
                      <span className="badge warn">Expired</span>
                    )}
                  </td>
                  <td>
                    {consent.active ? (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busyId === consent.consent_id}
                        onClick={() => void onRevoke(consent)}
                      >
                        Withdraw
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="hint">
        Withdrawing stops new records being added under that consent. Records already in your
        chart are kept as required by medical-record retention law.
      </p>
    </div>
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
    <div className="panel">
      <h2 className="panel-title">Requests</h2>
      <form className="form-grid" onSubmit={onSubmit}>
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
        <label className="field span-2">
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
        <div className="form-actions span-2">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || details.trim().length < 3}
          >
            {busy ? "Submitting…" : "Submit request"}
          </button>
          {requestType === "erasure" ? (
            <span className="hint">
              Medical records usually must be kept for a legal retention period; the facility will
              explain what can be erased or restricted.
            </span>
          ) : null}
        </div>
      </form>
      {notice ? <p className="hint" role="status">{notice}</p> : null}
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {requests.length === 0 ? (
        <p className="muted">No requests yet.</p>
      ) : (
        <ul className="lifelong-list">
          {requests.map((item) => (
            <li key={item.request_id} className="lifelong-item">
              <div className="lifelong-when">{when(item.created_at).split(",")[0]}</div>
              <div className="lifelong-body">
                <div className="lifelong-top">
                  <strong>{item.request_id}</strong>
                  <span className="badge neutral">{item.request_type}</span>
                  <span
                    className={`badge ${
                      item.status === "resolved" ? "ok" : item.status === "rejected" ? "bad" : "warn"
                    }`}
                  >
                    {item.status.replace("_", " ")}
                  </span>
                </div>
                <p>{item.details}</p>
                {item.resolution_note ? <p className="hint">{item.resolution_note}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
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
