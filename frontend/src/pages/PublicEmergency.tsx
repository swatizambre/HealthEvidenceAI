import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { addEmergencyPlace, openPublicEmergencyCard, type PublicEmergencyCard } from "../api";

type Lang = "en" | "hi";

const LABELS: Record<Lang, Record<string, string>> = {
  en: {
    title: "Emergency medical card",
    allergies: "Allergies",
    noAllergies: "None recorded",
    blood: "Blood group",
    conditions: "Health conditions",
    medicines: "Current medicines",
    implants: "Implants and devices",
    notes: "Notes from the patient",
    contacts: "Call family",
    none: "None recorded",
    whereTitle: "Tell the family where the patient is",
    whereHint: "Optional. Only the patient and family they chose will see this.",
    placeLabel: "Hospital or place",
    placeholder: "e.g. City Hospital, emergency ward",
    useLocation: "Add my location",
    locating: "Finding location…",
    locationAdded: "Location will be shared (about 100 m).",
    send: "Send to family",
    sent: "Sent. The family can see where the patient is.",
    alerted: "The patient's family has been told this card was opened.",
    notAlerted: "The patient chose not to alert family when this card is opened.",
    loading: "Opening emergency card…",
    years: "years",
  },
  hi: {
    title: "आपातकालीन मेडिकल कार्ड",
    allergies: "एलर्जी",
    noAllergies: "कोई दर्ज नहीं",
    blood: "ब्लड ग्रुप",
    conditions: "बीमारियाँ",
    medicines: "चल रही दवाइयाँ",
    implants: "इम्प्लांट और उपकरण",
    notes: "मरीज़ के नोट",
    contacts: "परिवार को कॉल करें",
    none: "कोई दर्ज नहीं",
    whereTitle: "परिवार को बताएँ कि मरीज़ कहाँ है",
    whereHint: "वैकल्पिक। यह केवल मरीज़ और उनके चुने हुए परिवार को दिखेगा।",
    placeLabel: "अस्पताल या जगह",
    placeholder: "जैसे: सिटी हॉस्पिटल, इमरजेंसी वार्ड",
    useLocation: "मेरी लोकेशन जोड़ें",
    locating: "लोकेशन ढूँढ रहे हैं…",
    locationAdded: "लोकेशन साझा होगी (लगभग 100 मीटर)।",
    send: "परिवार को भेजें",
    sent: "भेज दिया। परिवार देख सकता है कि मरीज़ कहाँ है।",
    alerted: "मरीज़ के परिवार को बता दिया गया है कि यह कार्ड खोला गया।",
    notAlerted: "मरीज़ ने कार्ड खुलने पर परिवार को सूचना न देने का चुनाव किया है।",
    loading: "आपातकालीन कार्ड खुल रहा है…",
    years: "वर्ष",
  },
};

