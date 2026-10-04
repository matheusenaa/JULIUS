import {
  AlertTriangle,
  Briefcase,
  Car,
  CircleDashed,
  GraduationCap,
  HeartPulse,
  House,
  Landmark,
  Loader2,
  PartyPopper,
  PiggyBank,
  Plane,
  Receipt,
  Repeat,
  Shirt,
  ShoppingBag,
  Sparkles,
  TrendingUp,
  Undo2,
  Utensils,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { brl, signedBrl } from "../lib/format";
import type { Category } from "../lib/types";

export { Logo } from "./Brand";

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "accent" | "ghost" | "danger";
  size?: "small";
  loading?: boolean;
  block?: boolean;
};

export function Button({ variant, size, loading, block, children, disabled, className, ...rest }: BtnProps) {
  const cls = ["btn", variant, size, block && "block", className].filter(Boolean).join(" ");
  return (
    <button className={cls} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {loading && <Loader2 size={16} className="spin" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {error ? <span className="error-text">{error}</span> : hint ? <span className="hint">{hint}</span> : null}
    </label>
  );
}

/** Folha inferior no celular, modal centralizado no desktop. Fecha com Esc e devolve o foco. */
export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input, select, textarea, button:not([data-close])");
    first?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      previous?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref}>
        <div className="sheet-head">
          <h2 id={titleId}>{title}</h2>
          <button className="btn ghost icon" onClick={onClose} aria-label="Fechar" data-close>
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, text, action }: { icon: LucideIcon; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="state">
      <div className="icon">
        <Icon size={24} />
      </div>
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state" role="alert">
      <div className="icon">
        <AlertTriangle size={24} />
      </div>
      <h3>Não foi possível carregar</h3>
      <p>{message}</p>
      {onRetry && (
        <button className="btn small" onClick={onRetry}>
          Tentar de novo
        </button>
      )}
    </div>
  );
}

export function Skeleton({ lines = 3, height = 18 }: { lines?: number; height?: number }) {
  return (
    <div aria-busy="true" aria-label="Carregando" style={{ display: "grid", gap: 12 }}>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ height, width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function Amount({ cents, type, className = "" }: { cents: number; type?: string; className?: string }) {
  const cls = type === "income" ? "income" : type === "expense" ? "expense" : "";
  return <span className={`num ${cls} ${className}`}>{type ? signedBrl(cents, type) : brl(cents)}</span>;
}

const ICONS: Record<string, LucideIcon> = {
  utensils: Utensils,
  home: House,
  car: Car,
  "heart-pulse": HeartPulse,
  "graduation-cap": GraduationCap,
  "party-popper": PartyPopper,
  shirt: Shirt,
  repeat: Repeat,
  "shopping-bag": ShoppingBag,
  receipt: Receipt,
  landmark: Landmark,
  plane: Plane,
  "trending-up": TrendingUp,
  briefcase: Briefcase,
  sparkles: Sparkles,
  "piggy-bank": PiggyBank,
  "undo-2": Undo2,
};

export function CategoryIcon({ category, parent, size = 18 }: { category?: Category | null; parent?: Category | null; size?: number }) {
  const source = category?.icon ? category : parent;
  const Icon = (source?.icon && ICONS[source.icon]) || CircleDashed;
  const color = category?.color ?? parent?.color ?? undefined;
  return (
    <span className="cat-dot" style={color ? { background: `${color}1f`, color } : undefined} aria-hidden="true">
      <Icon size={size} />
    </span>
  );
}

export function Progress({ ratio, label }: { ratio: number; label: string }) {
  const cls = ratio >= 1 ? "over" : ratio >= 0.8 ? "warn" : "";
  return (
    <div className={`progress ${cls}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio * 100)}>
      <i style={{ width: `${Math.min(ratio, 1) * 100}%` }} />
    </div>
  );
}
