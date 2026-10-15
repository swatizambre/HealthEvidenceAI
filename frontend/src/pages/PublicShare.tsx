import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getPublicShare } from "../api";
import { Notice, Skeleton } from "../ui";

export function PublicSharePage() {
  const { token = "" } = useParams();
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    getPublicShare(token)
      .then(setPayload)
      .catch((err: Error) => setError(err.message));
  }, [token]);

  if (error) {
    return (
      <div className="page">
        <Notice tone="danger">{error}</Notice>
      </div>
    );
  }
  if (!payload) {
    return (
      <div className="page">
        <Skeleton lines={5} />
      </div>
    );
  }

  const allergies = (payload.allergies as string[] | undefined) || [];
  const medications = (payload.medications as { name: string; dose: string }[] | undefined) || [];
  const conditions = (payload.conditions as string[] | undefined) || [];

  return (
    <div className="page">
      <header className="page-header">
        <h1>Shared health summary</h1>
        <p className="muted">
          {(payload.display_name as string) || "Patient"} · {(payload.patient_id as string) || ""}
        </p>
      </header>
      <section className="panel">
        <p>
          <strong>Blood group:</strong> {(payload.blood_group as string) || "—"}
        </p>
        <p>
          <strong>Allergies:</strong> {allergies.length ? allergies.join("; ") : "—"}
        </p>
        <p>
          <strong>Medicines:</strong>{" "}
          {medications.length
            ? medications.map((item) => `${item.name} ${item.dose}`).join("; ")
            : "—"}
        </p>
        <p>
          <strong>Conditions:</strong> {conditions.length ? conditions.join("; ") : "—"}
        </p>
        <p className="muted small">{String(payload.disclaimer || "")}</p>
      </section>
    </div>
  );
}