/** What a doctor, ambulance crew or bystander sees after scanning the patient's card. No sign-in. */
export function PublicEmergencyPage() {
  const { token = "" } = useParams();
  const [lang, setLang] = useState<Lang>("en");
  const [card, setCard] = useState<PublicEmergencyCard | null>(null);
  const [error, setError] = useState("");
  const [place, setPlace] = useState("");
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [placeError, setPlaceError] = useState("");
  const t = LABELS[lang];

  useEffect(() => {
    let cancelled = false;
    openPublicEmergencyCard(token)
      .then((body) => {
        if (!cancelled) setCard(body);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not open this card.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  function onLocate() {
    if (!("geolocation" in navigator)) {
      setPlaceError("Location is not available on this device.");
      return;
    }
    setLocating(true);
    setPlaceError("");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({ latitude: position.coords.latitude, longitude: position.coords.longitude });
        setLocating(false);
      },
      () => {
        setPlaceError("Location was not shared. You can type the place instead.");
        setLocating(false);
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!card || (!place.trim() && !coords)) return;
    setSending(true);
    setPlaceError("");
    try {
      await addEmergencyPlace(token, card.event_id, {
        place_note: place.trim(),
        ...(coords ? coords : {}),
      });
      setSent(true);
    } catch (err) {
      setPlaceError(err instanceof Error ? err.message : "Could not send.");
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="public-emergency" lang={lang}>
      <header className="pe-header">
        <span className="pe-cross" aria-hidden="true">
          +
        </span>
        <h1>{t.title}</h1>
        <div className="pe-lang" role="group" aria-label="Language">
          <button type="button" aria-pressed={lang === "en"} onClick={() => setLang("en")}>
            English
          </button>
          <button type="button" aria-pressed={lang === "hi"} onClick={() => setLang("hi")}>
            हिंदी
          </button>
        </div>
      </header>

      {error ? (
        <p className="pe-error" role="alert">
          {error}
        </p>
      ) : null}
      {!card && !error ? <p className="pe-muted">{t.loading}</p> : null}

      {card ? (
        <>
          <section className="pe-person" aria-label="Patient">
            <p className="pe-name">{card.display_name}</p>
            <p className="pe-muted">
              {card.age !== null ? `${card.age} ${t.years}` : ""}
              {card.sex ? ` · ${card.sex}` : ""}
            </p>
          </section>

          <section className="pe-critical" aria-label={t.allergies}>
            <h2>{t.allergies}</h2>
            {card.allergies.length ? (
              <ul>
                {card.allergies.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>{t.noAllergies}</p>
            )}
          </section>

          <dl className="pe-facts">
            <div>
              <dt>{t.blood}</dt>
              <dd>{card.blood_group || t.none}</dd>
            </div>
            <div>
              <dt>{t.medicines}</dt>
              <dd>
                {card.medications.length
                  ? card.medications.map((med) => `${med.name} ${med.dose}`.trim()).join("; ")
                  : t.none}
              </dd>
            </div>
            <div>
              <dt>{t.conditions}</dt>
              <dd>{card.conditions.length ? card.conditions.join("; ") : t.none}</dd>
            </div>
            <div>
              <dt>{t.implants}</dt>
              <dd>{card.implants || t.none}</dd>
            </div>
            {card.notes ? (
              <div>
                <dt>{t.notes}</dt>
                <dd>{card.notes}</dd>
              </div>
            ) : null}
          </dl>

          {card.emergency_contacts.length ? (
            <section aria-label={t.contacts}>
              <h2 className="pe-h2">{t.contacts}</h2>
              <div className="pe-contacts">
                {card.emergency_contacts.map((contact) =>
                  contact.phone ? (
                    <a key={`${contact.name}-${contact.phone}`} className="pe-call" href={`tel:${contact.phone.replace(/[^\d+]/g, "")}`}>
                      <strong>{contact.name || contact.phone}</strong>
                      <span>
                        {contact.relation ? `${contact.relation} · ` : ""}
                        {contact.phone}
                      </span>
                    </a>
                  ) : null,
                )}
              </div>
            </section>
          ) : null}

          <p className="pe-status">{card.family_alerted ? t.alerted : t.notAlerted}</p>

          {card.family_alerted ? (
            sent ? (
              <p className="pe-sent" role="status">
                {t.sent}
              </p>
            ) : (
              <form className="pe-where" onSubmit={onSend}>
                <h2 className="pe-h2">{t.whereTitle}</h2>
                <p className="pe-muted">{t.whereHint}</p>
                <label>
                  <span>{t.placeLabel}</span>
                  <input
                    value={place}
                    maxLength={200}
                    placeholder={t.placeholder}
                    onChange={(event) => setPlace(event.target.value)}
                  />
                </label>
                <div className="pe-actions">
                  <button type="button" className="pe-secondary" onClick={onLocate} disabled={locating}>
                    {locating ? t.locating : t.useLocation}
                  </button>
                  <button type="submit" className="pe-primary" disabled={sending || (!place.trim() && !coords)}>
                    {t.send}
                  </button>
                </div>
                {coords ? <p className="pe-muted">{t.locationAdded}</p> : null}
                {placeError ? (
                  <p className="pe-error" role="alert">
                    {placeError}
                  </p>
                ) : null}
              </form>
            )
          ) : null}

          <p className="pe-disclaimer">{card.disclaimer}</p>
        </>
      ) : null}
    </main>
  );
}
