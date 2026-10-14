import { useCallback, useEffect, useRef, useState } from "react";
import type { Translate } from "../i18n";
import { useRealtime } from "../realtimeContext";

type Options = {
  /** Fallback poll when SSE is down (ms). When connected, poll is slowed. */
  intervalMs?: number;
  /** When false, polling pauses (e.g. modal busy). Default true. */
  enabled?: boolean;
};

/**
 * Final real-time desk refresh: SSE push first, visibility refetch, slow poll fallback.
 */
export function useLiveRefresh(
  refresh: () => void | Promise<void>,
  { intervalMs = 60_000, enabled = true }: Options = {},
): { lastUpdatedAt: number | null; refreshNow: () => void; pushConnected: boolean } {
  const { connected, subscribe } = useRealtime();
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const inFlight = useRef(false);

  const run = useCallback(async () => {
    if (inFlight.current || !enabled) {
      return;
    }
    inFlight.current = true;
    try {
      await refreshRef.current();
      setLastUpdatedAt(Date.now());
    } finally {
      inFlight.current = false;
    }
  }, [enabled]);

  // Immediate refresh on every desk mutation push.
  useEffect(() => {
    if (!enabled) {
      return;
    }
    return subscribe((event) => {
      if (event.type === "connected") {
        return;
      }
      void run();
    });
  }, [enabled, subscribe, run]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    void run();
    // When SSE is live, poll slowly as a safety net; when disconnected, poll faster.
    const period = connected ? Math.max(intervalMs, 45_000) : Math.min(intervalMs, 12_000);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void run();
      }
    }, period);
    function onVisible() {
      if (document.visibilityState === "visible") {
        void run();
      }
    }
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [enabled, intervalMs, run, connected]);

  return { lastUpdatedAt, refreshNow: () => void run(), pushConnected: connected };
}

export function formatLiveAge(
  lastUpdatedAt: number | null,
  pushConnected = false,
  t?: Translate,
): string {
  const tr: Translate = t ?? ((key, vars) => {
    let text: string = LIVE_EN[key as keyof typeof LIVE_EN] ?? key;
    for (const [name, value] of Object.entries(vars ?? {})) text = text.split(`{${name}}`).join(String(value));
    return text;
  });
  const channel = pushConnected ? tr("live.push") : tr("live.poll");
  if (lastUpdatedAt == null) {
    return `${channel} · ${tr("live.connecting")}`;
  }
  const seconds = Math.max(0, Math.round((Date.now() - lastUpdatedAt) / 1000));
  if (seconds < 5) {
    return `${channel} · ${tr("live.justNow")}`;
  }
  if (seconds < 60) {
    return `${channel} · ${tr("live.secondsAgo", { n: seconds })}`;
  }
  const minutes = Math.floor(seconds / 60);
  return `${channel} · ${tr("live.minutesAgo", { n: minutes })}`;
}

const LIVE_EN = {
  "live.push": "Live push",
  "live.poll": "Live poll",
  "live.connecting": "connecting…",
  "live.justNow": "just now",
  "live.secondsAgo": "{n}s ago",
  "live.minutesAgo": "{n}m ago",
} as const;
