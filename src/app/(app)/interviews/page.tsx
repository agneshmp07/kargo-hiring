"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarDays, CalendarClock, Check, ThumbsUp, ThumbsDown, LogOut, Briefcase, Flag, Clock, ClipboardPen } from "lucide-react";
import { api } from "@/lib/api";
import type { Card } from "@/lib/types";
import { STAGE_TONE, fmtTime } from "@/lib/labels";
import { Avatar } from "@/components/brand";
import { Badge, Empty, Metric, Segmented, Spinner, useToast, PageHeader } from "@/components/ui";
import { CalendarDays as CalendarDaysIcon } from "lucide-react";
import { can, useMe } from "@/components/AppShell";

type Scorecard = { id: number; interviewer: string; ratings: Record<string, number>; recommendation: string; notes: string };
type Row = { candidate_id: string; role: string; stage: string; scheduled_for: string | null; updated_at: string; card: Card; scorecards: Scorecard[] };
type Data = { rows: Row[]; stage_labels: Record<string, string>; role_names: Record<string, string> };

const AREAS: Record<string, string> = { P1: "Ground-level ops understanding", P2: "Builds what's needed, unasked", P3: "Owns decisions", P4: "Handles crises", P5: "Learns from failure" };
const REC: Record<string, string> = { strong_yes: "Strong yes", yes: "Yes", no: "No", strong_no: "Strong no" };
const VIEWS = { invited: "Waiting to book", scheduled: "Booked", interviewed: "Interviewed", outcomes: "Outcomes" } as const;
type View = keyof typeof VIEWS;
const isOutcome = (s: string) => ["selected", "not_selected", "withdrawn"].includes(s);

