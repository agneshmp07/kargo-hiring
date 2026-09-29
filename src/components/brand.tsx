"use client";

/* Visual pieces with a bit of character: the logo, the animated route art, score rings,
   the Kargo-pattern signal strip, generated avatars and a small confetti burst. */

import { useId } from "react";
import type { Band, Code } from "@/lib/types";

export function Logo({ size = 32 }: { size?: number }) {
  const id = `kg-logo-${useId().replace(/:/g, "")}`;  // unique per copy: a hidden copy can't break the others
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="rgb(var(--accent))" />
          <stop offset="1" stopColor="#ff9a4d" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${id})`} />
      {/* three stacked containers */}
      <rect x="7" y="17" width="8" height="6" rx="1.2" fill="white" opacity=".95" />
      <rect x="17" y="17" width="8" height="6" rx="1.2" fill="white" opacity=".75" />
      <rect x="12" y="9.5" width="8" height="6" rx="1.2" fill="white" opacity=".9" />
      <path d="M9 19.2h4M19 19.2h4M14 11.7h4" stroke="rgb(var(--accent))" strokeWidth="1.1" strokeLinecap="round" opacity=".7" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="flex items-center gap-2.5">
      <Logo />
      <span className="font-display text-lg font-bold tracking-tight">Kargo<span className="text-accent">.</span><span className="ml-1 font-medium text-muted">hiring</span></span>
    </span>
  );
}

/** Animated shipping routes between ports, for the opening screen. */
export function RouteArt({ className = "" }: { className?: string }) {
  const gid = `route-${useId().replace(/:/g, "")}`;
  const routes = [
    "M40 300 C 160 180, 260 330, 380 210 S 560 120, 660 190",
    "M60 90 C 180 150, 280 40, 420 110 S 600 260, 700 230",
    "M20 200 C 120 240, 220 120, 330 150 S 520 330, 690 300",
  ];
  const ports = [[40, 300], [660, 190], [60, 90], [700, 230], [20, 200], [690, 300], [380, 210], [420, 110], [330, 150]];
  return (
    <svg viewBox="0 0 720 360" className={className} aria-hidden="true" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={gid} x1="0" x2="1">
          <stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0" />
          <stop offset=".5" stopColor="rgb(var(--accent))" />
          <stop offset="1" stopColor="#ffd2a8" />
        </linearGradient>
      </defs>
      {routes.map((d, i) => (
        <g key={i}>
          <path d={d} fill="none" stroke="rgb(255 255 255 / .10)" strokeWidth="1.5" strokeDasharray="2 6" />
          <path d={d} fill="none" stroke={`url(#${gid})`} strokeWidth="2.2" strokeLinecap="round"
            strokeDasharray="900" strokeDashoffset="900"
            style={{ animation: `dash 3.2s ${i * 0.6}s cubic-bezier(.4,0,.2,1) forwards` }} />
          <circle r="4.5" fill="#fff">
            <animateMotion dur={`${9 + i * 2}s`} repeatCount="indefinite" path={d} />
          </circle>
          <circle r="10" fill="rgb(var(--accent))" opacity=".25">
            <animateMotion dur={`${9 + i * 2}s`} repeatCount="indefinite" path={d} />
          </circle>
        </g>
      ))}
      {ports.map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="3.5" fill="#fff" opacity=".9" />
          <circle cx={x} cy={y} r="9" fill="none" stroke="#fff" strokeOpacity=".25" />
        </g>
      ))}
    </svg>
  );
}

const BAND_COLOR: Record<Band, string> = { Strong: "var(--good)", Borderline: "var(--warn)", "Not a fit": "var(--muted)" };

export function ScoreRing({ value, band, size = 64 }: { value: number; band: Band; size?: number }) {
  const r = (size - 8) / 2, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, value)) / 100;
  const color = `rgb(${BAND_COLOR[band]})`;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} title={`${Math.round(value)}/100 · ${band}`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--line))" strokeWidth="6" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)} style={{ transition: "stroke-dashoffset .8s cubic-bezier(.2,.7,.2,1)" }} />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="font-display text-lg font-bold tabular-nums leading-none" style={{ color }}>{Math.round(value)}</span>
      </div>
    </div>
  );
}

