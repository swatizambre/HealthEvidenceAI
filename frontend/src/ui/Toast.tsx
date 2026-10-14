import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Icon } from "./icons";

type ToastTone = "success" | "danger" | "info";
type ToastItem = { id: number; tone: ToastTone; message: string };

type ToastApi = { show: (message: string, tone?: ToastTone) => void };

const ToastContext = createContext<ToastApi | null>(null);

/** Toasts render in one polite live region; errors use an assertive region. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const show = useCallback(
    (message: string, tone: ToastTone = "success") => {
      const id = nextId.current++;
      setItems((prev) => [...prev.slice(-3), { id, tone, message }]);
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), tone === "danger" ? 9000 : 5000),
      );
    },
    [dismiss],
  );

  useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((timer) => window.clearTimeout(timer));
      map.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(() => ({ show }), [show]);
  const polite = items.filter((item) => item.tone !== "danger");
  const urgent = items.filter((item) => item.tone === "danger");

  function renderList(list: ToastItem[]) {
    return list.map((item) => (
      <div key={item.id} className={`toast toast-${item.tone}`}>
        <Icon name={item.tone === "danger" ? "alert" : item.tone === "success" ? "check" : "info"} />
        <p>{item.message}</p>
        <button type="button" className="toast-close" onClick={() => dismiss(item.id)}>
          <Icon name="x" size={14} />
          <span className="sr-only">Dismiss</span>
        </button>
      </div>
    ));
  }

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-region">
        <div aria-live="polite" aria-atomic="false">
          {renderList(polite)}
        </div>
        <div aria-live="assertive" aria-atomic="false">
          {renderList(urgent)}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx;
}
