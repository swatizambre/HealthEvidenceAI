import { FormEvent, useEffect, useState } from "react";
import {
  ackEmergencyAlert,
  getAbdmStatus,
  getMyEmergencyAlerts,
  getMyEmergencyCard,
  patchMyEmergencyCard,
  rotateMyEmergencyLink,
  type EmergencyAlert,
  type EmergencyCard,
} from "../api";
import { QrCode } from "../components/QrCode";
import { forgetSavedCard, loadSavedCard, saveCard } from "../offlineCard";
import { useRole } from "../roleContext";
import { Button, Notice, Skeleton } from "../ui";

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function mapLink(alert: EmergencyAlert): string | null {
  if (alert.latitude === null || alert.longitude === null) return null;
  return `https://www.openstreetmap.org/?mlat=${alert.latitude}&mlon=${alert.longitude}#map=16/${alert.latitude}/${alert.longitude}`;
}

function AlertRow({ alert, onAck }: { alert: EmergencyAlert; onAck: (id: string) => void }) {
  const map = mapLink(alert);
  const whose = alert.whose === "you" ? "Your card" : `${alert.whose}'s card`;
  return (
    <li className={`emergency-alert${alert.acknowledged ? "" : " is-new"}`}>
      <div className="emergency-alert-body">
        <p>
          <strong>{whose} was opened</strong> · {when(alert.opened_at)}
        </p>
        {alert.place_note ? <p>Where: {alert.place_note}</p> : <p className="muted small">No place shared yet.</p>}
        {map ? (
          <a href={map} target="_blank" rel="noreferrer">
            Open map
          </a>
        ) : null}
      </div>
      {alert.acknowledged ? (
        <span className="muted small">Seen</span>
      ) : (
        <Button size="sm" onClick={() => onAck(alert.event_id)}>
          Mark seen
        </Button>
      )}
    </li>
  );
}

