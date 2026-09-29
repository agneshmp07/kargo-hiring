"use client";

import { useState } from "react";
import {
  Star, Scale, MinusCircle, Briefcase, MapPin, Eye, Copy, Inbox, ShieldCheck, Info, ArrowLeftRight,
  CalendarCheck, X, Pause, Undo2, MessageSquare, UsersRound, AlertTriangle, CheckCircle2, PauseCircle, Lock, Send,
  MessageCircleQuestion, Quote,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Board, Card } from "@/lib/types";
import { BAND_TONE, EMAIL_STATUS, GATE, SAFETY_NET, SOURCE_LABEL, fmtDate, fmtTime, label } from "@/lib/labels";
import { Badge, useToast } from "./ui";
import { can, useMe } from "./AppShell";
import { Avatar, ScoreRing, SignalStrip } from "./brand";

const BAND_ICON = { Strong: Star, Borderline: Scale, "Not a fit": MinusCircle } as const;
const BAND_STRIPE = { Strong: "from-good to-accent2", Borderline: "from-warn to-accent", "Not a fit": "from-line to-line" } as const;

export function BandBadge({ band }: { band: keyof typeof BAND_ICON }) {
  const I = BAND_ICON[band];
  return <Badge tone={BAND_TONE[band]} icon={<I className="h-3.5 w-3.5" />}>{band}</Badge>;
}

type Props = {
  card: Card; role: string; board: Pick<Board, "role_names" | "users">; onChange: () => void;
  showButtons?: boolean; compact?: boolean; keys?: boolean;
  onDecided?: (decision: "Advance" | "Pass" | "Hold") => void;
};

