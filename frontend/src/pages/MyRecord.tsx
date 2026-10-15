import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getLifelongSummary, type LifelongEvent, type LifelongSummary } from "../api";
import { PrivacyRights } from "../components/PrivacyRights";
import { useRole } from "../roleContext";
import { Button, ButtonLink, EmptyState, Notice, Skeleton } from "../ui";

const CATEGORY_LABEL: Record<string, string> = {
  encounter: "Visit",
  visit: "Visit",
  condition: "Health condition",
  diagnosis: "Health condition",
  procedure: "Procedure or surgery",
  medication: "Medicine",
  lab: "Test result",
  lab_result: "Test result",
  imaging: "Scan or X-ray",
  immunization: "Vaccine",
  allergy: "Allergy",
};

function categoryLabel(value: string): string {
  const key = value.trim().toLowerCase().replace(/\s+/g, "_");
  return CATEGORY_LABEL[key] || value.replace(/_/g, " ");
}

function yearLabel(value: string | null): string {
  return value ? value.slice(0, 4) : "Ongoing";
}

/** The DEMO disclaimer is shown once at the top; strip repeats from briefs and events. */
function withoutDisclaimer(text: string | null | undefined, disclaimer: string): string {
  const value = (text || "").trim();
  if (!disclaimer) return value;
  return value.split(disclaimer).join(" ").replace(/\s{2,}/g, " ").trim();
}

function EventRow({
  event,
  markDemo,
  disclaimer,
}: {
  event: LifelongEvent;
  markDemo: boolean;
  disclaimer: string;
}) {
  const why = withoutDisclaimer(event.why_it_matters, disclaimer);
  const labels = event.disorders ?? [];
  return (
    <li className="record-event">
      <span className="event-when">{yearLabel(event.occurred_on)}</span>
      <div className="record-event-body">
        <p className="record-event-title">
          <strong>{event.title}</strong>
          {markDemo && event.demo_synthetic ? <span className="tag">Example</span> : null}
        </p>
        <p className="muted small">
          {categoryLabel(event.category)}
          {event.facility_name ? `, ${event.facility_name}` : ""}
        </p>
        {event.summary ? <p>{event.summary}</p> : null}
        {why ? <p className="muted small">Why it matters: {why}</p> : null}
        {labels.length > 0 ? (
          <div className="chip-row" aria-label="Related to">
            {labels.map((label) => (
              <span key={label} className="chip chip-static">
                {label}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </li>
  );
}

export function MyRecordPage() {
  const { myPatientId, setMyPatientId, isPatient } = useRole();
  const [searchParams] = useSearchParams();
  const queryPatient = searchParams.get("patient") || "";
  const activePatientId = queryPatient && /^PAT-\d{6}$/i.test(queryPatient) ? queryPatient.toUpperCase() : myPatientId;
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
        if (!cancelled) setSummary(body);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load the record.");
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activePatientId]);

  const labels = useMemo(() => {
    if (!summary) return [];
    if (summary.disorders?.length) return summary.disorders;
    if (summary.by_disorder?.length) return summary.by_disorder.map((group) => group.key);
    const collected = new Set<string>();
    for (const event of summary.events) for (const label of event.disorders ?? []) collected.add(label);
    return Array.from(collected).sort((a, b) => a.localeCompare(b));
  }, [summary]);

  const visibleEvents = useMemo(() => {
    if (!summary) return [];
    if (labelFilter === "all") return summary.events;
    return summary.events.filter((event) => (event.disorders ?? []).includes(labelFilter));
  }, [summary, labelFilter]);

  const mixedDemo = Boolean(
    summary && summary.events.some((event) => event.demo_synthetic) && summary.events.some((event) => !event.demo_synthetic),
  );

  const disclaimer = (summary?.demo_synthetic_disclaimer || "").trim();
  const brief = summary
    ? withoutDisclaimer(isPatient ? summary.patient_brief : summary.doctor_brief, disclaimer)
    : "";

  function onOpen(event: FormEvent) {
    event.preventDefault();
    if (!isPatient) setMyPatientId(patientId);
  }

  return (
    <section className="page record-page">
      {summary?.includes_demo_synthetic ? (
        <Notice tone="warning" title="Demo record">
          {summary.demo_synthetic_disclaimer ||
            (mixedDemo
              ? "Events marked “Example” are invented to show how the record works. They are not from your chart."
              : "The history below is invented to show how the record works. It is not from your chart.")}{" "}
          Do not use it for care or insurance decisions.
        </Notice>
      ) : null}

      <header className="page-head">
        <div>
          <h1 className="page-title">{isPatient ? "My record" : "Lifelong record"}</h1>
          <p className="page-sub">
            {isPatient
              ? "Your visits, tests and treatments from every hospital and clinic, in one place."
              : "Continuity across facilities. Filter by health topic."}
          </p>
        </div>
        <div className="button-row">
          <ButtonLink variant="primary" icon="note" to={`/visit?patient=${encodeURIComponent(myPatientId)}`}>
            Add a visit
          </ButtonLink>
          <ButtonLink to={`/patients/${myPatientId}`}>{isPatient ? "Full chart" : "Open chart"}</ButtonLink>
        </div>
      </header>

      {!isPatient ? (
        <form className="inline-form" onSubmit={onOpen}>
          <label className="field">
            <span>Patient ID</span>
            <input value={patientId} onChange={(e) => setPatientId(e.target.value.trim().toUpperCase())} placeholder="PAT-000001" />
          </label>
          <Button type="submit">Open</Button>
        </form>
      ) : null}

      {error ? <Notice tone="danger" title="Could not load the record">{error}</Notice> : null}
      {busy && !summary ? <Skeleton lines={5} label="Loading record" /> : null}

      {summary ? (
        <section className="panel" aria-labelledby="history-title">
          <div className="section-bar">
            <div>
              <h2 className="section-title" id="history-title">
                {summary.patient_name}
              </h2>
              <p className="muted small">
                {summary.patient_id}, {visibleEvents.length} event{visibleEvents.length === 1 ? "" : "s"}
                {summary.facilities_count ? `, ${summary.facilities_count} facilit${summary.facilities_count === 1 ? "y" : "ies"}` : ""}
              </p>
            </div>
          </div>
          {brief ? <p className="lead">{brief}</p> : null}
          {labels.length > 0 ? (
            <div className="chip-row" role="group" aria-label="Filter by health topic">
              {["all", ...labels].map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`chip${labelFilter === label ? " is-active" : ""}`}
                  aria-pressed={labelFilter === label}
                  onClick={() => setLabelFilter(label)}
                >
                  {label === "all" ? "Everything" : label}
                </button>
              ))}
            </div>
          ) : null}
          {visibleEvents.length === 0 ? (
            <EmptyState icon="doc" title="Nothing recorded for this topic" />
          ) : (
            <ul className="record-events">
              {visibleEvents.map((event) => (
                <EventRow key={event.event_id} event={event} markDemo={mixedDemo} disclaimer={disclaimer} />
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {isPatient && /^PAT-\d{6}$/.test(myPatientId) ? <PrivacyRights patientId={myPatientId} /> : null}
      {!isPatient ? (
        <p className="muted small">
          <Link to={`/patients/${encodeURIComponent(activePatientId)}`}>Back to the chart</Link>
        </p>
      ) : null}
    </section>
  );
}
