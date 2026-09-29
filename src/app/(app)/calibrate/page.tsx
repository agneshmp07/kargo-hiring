"use client";

import { useCallback, useEffect, useState } from "react";
import { Star, Scale, MinusCircle, Inbox } from "lucide-react";
import { api } from "@/lib/api";
import { Callout, Empty, Metric, Spinner, useToast, PageHeader } from "@/components/ui";
import { SlidersHorizontal as SlidersHorizontalIcon } from "lucide-react";

type Summary = {
  rated: number; "agreement_%": number | null; table: Record<string, Record<string, number>>;
  disagreements: { candidate_id: string; rating: string; system_band: string }[]; verdict: string | null;
};
type Data = { next: { id: string; role: string; text: string } | null; mine: Summary; team: Summary; role_names: Record<string, string> };
const BANDS = ["Strong", "Borderline", "Not a fit"] as const;
const ICON = { Strong: Star, Borderline: Scale, "Not a fit": MinusCircle };

export default function Calibrate() {
  const toast = useToast();
  const [data, setData] = useState<Data | null>(null);
  const load = useCallback(() => api<Data>("/calibrate").then(setData).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <Spinner />;
  const { next, mine, team } = data;

  const rate = async (rating: string) => {
    try { await api("/calibrate", { body: { candidate_id: next!.id, role: next!.role, rating } }); load(); }
    catch (e: any) { toast(e.message, true); }
  };

  return (
    <div className="space-y-5">
      <PageHeader icon={<SlidersHorizontalIcon className="h-6 w-6" />} title="Calibrate" tone="good">The weights come from only 8 past hires, so check them against your own judgement. Rate <b>10 CVs</b> without seeing the system&apos;s answer, then compare. If you disagree on more than 2, revisit the weights before clearing a full batch.</PageHeader>
      <div className="space-y-1">
        <div className="h-2 overflow-hidden rounded-full bg-sunken"><div className="h-full bg-accent" style={{ width: `${Math.min(mine.rated, 10) * 10}%` }} /></div>
        <p className="text-xs text-muted">{mine.rated} of 10 rated</p>
      </div>
      {next ? (
        <div className="card space-y-3 p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="h2">{next.id} · {data.role_names[next.role] ?? next.role}</h2>
            <span className="text-xs text-muted">Identity removed · system rating hidden</span>
          </div>
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg bg-sunken p-4 font-sans text-sm leading-relaxed">{next.text}</pre>
          <div className="flex flex-wrap gap-2">
            {BANDS.map((b) => {
              const I = ICON[b];
              return <button key={b} className={`btn ${b === "Strong" ? "btn-primary" : ""}`} onClick={() => rate(b)}><I className="h-4 w-4" /> {b}</button>;
            })}
          </div>
        </div>
      ) : mine.rated === 0 && <Empty icon={<Inbox className="h-5 w-5" />}>No CVs to rate yet. Add some first.</Empty>}

      {mine.rated > 0 && (
        <div className="space-y-3">
          <h2 className="h2">How you compare</h2>
          {mine.verdict && <Callout tone={mine.verdict.startsWith("Good") ? "good" : "warn"}>{mine.verdict}</Callout>}
          <div className="flex flex-wrap gap-3">
            <Metric label="Agreement with the system" value={`${mine["agreement_%"]}%`} />
            {team.rated > mine.rated && <Metric label="Whole team" value={`${team["agreement_%"]}%`} hint={`${team.rated} ratings`} />}
          </div>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-line text-left text-muted"><th className="px-3 py-2">You said ↓ · System said →</th>{BANDS.map((b) => <th key={b} className="px-3 py-2">{b}</th>)}</tr></thead>
              <tbody>{BANDS.map((h) => (
                <tr key={h} className="border-b border-line last:border-0"><td className="px-3 py-2 font-medium">{h}</td>
                  {BANDS.map((s) => <td key={s} className={`px-3 py-2 tabular-nums ${h === s ? "font-semibold text-good" : ""}`}>{mine.table[h]?.[s] ?? 0}</td>)}</tr>
              ))}</tbody>
            </table>
          </div>
          {mine.disagreements.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {mine.disagreements.map((d) => <li key={d.candidate_id}>{d.candidate_id}: you said <b>{d.rating}</b>, the system said <b>{d.system_band}</b></li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
