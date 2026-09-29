"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { CheckCircle2, AlertCircle, X, Loader2 } from "lucide-react";
import type { Tone } from "@/lib/labels";

const TONE: Record<Tone, string> = {
  good: "bg-good/10 text-good ring-good/25",
  warn: "bg-warn/10 text-warn ring-warn/25",
  bad: "bg-bad/10 text-bad ring-bad/25",
  info: "bg-info/10 text-info ring-info/25",
  violet: "bg-violet/10 text-violet ring-violet/25",
  neutral: "bg-sunken text-muted ring-line",
  accent: "bg-accent/10 text-accent ring-accent/25",
};

export function Badge({ tone = "neutral", icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${TONE[tone]}`}>
      {icon}
      {children}
    </span>
  );
}

const METRIC_TONE: Record<Tone, string> = {
  good: "text-good bg-good/10", warn: "text-warn bg-warn/10", bad: "text-bad bg-bad/10", info: "text-info bg-info/10",
  violet: "text-violet bg-violet/10", neutral: "text-muted bg-sunken", accent: "text-accent bg-accent/10",
};

export function Metric({ label, value, hint, icon, tone = "neutral" }: {
  label: string; value: ReactNode; hint?: string; icon?: ReactNode; tone?: Tone;
}) {
  return (
    <div className="card group flex min-w-[150px] flex-1 items-center gap-3 px-4 py-3.5 transition hover:-translate-y-0.5 hover:shadow-lift" title={hint}>
      {icon && <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${METRIC_TONE[tone]}`}>{icon}</div>}
      <div className="min-w-0">
        <div className="truncate text-xs font-medium text-muted">{label}</div>
        <div className="font-display text-2xl font-bold tabular-nums leading-tight">{value}</div>
      </div>
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, labels }: {
  value: T; options: T[]; onChange: (v: T) => void; labels?: Record<string, string>;
}) {
  return (
    <div className="inline-flex flex-wrap rounded-xl border border-line bg-sunken p-1">
      {options.map((o) => (
        <button key={o} onClick={() => onChange(o)}
          className={`rounded-lg px-3 py-1.5 text-sm transition ${value === o ? "bg-surface font-semibold text-fg shadow-soft" : "text-muted hover:text-fg"}`}>
          {labels?.[o] ?? o}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: {
  value: T; tabs: { id: T; label: ReactNode }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`whitespace-nowrap rounded-full px-4 py-2 text-sm transition ${value === t.id ? "tab-active font-semibold shadow-soft" : "bg-surface/70 text-muted ring-1 ring-inset ring-line hover:text-fg"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="card flex items-center gap-4 border-dashed px-5 py-7 text-sm text-muted">
      {icon && <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-sunken text-muted ring-1 ring-inset ring-line">{icon}</div>}
      <div>{children}</div>
    </div>
  );
}

export function PageHeader({ icon, title, children, actions, tone = "accent" }: {
  icon: ReactNode; title: string; children?: ReactNode; actions?: ReactNode; tone?: Tone;
}) {
  return (
    <div className="flex flex-wrap items-start gap-4">
      <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl shadow-soft ${METRIC_TONE[tone]}`}>{icon}</div>
      <div className="min-w-0 flex-1">
        <h1 className="h1">{title}</h1>
        {children && <p className="muted mt-1 max-w-2xl">{children}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-muted">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function Modal({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="card w-full max-w-lg p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="h2">{title}</h2>
          <button className="btn btn-ghost px-2" onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Callout({ tone = "info", icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm ring-1 ring-inset ${TONE[tone]}`}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="text-fg">{children}</div>
    </div>
  );
}

/* ---------------- toasts ---------------- */

type Toast = { id: number; text: string; error?: boolean };
const ToastCtx = createContext<(text: string, error?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setItems((t) => [...t, { id, text, error }]);
    setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), error ? 7000 : 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="card pointer-events-auto flex items-start gap-2 px-3 py-2.5 text-sm shadow-lg">
            {t.error ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-bad" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-good" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
