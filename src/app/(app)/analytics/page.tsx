"use client";

import { useCallback, useEffect, useState } from "react";
import { FileDown, Download, Scale, BarChart3, Timer, Hourglass, Handshake, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { Callout, Metric, PageHeader, Segmented, Spinner, useToast } from "@/components/ui";

type Data = {
  funnel: [string, number][]; speed: { decided: number; median_days: number | null; waiting: number };
  agreement: { table: Record<string, Record<string, number>>; "agreement_%": number | null; decided: number };
  outcomes: Record<string, Record<string, number>>;
  sources: { source: string; cvs: number; "recommended_%": number; "invited_%": number; selected: number }[];
  fairness: { city: string; cvs: number; recommended_rate: number; invited: number; impact_ratio: number | null; flag: boolean }[];
  spend: { total_usd: number; per_cv_usd: number | null; batches: { batch: string; cvs: number; mode: string; cost_usd: number }[] };
  roles: string[]; role_names: Record<string, string>;
};

function Table({ head, rows }: { head: string[]; rows: (string | number | null)[][] }) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-line text-left text-muted">{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-line last:border-0">{r.map((c, j) => <td key={j} className={`px-3 py-2 ${j ? "tabular-nums" : "font-medium"}`}>{c ?? "-"}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export default function Analytics() {
  const toast = useToast();
  const [role, setRole] = useState("");
  const [d, setD] = useState<Data | null>(null);
  const load = useCallback(() => api<Data>(`/analytics${role ? `?role=${role}` : ""}`).then(setD).catch((e) => toast(e.message, true)), [role, toast]);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Spinner />;
  const max = Math.max(1, ...d.funnel.map(([, n]) => n));
  const flagged = d.fairness.filter((f) => f.flag);
  const bands = ["Strong", "Borderline", "Not a fit"];

  return (
    <div className="space-y-6">
      <PageHeader icon={<BarChart3 className="h-6 w-6" />} title="Analytics" tone="info" actions={<>
        <a className="btn" href="/api/analytics/report.pdf"><FileDown className="h-4 w-4" /> Board report (PDF)</a>
        <a className="btn" href="/api/analytics/training.csv" title="AI codes plus real outcomes per candidate, for re-deriving the weights from more than 8 hires."><Download className="h-4 w-4" /> Training data (CSV)</a>
      </>}>How hiring is going, whether the recommendations hold up, and whether the process is fair.</PageHeader>
      <Segmented value={role} options={["", ...d.roles]} labels={{ "": "All roles", ...d.role_names }} onChange={setRole} />
      <div className="flex flex-wrap gap-3">
        <Metric label="Median days to a decision" value={d.speed.median_days ?? "-"} icon={<Timer className="h-5 w-5" />} tone="info" />
        <Metric label="Still waiting" value={d.speed.waiting} icon={<Hourglass className="h-5 w-5" />} tone="accent" />
        <Metric label="Agree with the recommendation" value={d.agreement["agreement_%"] != null ? `${d.agreement["agreement_%"]}%` : "-"} hint="Invite on Strong/Borderline, or Pass on Not a fit" icon={<Handshake className="h-5 w-5" />} tone="good" />
        <Metric label="AI spend" value={`$${d.spend.total_usd.toFixed(2)}`} hint={d.spend.per_cv_usd ? `Per CV: $${d.spend.per_cv_usd.toFixed(3)}` : "No AI calls yet"} icon={<Wallet className="h-5 w-5" />} tone="violet" />
      </div>

      <section className="space-y-2">
        <h2 className="h2">Funnel</h2>
        <div className="card space-y-2 p-4">
          {d.funnel.map(([stage, n]) => (
            <div key={stage} className="grid grid-cols-[minmax(120px,220px)_1fr_40px] items-center gap-3 text-sm">
              <span className="text-muted">{stage}</span>
              <div className="h-7 overflow-hidden rounded-lg bg-sunken"><div className="h-full rounded-lg bg-gradient-to-r from-accent to-accent2 transition-all duration-700" style={{ width: `${Math.max((100 * n) / max, n ? 4 : 0)}%` }} /></div>
              <span className="text-right font-display font-bold tabular-nums">{n}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-5 md:grid-cols-2">
        <section className="space-y-2">
          <h2 className="h2">Decisions vs recommendation</h2>
          <Table head={["Band", "Invited", "Passed", "Held"]} rows={bands.map((b) => [b, d.agreement.table[b].Advance, d.agreement.table[b].Pass, d.agreement.table[b].Hold])} />
        </section>
        <section className="space-y-2">
          <h2 className="h2">Interview outcomes by band</h2>
          <Table head={["Band", "Selected", "Not selected", "Withdrew", "In progress"]} rows={bands.map((b) => [b, d.outcomes[b].selected, d.outcomes[b].not_selected, d.outcomes[b].withdrawn, d.outcomes[b].open])} />
          <p className="text-xs text-muted">As outcomes come in, this shows whether the bands predict success.</p>
        </section>
      </div>

      <section className="space-y-2">
        <h2 className="h2">Where candidates come from</h2>
        <Table head={["Source", "CVs", "Recommended %", "Invited %", "Selected"]} rows={d.sources.map((s) => [s.source, s.cvs, s["recommended_%"], s["invited_%"], s.selected])} />
      </section>

      <section className="space-y-2">
        <h2 className="h2">Fairness check</h2>
        <p className="muted">Recommendation rates by city. A group is flagged when its rate is under 80% of the best group&apos;s (the four-fifths rule), with at least 5 CVs. Gender, age and similar are never collected, so they can&apos;t be checked here. This check never changes any score.</p>
        <Callout tone={flagged.length ? "warn" : "good"} icon={<Scale className="h-4 w-4" />}>{flagged.length ? `Worth a look: ${flagged.map((f) => f.city).join(", ")}` : "No group flagged."}</Callout>
        <Table head={["City", "CVs", "Recommended %", "Invited", "Ratio to best"]} rows={d.fairness.map((f) => [f.city, f.cvs, f.recommended_rate, f.invited, f.impact_ratio])} />
      </section>

      {d.spend.batches.length > 0 && (
        <section className="space-y-2">
          <h2 className="h2">AI spend by batch</h2>
          <Table head={["Batch", "CVs", "Mode", "Cost (USD)"]} rows={d.spend.batches.map((b) => [b.batch, b.cvs, b.mode, b.cost_usd.toFixed(4)])} />
        </section>
      )}
    </div>
  );
}