export function EmergencyCardPage() {
  const { isPatient } = useRole();
  const [card, setCard] = useState<EmergencyCard | null>(null);
  const [offlineFrom, setOfflineFrom] = useState("");
  const [kept, setKept] = useState(() => loadSavedCard() !== null);
  const [alerts, setAlerts] = useState<EmergencyAlert[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [bloodGroup, setBloodGroup] = useState("");
  const [implants, setImplants] = useState("");
  const [notes, setNotes] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [contactRelation, setContactRelation] = useState("");
  const [abdmMessage, setAbdmMessage] = useState("");

  function apply(next: EmergencyCard) {
    setCard(next);
    setOfflineFrom("");
    setBloodGroup(next.blood_group || "");
    setImplants(next.implants || "");
    setNotes(next.notes || "");
    if (loadSavedCard() !== null) saveCard(next);
  }

  useEffect(() => {
    if (!isPatient) return;
    getMyEmergencyCard()
      .then(apply)
      .catch((err: Error) => {
        // No signal: show the copy kept on this phone, if the patient saved one.
        const saved = loadSavedCard();
        if (saved) {
          setCard(saved.card);
          setOfflineFrom(saved.savedAt);
        } else {
          setError(err.message);
        }
      });
    getMyEmergencyAlerts()
      .then((body) => setAlerts(body.alerts))
      .catch(() => setAlerts([]));
    getAbdmStatus()
      .then((body) => setAbdmMessage(body.message))
      .catch(() => setAbdmMessage(""));
  }, [isPatient]);

  function onKeepToggle(next: boolean) {
    if (!card) return;
    if (next) {
      const saved = saveCard(card);
      setKept(saved !== null);
      if (!saved) setError("This browser blocked saving. Print the wallet card instead.");
    } else {
      forgetSavedCard();
      setKept(false);
    }
  }

  async function onAlertFamily(next: boolean) {
    try {
      apply(await patchMyEmergencyCard({ alert_family: next }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    }
  }

  async function onRotate() {
    if (!window.confirm("Make a new QR link? Printed cards and saved copies with the old link stop working.")) return;
    setRotating(true);
    try {
      apply(await rotateMyEmergencyLink());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not make a new link.");
    } finally {
      setRotating(false);
    }
  }

  async function onAck(eventId: string) {
    try {
      const updated = await ackEmergencyAlert(eventId);
      setAlerts((items) => items.map((item) => (item.event_id === eventId ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update.");
    }
  }

  async function onSave(event: FormEvent) {
    event.preventDefault();
    if (!card) return;
    setSaving(true);
    setError("");
    try {
      const contacts = [...(card.emergency_contacts || [])];
      if (contactName.trim()) {
        contacts.push({
          name: contactName.trim(),
          phone: contactPhone.trim(),
          relation: contactRelation.trim() || "family",
        });
      }
      apply(
        await patchMyEmergencyCard({
          blood_group: bloodGroup,
          implants,
          notes,
          emergency_contacts: contacts.slice(-8),
        }),
      );
      setContactName("");
      setContactPhone("");
      setContactRelation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  if (!isPatient) {
    return <Notice tone="warning">Sign in as Patient to manage the emergency card.</Notice>;
  }
  if (error && !card) {
    return <Notice tone="danger">{error}</Notice>;
  }
  if (!card) {
    return <Skeleton lines={6} />;
  }

  const newAlerts = alerts.filter((item) => !item.acknowledged);
  const modules = card.qr_modules || [];

  return (
    <div className="page emergency-card-page">
      <header className="page-header">
        <h1>Emergency card</h1>
        <p className="muted">
          Any doctor or bystander can scan the QR, with no app and no sign-in, and see what they need in an emergency.
        </p>
      </header>

      {offlineFrom ? (
        <Notice tone="info" title="No connection — showing the copy kept on this phone">
          Saved {when(offlineFrom)}.
        </Notice>
      ) : null}
      {newAlerts.length ? (
        <Notice tone="danger" title={`Emergency card opened ${newAlerts.length === 1 ? "once" : `${newAlerts.length} times`}`}>
          See below for when and where.
        </Notice>
      ) : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}

      <section className="panel emergency-wallet" aria-label="Emergency card">
        <div className="emergency-wallet-head">
          <span>EMERGENCY · आपातकालीन</span>
        </div>
        <div className="emergency-wallet-body">
          <div className="emergency-wallet-facts">
            <p className="emergency-wallet-name">{card.display_name}</p>
            <p className="muted small">
              {card.sex} · born {card.date_of_birth}
            </p>
            <div className="chip-row">
              <span className="chip chip-static emergency-pill">Blood {card.blood_group || "not recorded"}</span>
              {card.allergies.length ? (
                card.allergies.slice(0, 3).map((item) => (
                  <span key={item} className="chip chip-static emergency-pill">
                    {item}
                  </span>
                ))
              ) : (
                <span className="chip chip-static">No allergies recorded</span>
              )}
            </div>
            <p>
              <strong>Medicines:</strong>{" "}
              {card.medications.length
                ? card.medications
                    .slice(0, 5)
                    .map((item) => `${item.name} ${item.dose}`.trim())
                    .join("; ")
                : "None listed"}
            </p>
            {card.implants ? (
              <p>
                <strong>Implants:</strong> {card.implants}
              </p>
            ) : null}
            {card.emergency_contacts.length ? (
              <p>
                <strong>Call:</strong>{" "}
                {card.emergency_contacts
                  .map((item) => [item.name, item.relation && `(${item.relation})`, item.phone].filter(Boolean).join(" "))
                  .join("; ")}
              </p>
            ) : null}
          </div>
          {modules.length ? (
            <figure className="emergency-wallet-qr">
              <QrCode modules={modules} label="QR code that opens this emergency card" />
              <figcaption className="muted small">Scan for full card</figcaption>
            </figure>
          ) : null}
        </div>
        <p className="muted small emergency-wallet-foot">{card.disclaimer}</p>
      </section>

      <section className="panel emergency-settings" aria-label="Card settings">
        <label className="toggle-row">
          <input type="checkbox" checked={kept} onChange={(event) => onKeepToggle(event.target.checked)} />
          <span>
            <strong>Keep on this phone</strong>
            <span className="muted small"> Opens with no signal. Turn off on a shared phone.</span>
          </span>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={card.alert_family !== false}
            disabled={Boolean(offlineFrom)}
            onChange={(event) => void onAlertFamily(event.target.checked)}
          />
          <span>
            <strong>Alert me and my family when it's opened</strong>
            <span className="muted small"> The person who opens it can add where you are.</span>
          </span>
        </label>
        <div className="button-row">
          <Button size="sm" onClick={() => window.print()}>
            Print wallet card
          </Button>
          <Button size="sm" onClick={() => void onRotate()} loading={rotating} disabled={Boolean(offlineFrom)}>
            Make a new QR link
          </Button>
        </div>
        <p className="muted small">
          SMS and WhatsApp alerts need a messaging provider and are not switched on yet; alerts appear in the app.
        </p>
      </section>

      <section className="panel" aria-labelledby="alerts-title">
        <h2 id="alerts-title">Who opened it</h2>
        {alerts.length ? (
          <ul className="emergency-alerts">
            {alerts.map((alert) => (
              <AlertRow key={alert.event_id} alert={alert} onAck={(id) => void onAck(id)} />
            ))}
          </ul>
        ) : (
          <p className="muted">Nobody has opened your card or your family's cards.</p>
        )}
      </section>

      <form className="panel form-grid" onSubmit={onSave}>
        <h2 className="span-2">Edit card</h2>
        <label className="field">
          <span>Blood group</span>
          <input value={bloodGroup} onChange={(e) => setBloodGroup(e.target.value)} maxLength={16} />
        </label>
        <label className="field span-2">
          <span>Implants / devices</span>
          <input value={implants} onChange={(e) => setImplants(e.target.value)} maxLength={500} />
        </label>
        <label className="field span-2">
          <span>Notes for responders</span>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </label>
        <label className="field">
          <span>Add contact name</span>
          <input value={contactName} onChange={(e) => setContactName(e.target.value)} />
        </label>
        <label className="field">
          <span>Contact phone</span>
          <input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} inputMode="tel" />
        </label>
        <label className="field">
          <span>Relation</span>
          <input value={contactRelation} onChange={(e) => setContactRelation(e.target.value)} placeholder="daughter" />
        </label>
        <div className="span-2">
          <Button type="submit" variant="primary" loading={saving} disabled={Boolean(offlineFrom)}>
            Save emergency card
          </Button>
        </div>
      </form>
      {abdmMessage ? (
        <Notice tone="info">
          <strong>Link ABHA (sandbox)</strong> — {abdmMessage}
        </Notice>
      ) : null}
    </div>
  );
}
