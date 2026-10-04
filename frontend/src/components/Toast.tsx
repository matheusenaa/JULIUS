import { CheckCircle2, AlertTriangle } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface Toast {
  id: number;
  text: string;
  kind: "success" | "error";
  action?: { label: string; run: () => void };
}

type Push = (text: string, opts?: { kind?: Toast["kind"]; action?: Toast["action"] }) => void;

const ToastContext = createContext<Push>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback<Push>((text, opts) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, text, kind: opts?.kind ?? "success", action: opts?.action }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), opts?.action ? 7000 : 4000);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === "error" ? "error" : ""}`}>
            {t.kind === "error" ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
            <span>{t.text}</span>
            {t.action && (
              <button
                onClick={() => {
                  t.action!.run();
                  setToasts((all) => all.filter((x) => x.id !== t.id));
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
