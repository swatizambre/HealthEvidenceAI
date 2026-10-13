import { KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getPatients, type PatientSummary } from "../api";
import { formatLiveAge, useLiveRefresh } from "../hooks/useLiveRefresh";
import { conditionLabel } from "../labels";
import { pushRecentPatient, readRecentPatients } from "../recentPatients";

const PAGE_SIZE = 15;

function truncateConditions(conditions: string[], limit = 2): string {
  if (conditions.length === 0) {
    return "None recorded";
  }
  const cleaned = conditions.map(conditionLabel);
  const head = cleaned.slice(0, limit).join("; ");
  return cleaned.length > limit ? `${head}; +${cleaned.length - limit} more` : head;
}

export function PatientsPage() {
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [patients, setPatients] = useState<PatientSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState(() => readRecentPatients());
  const [tick, setTick] = useState(0);

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setOffset(0);
  }, [debounced]);

  const loadPatients = useCallback(async () => {
    setError("");
    try {
      const body = await getPatients({
        limit: PAGE_SIZE,
        offset,
        q: debounced || undefined,
      });
      setPatients(body.patients);
      setTotal(body.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh patients");
    }
  }, [debounced, offset]);

  const { lastUpdatedAt, refreshNow, pushConnected } = useLiveRefresh(loadPatients, {
    intervalMs: 60_000,
  });

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 5_000);
    return () => window.clearInterval(id);
  }, []);
  void tick;

  function openPatient(patient: PatientSummary) {
    pushRecentPatient({
      patient_id: patient.patient_id,
      display_name: patient.synthetic_name,
    });
    setRecent(readRecentPatients());
    navigate(`/patients/${patient.patient_id}`);
  }

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && patients && patients.length > 0) {
      event.preventDefault();
      openPatient(patients[0]);
    }
  }

  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Patient records</p>
          <h1 className="page-title">Patients</h1>
          <p className="page-subtitle">
            Locate a patient, review required chart items, prepare the evidence pack, and add visit
            notes for any gaps. Staff and residents prepare here; seniors confirm in Reviews.
          </p>
          <p className="live-stamp">
            <span aria-live="polite">{formatLiveAge(lastUpdatedAt, pushConnected)}</span>
            {" · "}
            <button type="button" className="text-link" onClick={refreshNow}>
              Refresh now
            </button>
          </p>
        </div>
      </header>

      <div className="finder-bar">
        <label className="search-field grow">
          <span className="sr-only">Find patient</span>
          <input
            ref={searchRef}
            type="search"
            placeholder="Find by PAT-ID, name, or condition…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onSearchKeyDown}
            autoComplete="off"
          />
        </label>
        <Link className="btn btn-primary" to="/visit">
          Add visit note
        </Link>
      </div>

      {recent.length > 0 && !debounced ? (
        <div className="chip-row" aria-label="Recently opened">
          <span className="chip-label">Recent</span>
          {recent.map((item) => (
            <Link key={item.patient_id} className="chip" to={`/patients/${item.patient_id}`}>
              {item.patient_id}
            </Link>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {!error && patients === null ? <p className="muted">Loading patients…</p> : null}

      {patients && patients.length === 0 ? (
        <div className="empty soft">
          <p>
            {debounced
              ? `No patients match “${debounced}”.`
              : "No patients on file yet."}
          </p>
          {!debounced ? (
            <Link className="text-link" to="/visit">
              Add visit note
            </Link>
          ) : null}
        </div>
      ) : null}

      {patients && patients.length > 0 ? (
        <>
          <div className="table-wrap">
            <table>
              <caption>
                Showing {pageStart}–{pageEnd} of {total}
                {debounced ? ` for “${debounced}”` : ""}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Patient</th>
                  <th scope="col">Sex</th>
                  <th scope="col">Conditions</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {patients.map((patient) => (
                  <tr key={patient.patient_id}>
                    <td>
                      <button
                        type="button"
                        className="patient-link linkish"
                        onClick={() => openPatient(patient)}
                      >
                        <strong>{patient.patient_id}</strong>
                        <span>{patient.synthetic_name}</span>
                      </button>
                    </td>
                    <td>{patient.sex}</td>
                    <td className="conditions-cell">{truncateConditions(patient.conditions)}</td>
                    <td>
                      <div className="row-actions">
                        <Link
                          className="text-link"
                          to={`/visit?patient=${encodeURIComponent(patient.patient_id)}`}
                        >
                          Add visit note
                        </Link>
                        <Link
                          className="text-link"
                          to={`/patients/${patient.patient_id}?prepare=1`}
                        >
                          Prepare evidence pack
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <button
              type="button"
              className="btn btn-ghost sm"
              disabled={offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
            >
              Previous
            </button>
            <span className="muted">
              Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
            </span>
            <button
              type="button"
              className="btn btn-ghost sm"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((value) => value + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
