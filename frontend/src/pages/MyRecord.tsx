import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getLifelongSummary, type LifelongEvent, type LifelongSummary } from "../api";
import { PrivacyRights } from "../components/PrivacyRights";
import { useRole } from "../roleContext";

function yearLabel(value: string | null): string {
  if (!value) {
    return "Ongoing";
  }
  return value.slice(0, 4);
}

function EventCard({ event }: { event: LifelongEvent }) {
  const labels = event.disorders ?? [];
  const demo = Boolean(event.demo_synthetic);
  return (
    <li className={`lifelong-item${demo ? " lifelong-item-demo" : ""}`}>
      <div className="lifelong-when">{yearLabel(event.occurred_on)}</div>
      <div className="lifelong-body">
        <div className="lifelong-top">
          <strong>{event.title}</strong>
          <span className="badge neutral">{event.category}</span>
          {demo ? <span className="badge warn">DEMO ONLY</span> : null}
        </div>
        {labels.length > 0 ? (
          <div className="chip-row compact event-labels" aria-label="Labels">
            {labels.map((label) => (
              <span key={label} className="chip chip-static">
                {label}
              </span>
            ))}
          </div>
        ) : null}
        <p>{event.summary}</p>
        {event.why_it_matters ? <p className="hint">{event.why_it_matters}</p> : null}
      </div>
    </li>
  );
}

export function MyRecordPage() {
  const { myPatientId, setMyPatientId, isPatient } = useRole();
  const [searchParams] = useSearchParams();
  const queryPatient = searchParams.get("patient") || "";
  const activePatientId =
    queryPatient && /^PAT-\d{6}$/i.test(queryPatient)
      ? queryPatient.toUpperCase()
      : myPatientId;
  const [patientId, setPatientId] = useState(activePatientId);
  const [summary, setSummary] = useState<LifelongSummary | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [labelFilter, setLabelFilter] = useState("all");

  useEffect(() => {
    if (queryPatient && /^PAT-\d{6}$/i.test(queryPatient)) {
      setMyPatientId(queryPatient.toUpperCase());
    }
  }, [queryPatient, setMyPatientId]);

  useEffect(() => {
    setPatientId(activePatientId);
  }, [activePatientId]);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError("");
    setLabelFilter("all");
    getLifelongSummary(activePatientId)
      .then((body) => {
        if (!cancelled) {
          setSummary(body);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setBusy(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activePatientId]);

  const labels = useMemo(() => {
    if (!summary) {
      return [];
    }
    if (summary.disorders?.length) {
      return summary.disorders;
    }
    if (summary.by_disorder?.length) {
      return summary.by_disorder.map((group) => group.key);
    }
    const collected = new Set<string>();
    for (const event of summary.events) {
      for (const label of event.disorders ?? []) {
        collected.add(label);
      }
    }
    return Array.from(collected).sort((a, b) => a.localeCompare(b));
  }, [summary]);

  const visibleEvents = useMemo(() => {
    if (!summary) {
      return [];
    }
    if (labelFilter === "all") {
      return summary.events;
    }
    return summary.events.filter((event) => (event.disorders ?? []).includes(labelFilter));
  }, [summary, labelFilter]);

  function onLink(event: FormEvent) {
    event.preventDefault();
    if (isPatient) {
      return;
    }
    setMyPatientId(patientId);
  }

  return (
    <section className="page chart-page lifelong-page">
      <header className="lifelong-header">
        <div className="lifelong-header-copy">
          <p className="eyebrow">Lifelong health record</p>
          <h1 className="page-title">{isPatient ? "My record" : "Lifelong record"}</h1>
          <p className="page-subtitle">
            Continuity across facilities — filter by topic, then review matching visits and results.
          </p>
        </div>
        <div className="home-actions">
          <Link className="btn btn-primary" to={`/visit?patient=${encodeURIComponent(myPatientId)}`}>
            Add visit note
          </Link>
          <Link className="btn btn-ghost" to={`/patients/${myPatientId}`}>
            Full chart
          </Link>
        </div>
      </header>

      {!isPatient ? (
        <form className="inline-form lifelong-patient-picker" onSubmit={onLink}>
          <label>
            Patient ID
            <input
              value={patientId}
              onChange={(event) => setPatientId(event.target.value.trim().toUpperCase())}
              placeholder="PAT-000001"
            />
          </label>
          <button type="submit" className="btn btn-ghost">
            Open
          </button>
        </form>
      ) : (
        <p className="hint" role="status">
          Signed in as <strong>{myPatientId}</strong>
        </p>
      )}

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {busy && !summary ? <p className="muted">Loading lifelong history…</p> : null}

      {summary ? (
        <div className="panel lifelong-panel lifelong-board">
          <div className="lifelong-board-head">
            <div>
              <h2 className="panel-title">{summary.patient_name}</h2>
              <p className="muted">
                {summary.patient_id}
                {labels.length ? ` · ${labels.length} labels` : ""}
                {` · ${visibleEvents.length} events`}
              </p>
            </div>
          </div>

          {summary.includes_demo_synthetic ? (
            <p className="error lifelong-demo-banner" role="alert">
              {summary.demo_synthetic_disclaimer ||
                "DEMO ONLY — invented example history, not from this patient's chart. Do not use for care or insurance decisions."}
            </p>
          ) : null}

          {summary.doctor_brief || summary.patient_brief ? (
            <p className="hint lifelong-brief">
              {isPatient ? summary.patient_brief : summary.doctor_brief}
            </p>
          ) : null}

          <div className="lifelong-filter-bar" aria-label="Disorder label filter">
            <span className="chip-label">Filter</span>
            <div className="chip-row specialty-filter label-filter">
              <button
                type="button"
                className={`chip ${labelFilter === "all" ? "chip-active" : ""}`}
                onClick={() => setLabelFilter("all")}
              >
                All
              </button>
              {labels.map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`chip ${labelFilter === label ? "chip-active" : ""}`}
                  onClick={() => setLabelFilter(label)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {visibleEvents.length === 0 ? (
            <p className="muted">No clinical history for this label.</p>
          ) : (
            <ul className="lifelong-list">
              {visibleEvents.map((event) => (
                <EventCard key={event.event_id} event={event} />
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {isPatient && /^PAT-\d{6}$/.test(myPatientId) ? (
        <PrivacyRights patientId={myPatientId} />
      ) : null}
    </section>
  );
}
