import { FormEvent, useEffect, useState } from "react";
import { createMyShare, listMyShares, revokeMyShare, type RecordShare } from "../api";
import { useRole } from "../roleContext";
import { Button, Notice } from "../ui";

const SCOPE_OPTIONS = [
  { id: "emergency", label: "Emergency card" },
  { id: "allergies", label: "Allergies" },
  { id: "medications", label: "Medicines" },
  { id: "conditions", label: "Conditions" },
];

export function ShareWithDoctorPage() {
  const { isPatient } = useRole();
  const [shares, setShares] = useState<RecordShare[]>([]);
  const [scopes, setScopes] = useState<string[]>(["emergency", "medications", "allergies"]);
  const [hours, setHours] = useState(24);
  const [label, setLabel] = useState("Doctor share");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastLink, setLastLink] = useState("");

  async function refresh() {
    const body = await listMyShares();
    setShares(body.shares);
  }

  useEffect(() => {
    if (!isPatient) return;
    refresh().catch((err: Error) => setError(err.message));
  }, [isPatient]);

  function toggleScope(id: string) {
    setScopes((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await createMyShare({ scopes, hours, label });
      if (created.path) {
        setLastLink(`${window.location.origin}${created.path}`);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create share.");
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(shareId: string) {
    setBusy(true);
    try {
      await revokeMyShare(shareId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke.");
    } finally {
      setBusy(false);
    }
  }

  if (!isPatient) {
    return <Notice tone="warning">Sign in as Patient to share your record.</Notice>;
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Share with a doctor</h1>
        <p className="muted">Time-limited link. Choose what to show. Revoke anytime. Views are logged.</p>
      </header>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <form className="panel form-grid" onSubmit={onCreate}>
        <label className="field span-2">
          <span>Label</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={160} />
        </label>
        <label className="field">
          <span>Expires in (hours)</span>
          <input
            type="number"
            min={1}
            max={336}
            value={hours}
            onChange={(e) => setHours(Number(e.target.value) || 24)}
          />
        </label>
        <fieldset className="span-2">
          <legend>What to show</legend>
          <div className="chip-row">
            {SCOPE_OPTIONS.map((item) => (
              <label key={item.id} className="chip">
                <input
                  type="checkbox"
                  checked={scopes.includes(item.id)}
                  onChange={() => toggleScope(item.id)}
                />{" "}
                {item.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="span-2">
          <Button type="submit" variant="primary" loading={busy} disabled={!scopes.length}>
            Create share link
          </Button>
        </div>
        {lastLink ? (
          <p className="span-2 mono small">
            Latest link: <a href={lastLink}>{lastLink}</a>
          </p>
        ) : null}
      </form>
      <section className="panel">
        <h2>Your shares</h2>
        {shares.length === 0 ? (
          <p className="muted">No shares yet.</p>
        ) : (
          <ul className="stack-list">
            {shares.map((share) => (
              <li key={share.share_id}>
                <strong>{share.label || share.share_id}</strong>
                <span className="muted small">
                  {" "}
                  · expires {share.expires_at || "—"} · views {share.view_count}
                  {share.revoked_at ? " · revoked" : ""}
                </span>
                {!share.revoked_at ? (
                  <Button size="sm" onClick={() => void onRevoke(share.share_id)} disabled={busy}>
                    Revoke
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
