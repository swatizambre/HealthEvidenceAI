import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { askHelp, getHelpTopics, type HelpTopic } from "../api";
import { useI18n } from "../i18n";
import { Button, Drawer, Icon } from "../ui";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  links?: string[];
};

const LINK_LABELS: Record<string, string> = {
  "/": "Work queue",
  "/cases": "Cases",
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
  if (path.startsWith("/cases/")) {
    return "Open case";
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

function caseFromLocation(pathname: string, searchCase: string | null): string {
  const match = pathname.match(/\/cases\/([^/?#]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : searchCase || "";
}

/** Header "Help" button that opens desk guidance in a side panel (no floating launcher). */
export function HelpChat() {
  const { t } = useI18n();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const routePatient = patientFromLocation(location.pathname, searchParams.get("patient"));
  const caseId = caseFromLocation(location.pathname, searchParams.get("case"));
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
        "Ask about desk workflows: finding a case, preparing the pre-auth form, answering a TPA query, or sending a case for senior review. Answers can use the open chart. This tool does not diagnose or decide coverage.",
      links: ["/", "/reviews", "/patients", "/visit"],
    },
  ]);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || topics.length) {
      return;
    }
    getHelpTopics()
      .then((body) => setTopics(body.topics))
      .catch(() => setTopics([]));
  }, [open, topics.length]);

  useEffect(() => {
    if (open) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [open, messages, busy]);

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
        { id: `a-${Date.now()}`, role: "assistant", text: reply.reply, links: reply.suggested_links },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Help is unavailable right now.");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(input);
  }

  return (
    <>
      <button
        type="button"
        className="header-btn"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <Icon name="help" />
        <span>{t("shell.help")}</span>
      </button>
      <Drawer
        open={open}
        title="Desk help"
        onClose={() => setOpen(false)}
        footer={
          <form className="help-form" onSubmit={onSubmit}>
            <label className="sr-only" htmlFor="help-chat-input">
              Ask a help question
            </label>
            <input
              id="help-chat-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={routePatient ? "Ask about this chart or the next step…" : "Ask how to prepare a pre-auth…"}
              disabled={busy}
              autoComplete="off"
            />
            <Button type="submit" variant="primary" size="sm" disabled={!input.trim()} loading={busy}>
              Send
            </Button>
          </form>
        }
      >
        <p className="muted small">
          {routePatient
            ? `Answers can use ${routePatient} when you ask about this chart.`
            : "Workflow guidance for desk staff, junior doctors and consultants."}
        </p>
        {topics.length > 0 ? (
          <div className="chip-row" aria-label="Suggested topics">
            {topics.map((topic) => (
              <button
                key={topic.id}
                type="button"
                className="chip"
                onClick={() => void send(topic.prompt)}
                disabled={busy}
              >
                {topic.title}
              </button>
            ))}
          </div>
        ) : null}
        <div className="help-log" role="log" aria-live="polite">
          {messages.map((item) => (
            <div key={item.id} className={`help-bubble help-${item.role}`}>
              <p>{item.text}</p>
              {item.links && item.links.length > 0 ? (
                <div className="help-links">
                  {item.links.map((path) => (
                    <Link key={path} className="text-link" to={path} onClick={() => setOpen(false)}>
                      {linkLabel(path)}
                    </Link>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
          {busy ? <p className="muted small">Looking up desk guidance…</p> : null}
          <div ref={endRef} />
        </div>
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
      </Drawer>
    </>
  );
}
