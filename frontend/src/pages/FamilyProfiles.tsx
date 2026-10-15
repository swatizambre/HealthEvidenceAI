import { FormEvent, useEffect, useState } from "react";
import { createMyFamily, listMyFamily, type CareRelationship } from "../api";
import { useRole } from "../roleContext";
import { Button, Notice } from "../ui";

export function FamilyProfilesPage() {
  const { isPatient } = useRole();
  const [rows, setRows] = useState<CareRelationship[]>([]);
  const [name, setName] = useState("");
  const [relationshipType, setRelationshipType] = useState("caregiver");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const body = await listMyFamily();
    setRows(body.relationships);
  }

  useEffect(() => {
    if (!isPatient) return;
    refresh().catch((err: Error) => setError(err.message));
  }, [isPatient]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await createMyFamily({
        related_display_name: name,
        relationship_type: relationshipType,
        access_level: "view",
      });
      setName("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add family profile.");
    } finally {
      setBusy(false);
    }
  }

  if (!isPatient) {
    return <Notice tone="warning">Sign in as Patient to manage family profiles.</Notice>;
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Family & caregivers</h1>
        <p className="muted">
          Demo stubs for parents, children, and caregivers. Full multi-account access comes later.
        </p>
      </header>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <form className="panel form-grid" onSubmit={onCreate}>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
        </label>
        <label className="field">
          <span>Relationship</span>
          <select value={relationshipType} onChange={(e) => setRelationshipType(e.target.value)}>
            <option value="parent">Parent</option>
            <option value="child">Child</option>
            <option value="spouse">Spouse</option>
            <option value="caregiver">Caregiver</option>
            <option value="other">Other</option>
          </select>
        </label>
        <div className="span-2">
          <Button type="submit" variant="primary" loading={busy}>
            Add profile
          </Button>
        </div>
      </form>
      <section className="panel">
        <h2>Linked profiles</h2>
        {rows.length === 0 ? (
          <p className="muted">No family or caregiver profiles yet.</p>
        ) : (
          <ul className="stack-list">
            {rows.map((row) => (
              <li key={row.relationship_id}>
                <strong>{row.related_display_name}</strong>
                <span className="muted small">
                  {" "}
                  · {row.relationship_type} · {row.access_level}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
