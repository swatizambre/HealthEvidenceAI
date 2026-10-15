import { FormEvent, useEffect, useState } from "react";
import { askChart, getDoctorBrief, type DoctorBrief } from "../api";
import { Button, Notice, Skeleton } from "../ui";
import { SafetyFindingsList } from "./SafetyChecks";

/** 30-second chart brief with sources, risk flags, medicine reconciliation, ask-with-sources. */
export function DoctorBriefPanel({ patientId }: { patientId: string }) {
  const [brief, setBrief] = useState<DoctorBrief | null>(null);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("any contrast reaction?");
  const [answers, setAnswers] = useState<{ text: string; source: string }[]>([]);
  const [askBusy, setAskBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBrief(null);
    getDoctorBrief(patientId)
      .then((body) => {
        if (!cancelled) setBrief(body);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [patientId]);

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    setAskBusy(true);
    setError("");
    try {
      const body = await askChart(patientId, question);
      setAnswers(body.answers);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask failed.");
    } finally {
      setAskBusy(false);
    }
  }

  if (error && !brief) {
    return <Notice tone="warning">{error}</Notice>;
  }
  if (!brief) {
    return <Skeleton lines={4} label="Loading doctor brief" />;
  }

  return (
    <section className="panel doctor-brief-panel" aria-label="Doctor brief">
      <h2>Doctor view — 30-second brief</h2>
      <p className="muted small">{brief.disclaimer}</p>
      {(brief.safety_findings || []).length > 0 ? (
        <>
          <h3>Worth a look across hospitals</h3>
          <SafetyFindingsList findings={brief.safety_findings || []} audience="doctor" />
        </>
      ) : null}
      <ul className="stack-list">
        {brief.brief_lines.map((line, index) => (
          <li key={`${line.source}-${index}`}>
            <p>{line.text}</p>
            <p className="muted small mono">Source: {line.source}</p>
          </li>
        ))}
      </ul>
      {brief.risk_flags.length > 0 ? (
        <>
          <h3>Risk flags</h3>
          <ul className="chip-row" aria-label="Risk flags">
            {brief.risk_flags.map((flag) => (
              <li key={`${flag.kind}-${flag.label}`}>
                <span className="chip chip-static" title={flag.source}>
                  {flag.kind}: {flag.label}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <h3>Medicines</h3>
      <ul className="stack-list">
        {(brief.medications.medications || []).slice(0, 12).map((med) => (
          <li key={`${med.name}-${med.generic_key}`}>
            {med.name} · {med.dose} · {med.status}
            <span className="muted small"> → {med.generic_key || "—"}</span>
          </li>
        ))}
      </ul>
      {(brief.medications.duplicate_groups || []).length > 0 ? (
        <Notice tone="warning" title="Possible duplicate medicines">
          {(brief.medications.duplicate_groups || [])
            .map((group) => `${group.generic_key}: ${group.names.join(", ")}`)
            .join(" · ")}
        </Notice>
      ) : null}
      <p className="muted small">{brief.medications.disclaimer}</p>
      <form className="help-form" onSubmit={onAsk}>
        <label className="sr-only" htmlFor="chart-ask">
          Ask the chart
        </label>
        <input
          id="chart-ask"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask with sources — e.g. any contrast reaction?"
        />
        <Button type="submit" size="sm" variant="primary" loading={askBusy}>
          Ask
        </Button>
      </form>
      {answers.length > 0 ? (
        <ul className="stack-list">
          {answers.map((item, index) => (
            <li key={`${item.source}-${index}`}>
              <p>{item.text}</p>
              <p className="muted small mono">Source: {item.source}</p>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
