import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { askHelp, getHelpTopics, type HelpTopic } from "../api";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  links?: string[];
};

const LINK_LABELS: Record<string, string> = {
  "/": "Today",
  "/patients": "Patients",
  "/visit": "Visit note",
  "/reviews": "Reviews",
};

function linkLabel(path: string): string {
  if (path.includes("prepare=1")) {
    return "Prepare evidence pack";
  }
  if (path.startsWith("/patients/PAT-")) {
    return "Open chart";
  }
  if (path.startsWith("/reviews")) {
    return "Reviews";
  }
  return LINK_LABELS[path] || path;
}

function patientFromLocation(pathname: string, searchPatient: string | null): string {
  if (searchPatient && /^PAT-\d{6}$/.test(searchPatient)) {
    return searchPatient;
  }
  const match = pathname.match(/\/patients\/(PAT-\d{6})/);
  return match?.[1] || "";
}

export function HelpChat() {
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const routePatient = patientFromLocation(location.pathname, searchParams.get("patient"));
  const caseId = searchParams.get("case") || "";
  const policyId = searchParams.get("policy") || "";

  const [open, setOpen] = useState(false);
  const [topics, setTopics] = useState<HelpTopic[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text:
        "Ask about desk workflows — find a patient, add a visit note, prepare an evidence pack, or open Reviews for clinician confirmation. Answers can use the open chart. This tool does not diagnose or decide coverage.",
      links: ["/", "/reviews", "/patients", "/visit"],
    },
  ]);
  const endRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const launchRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    getHelpTopics()
      .then((body) => setTopics(body.topics))
      .catch(() => setTopics([]));
  }, []);

  useEffect(() => {
    if (open) {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
      window.setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open, messages, busy]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        launchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) {
      return;
    }
    setError("");
    setBusy(true);
    setInput("");
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", text: message }]);
    try {
      const reply = await askHelp(message, location.pathname, {
        patient_id: routePatient || undefined,
        case_id: caseId || undefined,
        policy_id: policyId || undefined,
      });
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: reply.reply,
          links: reply.suggested_links,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Help chat unavailable");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(input);
  }

  return (
    <div className="help-chat-root">
      {open ? (
        <section className="help-chat-panel" id="help-chat-panel" aria-label="Desk help">
          <header className="help-chat-head">
            <div>
              <strong>Desk help</strong>
              <p className="muted">
                {routePatient
                  ? `Grounded on ${routePatient} when you ask about this chart`
                  : "Workflow guidance for staff, residents, and seniors"}
              </p>
            </div>
            <button
              type="button"
              className="btn btn-ghost sm"
              onClick={() => {
                setOpen(false);
                launchRef.current?.focus();
              }}
              aria-label="Close help chat"
            >
              Close
            </button>
          </header>

          {topics.length > 0 ? (
            <div className="help-topic-row" aria-label="Suggested topics">
              {topics.map((topic) => (
                <button
                  key={topic.id}
                  type="button"
                  className="chip help-topic-chip"
                  onClick={() => void send(topic.prompt)}
                  disabled={busy}
                >
                  {topic.title}
                </button>
              ))}
            </div>
          ) : null}

          <div className="help-chat-messages" role="log" aria-live="polite">
            {messages.map((item) => (
              <div
                key={item.id}
                className={`help-bubble ${item.role === "user" ? "user" : "assistant"}`}
              >
                <p>{item.text}</p>
                {item.links && item.links.length > 0 ? (
                  <div className="help-links">
                    {item.links.map((path) => (
                      <Link
                        key={path}
                        className="text-link"
                        to={path}
                        onClick={() => setOpen(false)}
                      >
                        {linkLabel(path)}
                      </Link>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
            {busy ? <p className="muted help-typing">Looking up desk guidance…</p> : null}
            <div ref={endRef} />
          </div>

          {error ? (
            <p className="error" role="alert">
              {error}
            </p>
          ) : null}

          <form className="help-chat-form" onSubmit={onSubmit}>
            <label className="sr-only" htmlFor="help-chat-input">
              Ask a help question
            </label>
            <input
              id="help-chat-input"
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={
                routePatient
                  ? "Ask about this chart or the next prep step…"
                  : "Ask how to prepare an evidence pack…"
              }
              disabled={busy}
              autoComplete="off"
            />
            <button className="btn btn-primary sm" type="submit" disabled={busy || !input.trim()}>
              Send
            </button>
          </form>
          <p className="help-chat-foot muted">
            Decision support only — never approves, denies, or diagnoses.
          </p>
        </section>
      ) : null}

      <button
        type="button"
        ref={launchRef}
        className={`help-chat-launch ${open ? "open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="help-chat-panel"
      >
        {open ? "Close help" : "Desk help"}
      </button>
    </div>
  );
}