export default function Interviews() {
  const toast = useToast();
  const [data, setData] = useState<Data | null>(null);
  const [view, setView] = useState<View>("scheduled");
  const load = useCallback(() => api<Data>("/interviews").then(setData).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <Spinner />;

  const count = (s: string) => data.rows.filter((r) => r.stage === s).length;
  const rows = data.rows.filter((r) => (view === "outcomes" ? isOutcome(r.stage) : r.stage === view))
    .sort((a, b) => (a.scheduled_for ?? a.updated_at).localeCompare(b.scheduled_for ?? b.updated_at));

  return (
    <div className="space-y-5">
      <PageHeader icon={<CalendarDaysIcon className="h-6 w-6" />} title="Interviews" tone="info">Everyone you invited, from booking to outcome. Bookings made through Cal.com or Calendly update here automatically; you can also set them by hand.</PageHeader>
      {!data.rows.length ? <Empty icon={<CalendarDays className="h-5 w-5" />}>Nobody invited yet. Invite candidates from the Shortlist.</Empty> : (
        <>
          <div className="flex flex-wrap gap-3">
            <Metric label="Waiting to book" value={count("invited")} />
            <Metric label="Booked" value={count("scheduled")} />
            <Metric label="Interviewed" value={count("interviewed")} />
            <Metric label="Outcome recorded" value={data.rows.filter((r) => isOutcome(r.stage)).length} />
          </div>
          <Segmented value={view} options={Object.keys(VIEWS) as View[]} labels={VIEWS} onChange={setView} />
          {!rows.length && <Empty>Nobody here right now.</Empty>}
          {rows.map((r) => <InterviewCard key={r.candidate_id} row={r} data={data} onChange={load} />)}
        </>
      )}
    </div>
  );
}

function InterviewCard({ row, data, onChange }: { row: Row; data: Data; onChange: () => void }) {
  const me = useMe();
  const toast = useToast();
  const [panel, setPanel] = useState<"time" | "score" | null>(null);
  const [when, setWhen] = useState("");
  const [ratings, setRatings] = useState<Record<string, number>>({ P1: 3, P2: 3, P3: 3, P4: 3, P5: 3 });
  const [rec, setRec] = useState("");
  const [notes, setNotes] = useState("");
  const c = row.card;

  const stage = async (s: string, scheduled_for?: string) => {
    try { await api(`/interviews/${c.id}/stage`, { body: { stage: s, scheduled_for } }); setPanel(null); onChange(); }
    catch (e: any) { toast(e.message, true); }
  };
  const saveCard = async () => {
    try { await api(`/interviews/${c.id}/scorecard`, { body: { ratings, recommendation: rec, notes } }); setPanel(null); onChange(); toast("Scorecard saved"); }
    catch (e: any) { toast(e.message, true); }
  };

  return (
    <article className="card space-y-3 p-4 md:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Avatar id={c.id} name={c.name} size={40} />
        <h3 className="mr-1 font-display text-lg font-bold">{c.id}{c.name && <span className="font-medium text-muted"> · {c.name}</span>}</h3>
        <Badge tone="info" icon={<Briefcase className="h-3.5 w-3.5" />}>{data.role_names[row.role] ?? row.role}</Badge>
        <Badge tone={STAGE_TONE[row.stage] ?? "neutral"} icon={<Flag className="h-3.5 w-3.5" />}>{data.stage_labels[row.stage]}</Badge>
        {row.scheduled_for && <Badge tone="violet" icon={<Clock className="h-3.5 w-3.5" />}>{fmtTime(row.scheduled_for)} IST</Badge>}
        {row.scorecards.length > 0 && <Badge tone="good" icon={<ClipboardPen className="h-3.5 w-3.5" />}>{row.scorecards.length} scorecard(s): {row.scorecards.map((s) => REC[s.recommendation]).join(", ")}</Badge>}
      </div>
      {c.rationale && <p className="muted">{c.rationale}</p>}
      <div className="grid gap-5 md:grid-cols-5">
        <div className="space-y-2 text-sm md:col-span-3">
          <div className="font-semibold">Questions to ask</div>
          <ol className="list-decimal space-y-1 pl-5">{c.probes.map((p, i) => <li key={i}>{p}</li>)}</ol>
          {row.scorecards.map((s) => (
            <p key={s.id} className="rounded-lg bg-sunken px-3 py-2"><b>{s.interviewer}</b>: {REC[s.recommendation]} · {Object.entries(s.ratings).map(([k, v]) => `${k} ${v}/5`).join(" · ")}
              {s.notes && <><br /><i className="text-muted">{s.notes}</i></>}</p>
          ))}
        </div>
        <div className="space-y-2 md:col-span-2">
          {isOutcome(row.stage) ? <p className="text-sm text-good">{data.stage_labels[row.stage]} · {fmtTime(row.updated_at)}</p> : (
            <>
              <div className="flex flex-wrap gap-2">
                {can(me, "schedule") && <button className="btn" onClick={() => setPanel(panel === "time" ? null : "time")}><CalendarClock className="h-4 w-4" /> Set interview time</button>}
                {can(me, "schedule") && row.stage === "scheduled" && <button className="btn" onClick={() => stage("interviewed")}><Check className="h-4 w-4" /> Mark as interviewed</button>}
                {can(me, "scorecard") && <button className="btn" onClick={() => setPanel(panel === "score" ? null : "score")}><ClipboardPen className="h-4 w-4" /> Add my scorecard</button>}
              </div>
              {panel === "time" && (
                <div className="space-y-2 rounded-lg bg-sunken p-3">
                  <label className="label">Date and time (your local time)</label>
                  <input type="datetime-local" className="input" value={when} onChange={(e) => setWhen(e.target.value)} />
                  <button className="btn btn-primary" disabled={!when} onClick={() => stage("scheduled", new Date(when).toISOString())}>Save booking</button>
                </div>
              )}
              {panel === "score" && (
                <div className="space-y-2 rounded-lg bg-sunken p-3 text-sm">
                  {Object.entries(AREAS).map(([k, lbl]) => (
                    <label key={k} className="block">{lbl}: <b>{ratings[k]}</b>/5
                      <input type="range" min={1} max={5} value={ratings[k]} className="w-full accent-[rgb(var(--accent))]"
                        onChange={(e) => setRatings({ ...ratings, [k]: Number(e.target.value) })} />
                    </label>
                  ))}
                  <Segmented value={rec} options={Object.keys(REC)} labels={REC} onChange={setRec} />
                  <textarea className="input" rows={3} placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
                  <button className="btn btn-primary" disabled={!rec} onClick={saveCard}>Save scorecard</button>
                </div>
              )}
              {can(me, "decide") && ["scheduled", "interviewed"].includes(row.stage) && (
                <div className="space-y-1">
                  <div className="text-sm font-semibold">Outcome</div>
                  <div className="flex flex-wrap gap-2">
                    <button className="btn btn-primary" title="No email is sent. Offers are handled outside this system." onClick={() => stage("selected")}><ThumbsUp className="h-4 w-4" /> Selected</button>
                    <button className="btn" title="Sends a kind post-interview email after the undo window." onClick={() => stage("not_selected")}><ThumbsDown className="h-4 w-4" /> Not selected</button>
                    <button className="btn" onClick={() => stage("withdrawn")}><LogOut className="h-4 w-4" /> Withdrew</button>
                  </div>
                  <p className="text-xs text-muted">Selected sends nothing: offers stay outside this system.</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </article>
  );
}
