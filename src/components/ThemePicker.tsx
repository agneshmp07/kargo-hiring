"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";

export const THEMES = [
  { id: "harbour", name: "Harbour", note: "Freight navy and orange", swatch: ["#0f1b2d", "#f26b1d", "#14a096"] },
  { id: "editorial", name: "Editorial", note: "Warm paper, serif, forest green", swatch: ["#f6f1e7", "#1f6f4a", "#be6034"] },
  { id: "aurora", name: "Aurora", note: "Glass, violet and cyan", swatch: ["#070716", "#a855f7", "#22d3ee"] },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];

export function applyTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id;
  try { localStorage.setItem("kargo-theme", id); } catch {}
}

/** Pick one of the three looks. Remembered in this browser. */
export default function ThemePicker({ compact = false }: { compact?: boolean }) {
  const [current, setCurrent] = useState<ThemeId>("harbour");
  useEffect(() => { setCurrent((document.documentElement.dataset.theme as ThemeId) || "harbour"); }, []);
  const pick = (id: ThemeId) => { applyTheme(id); setCurrent(id); };

  if (compact) {
    return (
      <div className="flex items-center gap-2 px-3" role="radiogroup" aria-label="Look">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted/80">Look</span>
        {THEMES.map((t) => (
          <button key={t.id} role="radio" aria-checked={current === t.id} title={`${t.name}: ${t.note}`} onClick={() => pick(t.id)}
            className={`relative h-6 w-6 overflow-hidden rounded-full ring-2 transition hover:scale-110 ${current === t.id ? "ring-accent" : "ring-line"}`}
            style={{ background: `conic-gradient(${t.swatch[0]} 0 50%, ${t.swatch[1]} 0 80%, ${t.swatch[2]} 0)` }}>
            <span className="sr-only">{t.name}</span>
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Look">
      {THEMES.map((t) => (
        <button key={t.id} role="radio" aria-checked={current === t.id} onClick={() => pick(t.id)}
          className={`card flex flex-col items-start gap-2 p-3 text-left transition hover:-translate-y-0.5 ${current === t.id ? "ring-2 ring-accent" : ""}`}>
          <div className="flex w-full items-center justify-between">
            <div className="flex -space-x-1.5">
              {t.swatch.map((c) => <span key={c} className="h-5 w-5 rounded-full ring-2 ring-surface" style={{ background: c }} />)}
            </div>
            {current === t.id && <Check className="h-4 w-4 text-accent" />}
          </div>
          <div>
            <div className="text-sm font-semibold">{t.name}</div>
            <div className="text-[11px] leading-snug text-muted">{t.note}</div>
          </div>
        </button>
      ))}
    </div>
  );
}
