import { useEffect, useState } from "react";
import { getSafetyChecks, type SafetyChecks, type SafetyFinding } from "../api";
import { Notice, Skeleton } from "../ui";

const KIND_LABEL: Record<string, string> = {
  allergy_conflict: "Allergy and medicine",
  duplicate_medicine: "Same medicine twice",
  test_not_repeated: "Test not repeated",
};

function FindingItem({ finding, audience }: { finding: SafetyFinding; audience: "patient" | "doctor" }) {
  const high = finding.severity === "high";
  return (
    <li className={`safety-finding${high ? " is-high" : ""}`}>
      <p className="safety-kind">{KIND_LABEL[finding.kind] || finding.kind.replace(/_/g, " ")}</p>
      <p className="safety-title">{finding.title}</p>
      <p>{audience === "patient" ? finding.patient_text : finding.doctor_text}</p>
      {finding.sources.length > 0 ? (
        <details className="safety-sources">
          <summary>
            {finding.sources.length === 1 ? "1 source" : `${finding.sources.length} sources`}
          </summary>
          <ul>
            {finding.sources.map((source) => (
              <li key={source.ref}>
                {source.label} <span className="muted small mono">{source.ref}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </li>
  );
}

/** Findings list, worded for the patient (questions) or the doctor (review items). */
export function SafetyFindingsList({
  findings,
  audience,
}: {
  findings: SafetyFinding[];
  audience: "patient" | "doctor";
}) {
  return (
    <ul className="safety-findings">
      {findings.map((finding) => (
        <FindingItem key={finding.id} finding={finding} audience={audience} />
      ))}
    </ul>
  );
}

/** Patient-facing card: "Things to ask your doctor", built from every hospital's records. */
export function SafetyChecksCard({ patientId }: { patientId: string }) {
  const [data, setData] = useState<SafetyChecks | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError("");
    getSafetyChecks(patientId)
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not run the checks.");
      });
    return () => {
      cancelled = true;
    };
  }, [patientId]);

  if (error) return <Notice tone="warning" title="Safety checks unavailable">{error}</Notice>;
  if (!data) return <Skeleton lines={2} label="Checking your records" />;

  const count = data.findings.length;
  const checked = data.checked;
  return (
    <section className="panel safety-card" aria-labelledby="safety-title">
      <h2 className="section-title" id="safety-title">
        {count === 0 ? "Nothing to ask your doctor right now" : `${count} thing${count === 1 ? "" : "s"} to ask your doctor`}
      </h2>
      <p className="muted small">
        Checked {checked.active_medicines ?? 0} current medicines, {checked.lab_results ?? 0} test results and{" "}
        {checked.allergies ?? 0} allergies from every place you were seen.
      </p>
      {count > 0 ? <SafetyFindingsList findings={data.findings} audience="patient" /> : null}
      <p className="muted small">{data.disclaimer}</p>
    </section>
  );
}
