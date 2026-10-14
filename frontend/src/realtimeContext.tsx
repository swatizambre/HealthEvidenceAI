import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getStreamTicket } from "./api";
import { useRole } from "./roleContext";

export type DeskRealtimeEvent = {
  event_id: string;
  type: string;
  ts: number;
  org_id?: string | null;
  case_id?: string | null;
  patient_id?: string | null;
  actor?: string | null;
  detail?: Record<string, unknown>;
};

type RealtimeContextValue = {
  connected: boolean;
  lastEvent: DeskRealtimeEvent | null;
  revision: number;
  /** Subscribe to push events; returns unsubscribe. */
  subscribe: (listener: (event: DeskRealtimeEvent) => void) => () => void;
};

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { demoSigninAllowed, isPatient } = useRole();
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<DeskRealtimeEvent | null>(null);
  const [revision, setRevision] = useState(0);
  const listeners = useRef(new Set<(event: DeskRealtimeEvent) => void>());

  const subscribe = useCallback((listener: (event: DeskRealtimeEvent) => void) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  useEffect(() => {
    if (isPatient) {
      setConnected(false);
      return;
    }
    let closed = false;
    let source: EventSource | null = null;
    let retryTimer: number | undefined;

    function scheduleRetry() {
      if (!closed) {
        retryTimer = window.setTimeout(() => void connect(), 3_000);
      }
    }

    async function connect() {
      // Fresh single-use ticket on every (re)connect — the bearer never enters the URL.
      let ticket: string | null = null;
      try {
        ticket = await getStreamTicket();
      } catch {
        setConnected(false);
        scheduleRetry();
        return;
      }
      if (closed) {
        return;
      }
      const params = new URLSearchParams();
      if (ticket) {
        params.set("ticket", ticket);
      }
      const url = `/api/v1/events/stream${params.toString() ? `?${params}` : ""}`;
      source = new EventSource(url);

      source.onopen = () => {
        if (!closed) {
          setConnected(true);
        }
      };

      source.onerror = () => {
        // Close so EventSource does not auto-retry with the spent ticket.
        setConnected(false);
        source?.close();
        scheduleRetry();
      };

      function onMessage(raw: MessageEvent) {
        try {
          const parsed = JSON.parse(String(raw.data)) as DeskRealtimeEvent;
          setLastEvent(parsed);
          setRevision((n) => n + 1);
          listeners.current.forEach((listener) => listener(parsed));
        } catch {
          /* ignore malformed */
        }
      }

      source.onmessage = onMessage;
      // Named event types from the server.
      for (const name of [
        "connected",
        "evidence_pack_prepare",
        "evidence_pack_review",
        "case_assign",
        "visit_note_saved",
        "hospital_visit_received",
      ]) {
        source.addEventListener(name, onMessage as EventListener);
      }
    }

    void connect();
    return () => {
      closed = true;
      if (retryTimer) {
        window.clearTimeout(retryTimer);
      }
      source?.close();
      setConnected(false);
    };
  }, [isPatient, demoSigninAllowed]);

  const value = useMemo(
    () => ({ connected, lastEvent, revision, subscribe }),
    [connected, lastEvent, revision, subscribe],
  );

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export function useRealtime(): RealtimeContextValue {
  const ctx = useContext(RealtimeContext);
  if (!ctx) {
    throw new Error("useRealtime must be used within RealtimeProvider");
  }
  return ctx;
}
