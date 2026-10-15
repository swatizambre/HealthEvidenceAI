import { FormEvent, useEffect, useState } from "react";
import {
  getAbdmStatus,
  getMyEmergencyCard,
  patchMyEmergencyCard,
  type EmergencyCard,
} from "../api";
import { useRole } from "../roleContext";
import { Button, Notice, Skeleton } from "../ui";

export function EmergencyCardPage() {
  const { isPatient } = useRole();
  const [card, setCard] = useState<EmergencyCard | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [bloodGroup, setBloodGroup] = useState("");
  const [implants, setImplants] = useState("");
  const [notes, setNotes] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [abdmMessage, setAbdmMessage] = useState("");

  useEffect(() => {
    if (!isPatient) return;
    getMyEmergencyCard()
      .then((body) => {
        setCard(body);
        setBloodGroup(body.blood_group || "");
        setImplants(body.implants || "");
        setNotes(body.notes || "");
      })
      .catch((err: Error) => setError(err.message));
    getAbdmStatus()
      .then((body) => setAbdmMessage(body.message))
      .catch(() => setAbdmMessage(""));
  }, [isPatient]);

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
          relation: "emergency",
        });
      }
      const next = await patchMyEmergencyCard({
        blood_group: bloodGroup,
        implants,
        notes,
        emergency_contacts: contacts.slice(-8),
      });
      setCard(next);
      setContactName("");
      setContactPhone("");
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

  return (
    <div className="page emergency-card-page">
      <header className="page-header">
        <h1>Emergency card</h1>
        <p className="muted">
          Critical allergies, medicines, and contacts for any clinician — with a QR payload for
          demo offline handoff.
        </p>
      </header>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <section className="panel emergency-card-preview" aria-label="Emergency summary">
        <h2>{card.display_name}</h2>
        <p className="muted small">
          {card.patient_id} · {card.sex} · DOB {card.date_of_birth}
        </p>
        <p>
          <strong>Blood group:</strong> {card.blood_group || "Not recorded"}
        </p>
        <p>
          <strong>Allergies:</strong> {card.allergies.length ? card.allergies.join("; ") : "None listed"}
        </p>
        <p>
          <strong>Medicines:</strong>{" "}
          {card.medications.length
            ? card.medications.map((item) => `${item.name} ${item.dose}`).join("; ")
            : "None listed"}
        </p>
        <p>
          <strong>Conditions:</strong>{" "}
          {card.conditions.length ? card.conditions.join("; ") : "None listed"}
        </p>
        <p>
          <strong>Implants:</strong> {card.implants || "None listed"}
        </p>
        <p className="mono small">QR payload: {card.qr_payload}</p>
        <p className="muted small">{card.disclaimer}</p>
        <Button size="sm" onClick={() => window.print()}>
          Print / save offline
        </Button>
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
          <input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} />
        </label>
        <div className="span-2">
          <Button type="submit" variant="primary" loading={saving}>
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