export default function CandidateCard({ card, role, board, onChange, showButtons = true, compact = false, keys = false, onDecided }: Props) {
  const me = useMe();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const roles = Object.keys(card.results);
  const [decideRole, setDecideRole] = useState(card.better_fit in card.results ? card.better_fit : role);
  const r = card.results[role];
  const names = board.role_names;
  const dec = card.decision;

  const call = async (fn: () => Promise<any>, ok: (res: any) => string) => {
    setBusy(true);
    try {
      const res = await fn();
      toast(ok(res));
      onChange();
      return true;
    } catch (e: any) {
      toast(e.message, true);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const decide = async (decision: "Advance" | "Pass" | "Hold") => {
    const done = await call(() => api("/decisions", { body: { candidate_id: card.id, role: decideRole, decision } }), (res) =>
      decision === "Advance" ? `${card.id} invited: ${res.name ?? ""} · email ${EMAIL_STATUS[res.email_status] ?? ""}`
        : decision === "Pass" ? `${card.id} passed · email ${EMAIL_STATUS[res.email_status] ?? ""}`
        : `${card.id} on hold. You'll be reminded in 7 days.`);
    if (done) onDecided?.(decision);
  };
  const undo = () => call(() => api(`/decisions/${dec!.id}/undo`, { method: "POST" }), () => "Undone. The email was cancelled before sending.");

  const g = GATE[r.gate];
  const inMumbai = /mumbai/i.test(card.city);
  const n1Caps = (card.layer_a.N1?.code ?? 0) > 0 && (card.layer_a.P1?.code ?? 0) > 0;
  const watch = (["N1", "N2"] as const).filter((v) => (card.layer_a[v]?.code ?? 0) > 0);

  return (
    <article className="card overflow-hidden transition hover:shadow-lift" data-candidate={card.id}>
      <div className={`h-1 bg-gradient-to-r ${BAND_STRIPE[r.band]}`} />
      <div className="p-4 md:p-6">
        {/* ---------------- header ---------------- */}
        <div className="flex items-start gap-4">
          <Avatar id={card.id} name={card.name} size={52} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-display text-lg font-bold tracking-tight">{card.id}{card.name && <span className="font-medium text-muted"> · {card.name}</span>}</h3>
              <BandBadge band={r.band} />
              <span className="chip">{names[role] ?? role}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge tone={g.tone} icon={<Briefcase className="h-3.5 w-3.5" />}>
                {card.pm_years ?? "?"} yrs PM · asks {r.gate_range[0]}–{r.gate_range[1]} · {g.text}
              </Badge>
              <Badge tone={inMumbai || card.open_to_relocate === "yes" ? "info" : "neutral"} icon={<MapPin className="h-3.5 w-3.5" />}>
                {card.city}{inMumbai ? "" : ` · relocate: ${card.open_to_relocate}`}
              </Badge>
              {card.confidence === "low" && <Badge tone="violet" icon={<Eye className="h-3.5 w-3.5" />}>Check this CV yourself</Badge>}
              {card.duplicate_of && <Badge tone="bad" icon={<Copy className="h-3.5 w-3.5" />}>Also applied as {card.duplicate_of}</Badge>}
              {card.source && !["folder", "demo"].includes(card.source) && <Badge icon={<Inbox className="h-3.5 w-3.5" />}>{SOURCE_LABEL[card.source] ?? card.source}</Badge>}
            </div>
          </div>
          <div className="flex flex-col items-center gap-1">
            <ScoreRing value={r.final} band={r.band} />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">score</span>
          </div>
        </div>

        {/* ---------------- pattern strip ---------------- */}
        <div className="mt-5 rounded-2xl bg-sunken/60 p-3.5 ring-1 ring-inset ring-line/70">
          <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-muted">
            <span>Kargo pattern</span>
            <span className="tabular-nums">pattern {Math.round(r.layer_a)} · role fit {Math.round(r.layer_b)}</span>
          </div>
          <SignalStrip codes={card.layer_a} capped={n1Caps} />
          {watch.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {watch.map((v) => <Badge key={v} tone="bad" icon={<AlertTriangle className="h-3.5 w-3.5" />}>{label(v)}</Badge>)}
            </div>
          )}
        </div>

        {(r.adjustments.length > 0 || (card.confidence === "low" && card.low_conf_reasons.length > 0) || roles.length > 1) && (
          <div className="mt-3 space-y-1.5">
            {r.adjustments.map((a) => (
              <p key={a.rule} className="flex gap-2 text-xs text-muted"><ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" />
                <span><b className="text-fg">Safety net:</b> {SAFETY_NET[a.rule] ?? a.why}</span></p>
            ))}
            {card.confidence === "low" && card.low_conf_reasons.length > 0 && (
              <p className="flex gap-2 text-xs text-muted"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet" /> Why: {card.low_conf_reasons.join("; ")}</p>
            )}
            {roles.filter((o) => o !== role).map((o) => (
              <p key={o} className="flex gap-2 text-xs text-muted"><ArrowLeftRight className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>Also checked for <b className="text-fg">{names[o] ?? o}</b>: {card.results[o].band}, {Math.round(card.results[o].final)}/100
                  {card.better_fit === o && <b className="text-good"> · looks like the better fit</b>}</span></p>
            ))}
          </div>
        )}

        {card.rationale && <p className="mt-4 text-[15px] leading-relaxed">{card.rationale}</p>}

        {!compact && (
          <div className="mt-4 grid gap-5 lg:grid-cols-5">
            <div className="lg:col-span-3"><Evidence card={card} role={role} /></div>
            <div className="lg:col-span-2">
              <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><MessageCircleQuestion className="h-4 w-4 text-accent" /> Ask in the interview</div>
              <ol className="space-y-2">
                {card.probes.map((p, i) => (
                  <li key={i} className="flex gap-2.5 text-sm">
                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent/10 font-display text-xs font-bold text-accent">{i + 1}</span>
                    <span className="pt-0.5">{p}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-3 text-xs text-muted">PM years: {card.pm_years_working}</p>
            </div>
          </div>
        )}

        <TeamRow card={card} role={role} board={board} onChange={onChange} />

        {/* ---------------- decision ---------------- */}
        {dec && dec.decision !== "Hold" ? (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-2xl bg-good/10 px-4 py-3 text-sm ring-1 ring-inset ring-good/25">
            <CheckCircle2 className="h-5 w-5 text-good" />
            <span>{dec.decision === "Advance" ? "Invited to interview" : "Passed"} ({names[dec.role] ?? dec.role})
              {dec.decided_by && ` by ${dec.decided_by}`} on {fmtDate(dec.ts)} · email {EMAIL_STATUS[card.email_status ?? ""] ?? card.email_status ?? "none"}
              {card.email_status === "scheduled" && card.email_send_after && ` (goes out ${fmtTime(card.email_send_after)})`}</span>
            {card.undoable && can(me, "decide") && (
              <button className="btn ml-auto" disabled={busy} onClick={undo}><Undo2 className="h-4 w-4" /> Undo</button>
            )}
          </div>
        ) : (
          <>
            {dec?.decision === "Hold" && (
              <div className="mt-4 flex items-center gap-2 rounded-2xl bg-warn/10 px-4 py-3 text-sm ring-1 ring-inset ring-warn/25">
                <PauseCircle className="h-5 w-5 text-warn" /> On hold since {fmtDate(dec.ts)}
                {card.hold_days != null && `: ${card.hold_days} days, time to decide?`}
              </div>
            )}
            {showButtons && (can(me, "decide") ? (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line/70 pt-4">
                {roles.length > 1 && (
                  <select className="input w-auto py-2" value={decideRole} onChange={(e) => setDecideRole(e.target.value)} aria-label="Decide for role">
                    {roles.map((o) => <option key={o} value={o}>Decide for {names[o] ?? o}</option>)}
                  </select>
                )}
                <button data-action="Advance" className="btn btn-primary px-5" disabled={busy} onClick={() => decide("Advance")}>
                  <CalendarCheck className="h-4 w-4" /> Invite to interview{keys && <span className="kbd">I</span>}
                </button>
                <button data-action="Pass" className="btn" disabled={busy} onClick={() => decide("Pass")}><X className="h-4 w-4" /> Pass{keys && <span className="kbd">P</span>}</button>
                {dec?.decision !== "Hold" && <button data-action="Hold" className="btn" disabled={busy} onClick={() => decide("Hold")}><Pause className="h-4 w-4" /> Hold{keys && <span className="kbd">H</span>}</button>}
              </div>
            ) : (
              <p className="mt-4 flex items-center gap-1.5 text-xs text-muted"><Lock className="h-3.5 w-3.5" /> Only the decision-maker can invite or pass. You can comment or give a second opinion.</p>
            ))}
          </>
        )}
      </div>
    </article>
  );
}

export function Evidence({ card, role }: { card: Card; role: string }) {
  const flags = Object.fromEntries(card.evidence_flags.map((f) => [f.var, f.flag]));
  const la = card.layer_a;
  const n1Caps = (la.N1?.code ?? 0) > 0 && (la.P1?.code ?? 0) > 0;
  const items: [string, { code: number; evidence: string | null }, string | undefined][] = [
    ...(["P1", "P2", "P3", "P4", "P5"] as const).filter((v) => la[v]).map((v) => [v, la[v], flags[v]] as any),
    ...Object.entries(card.layer_b[role] ?? {}).map(([k, v]) => [k, v, flags[`${role}.${k}`]] as any),
  ];
  const found = items.filter(([, v]) => v.code > 0);
  const missing = items.filter(([, v]) => v.code === 0).map(([k]) => label(k));
  const watch = (["N1", "N2"] as const).filter((v) => (la[v]?.code ?? 0) > 0);
  return (
    <div className="text-sm">
      <div className="mb-2 flex items-center gap-1.5 font-semibold"><Quote className="h-4 w-4 text-accent2" /> What the CV shows</div>
      {found.length ? (
        <ul className="grid gap-2 sm:grid-cols-2">
          {found.map(([k, v, flag]) => {
            const dead = k === "P1" && n1Caps;
            return (
              <li key={k} className={`rounded-xl border-l-[3px] bg-sunken/60 px-3 py-2.5 ${dead ? "border-bad/60" : v.code === 1 ? "border-accent2" : "border-accent2/40"}`}>
                <div className="flex items-center gap-1.5 text-xs font-semibold">
                  <span className={v.code === 1 ? "text-accent2" : "text-muted"}>{v.code === 1 ? "●" : "◐"}</span>{label(k)}
                </div>
                <p className="mt-1 text-[13px] leading-snug text-muted">“{v.evidence}”</p>
                {dead ? <p className="mt-1 text-xs text-bad">Doesn&apos;t count: the logistics exposure is desk/API only.</p>
                  : flag && <p className="mt-1 text-xs text-warn">{flag}</p>}
              </li>
            );
          })}
        </ul>
      ) : <p className="rounded-xl bg-sunken/60 px-3 py-2.5 italic text-muted">No supporting evidence found in the CV.</p>}
      {watch.map((v) => la[v].evidence && (
        <p key={v} className="mt-2 flex gap-1.5 rounded-xl bg-bad/5 px-3 py-2 text-xs ring-1 ring-inset ring-bad/20">
          <AlertTriangle className="h-4 w-4 shrink-0 text-bad" /><span><b>{label(v)}</b>: “{la[v].evidence}”</span></p>
      ))}
      {missing.length > 0 && <p className="mt-2 text-xs text-muted">Not found: {missing.join(" · ")}</p>}
    </div>
  );
}

function TeamRow({ card, role, board, onChange }: { card: Card; role: string; board: Pick<Board, "users">; onChange: () => void }) {
  const me = useMe();
  const toast = useToast();
  const [open, setOpen] = useState<"comments" | "opinions" | null>(null);
  const [text, setText] = useState("");
  const others = board.users.filter((u) => u.username !== me.user.username && u.can_review);
  const [assignee, setAssignee] = useState(others[0]?.username ?? "");
  const done = card.reviews.filter((r) => r.status === "done");
  const waiting = card.reviews.filter((r) => r.status === "open");

  const post = async () => {
    try {
      await api("/comments", { body: { candidate_id: card.id, body: text } });
      setText("");
      onChange();
    } catch (e: any) { toast(e.message, true); }
  };
  const ask = async () => {
    try {
      await api("/reviews", { body: { candidate_id: card.id, role, assignee } });
      toast("Asked. They'll see it under Second opinions.");
      onChange();
    } catch (e: any) { toast(e.message, true); }
  };

  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2">
        <button className={`chip transition hover:text-fg ${open === "comments" ? "bg-accent/10 text-accent ring-accent/30" : ""}`} onClick={() => setOpen(open === "comments" ? null : "comments")}>
          <MessageSquare className="h-3.5 w-3.5" /> Comments ({card.comments.length})
        </button>
        <button className={`chip transition hover:text-fg ${open === "opinions" ? "bg-accent/10 text-accent ring-accent/30" : ""}`} onClick={() => setOpen(open === "opinions" ? null : "opinions")}>
          <UsersRound className="h-3.5 w-3.5" /> Second opinions ({done.length}){waiting.length > 0 && ` · ${waiting.length} waiting`}
        </button>
      </div>
      {open === "comments" && (
        <div className="mt-2 animate-rise space-y-2 rounded-2xl bg-sunken/70 p-3 text-sm">
          {card.comments.map((c) => (
            <div key={c.id} className="flex gap-2">
              <Avatar id={c.author} name={c.author} size={26} />
              <p><b>{c.author}</b> <span className="text-xs text-muted">{fmtTime(c.ts)}</span><br />{c.body}</p>
            </div>
          ))}
          {can(me, "comment") && (
            <div className="flex gap-2">
              <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a comment. Use @username to mention someone"
                onKeyDown={(e) => e.key === "Enter" && text.trim() && post()} />
              <button className="btn" disabled={!text.trim()} onClick={post}><Send className="h-4 w-4" /></button>
            </div>
          )}
        </div>
      )}
      {open === "opinions" && (
        <div className="mt-2 animate-rise space-y-2 rounded-2xl bg-sunken/70 p-3 text-sm">
          {done.map((o) => <p key={o.id}><b>{o.assignee}</b> suggests <b>{o.opinion === "Advance" ? "Invite" : o.opinion}</b>{o.note && `: ${o.note}`}</p>)}
          {waiting.map((o) => <p key={o.id} className="text-muted">Waiting for {o.assignee} (asked by {o.requested_by})</p>)}
          {can(me, "comment") && others.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <select className="input w-auto" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                {others.map((u) => <option key={u.username} value={u.username}>{u.display_name}</option>)}
              </select>
              <button className="btn" onClick={ask}><UsersRound className="h-4 w-4" /> Ask for a second opinion</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