export function ProgressRing({ done, total, size = 88 }: { done: number; total: number; size?: number }) {
  const r = (size - 10) / 2, c = 2 * Math.PI * r, pct = total ? done / total : 0;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--line))" strokeWidth="8" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--accent))" strokeWidth="8" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)} style={{ transition: "stroke-dashoffset 1s cubic-bezier(.2,.7,.2,1)" }} />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center leading-tight">
        <div><div className="font-display text-xl font-bold tabular-nums">{done}<span className="text-sm text-muted">/{total}</span></div>
          <div className="text-[10px] uppercase tracking-wide text-muted">decided</div></div>
      </div>
    </div>
  );
}

const SIGNALS: [string, string, string][] = [
  ["P1", "Ops", "Hands-on logistics / ops work"],
  ["P2", "Built", "Built something unasked that others adopted"],
  ["P3", "Owns", "Owned decisions with no layer above"],
  ["P4", "Crisis", "Personally resolved a live crisis"],
  ["P5", "Learns", "Killed something / ran a post-mortem"],
];

/** The Kargo pattern at a glance: five segments, full / half / empty. */
export function SignalStrip({ codes, capped }: { codes: Record<string, Code>; capped?: boolean }) {
  return (
    <div className="grid grid-cols-5 gap-1.5">
      {SIGNALS.map(([k, short, long]) => {
        let code = codes[k]?.code ?? 0;
        const dim = k === "P1" && capped;
        if (dim) code = 0;
        return (
          <div key={k} title={`${long}: ${dim ? "doesn't count (desk/API only)" : code === 1 ? "clear evidence" : code === 0.5 ? "partly" : "not found"}`}>
            <div className="h-2 overflow-hidden rounded-full bg-sunken ring-1 ring-inset ring-line">
              <div className={`h-full rounded-full ${code === 1 ? "bg-accent2" : "bg-accent2/60"}`}
                style={{ width: `${code * 100}%`, transition: "width .6s cubic-bezier(.2,.7,.2,1)" }} />
            </div>
            <div className={`mt-1 text-[11px] font-medium ${code ? "text-fg" : "text-muted/70"} ${dim ? "line-through" : ""}`}>{short}</div>
          </div>
        );
      })}
    </div>
  );
}

function hash(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

/** A friendly generated avatar. Uses initials once a name is revealed, otherwise the ID's digits. */
export function Avatar({ id, name, size = 44 }: { id: string; name?: string | null; size?: number }) {
  const h = hash(id);
  const a = h % 360, b = (a + 40 + (h % 60)) % 360;
  const label = name ? name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase() : id.replace(/\D/g, "").slice(-2);
  return (
    <div className="grid shrink-0 place-items-center rounded-2xl font-display font-bold text-white shadow-soft"
      style={{ width: size, height: size, fontSize: size * 0.36, background: `linear-gradient(135deg, hsl(${a} 70% 55%), hsl(${b} 75% 45%))` }}>
      {label}
    </div>
  );
}

export function Confetti({ count = 80 }: { count?: number }) {
  const colors = ["rgb(var(--accent))", "rgb(var(--accent2))", "rgb(var(--info))", "rgb(var(--violet))", "#ffd166"];
  return (
    <div className="pointer-events-none fixed inset-0 z-[70] overflow-hidden" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => {
        const left = (i * 37) % 100, delay = (i % 12) * 0.08, dur = 2.4 + (i % 7) * 0.25, w = 6 + (i % 4) * 2;
        return (
          <span key={i} className="absolute top-0 rounded-sm"
            style={{ left: `${left}%`, width: w, height: w * 0.45, background: colors[i % colors.length],
              animation: `confetti ${dur}s ${delay}s cubic-bezier(.3,.6,.4,1) forwards` }} />
        );
      })}
    </div>
  );
}
