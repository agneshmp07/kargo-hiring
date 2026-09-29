"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw, Mail } from "lucide-react";
import { api } from "@/lib/api";
import { EMAIL_STATUS, fmtTime } from "@/lib/labels";
import { Badge, Empty, Modal, Spinner, Tabs, useToast, PageHeader } from "@/components/ui";
import { History as HistoryIcon } from "lucide-react";
import { can, useMe } from "@/components/AppShell";

type Dec = { id: number; ts: string; candidate_id: string; name: string; role: string; decision: string; undone_at: string | null; decided_by: string | null; band: string; final: number; gate: string; floors: string[]; source: string; rationale_shown: string };
type Msg = { id: number; candidate_id: string | null; kind: string; channel: string; to_addr: string; subject: string; status: string; attempts: number; provider_event: string | null; error: string | null; send_after: string; updated_at: string };
type Data = { decisions: Dec[]; messages: Msg[]; log: { ts: string; event: string; data: string }[] };

const csv = (rows: Dec[]) => {
  const cols: (keyof Dec)[] = ["ts", "candidate_id", "name", "role", "decision", "undone_at", "decided_by", "band", "final", "gate", "floors", "source", "rationale_shown"];
  const esc = (v: unknown) => `"${String(Array.isArray(v) ? v.join(", ") : v ?? "").replace(/"/g, '""')}"`;
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
};

export default function History() {
  const me = useMe();
  const toast = useToast();
  const [d, setD] = useState<Data | null>(null);
  const [tab, setTab] = useState<"d" | "m" | "a">("d");
  const [view, setView] = useState<{ subject: string; body: string; channel: string } | null>(null);
  const load = useCallback(() => api<Data>("/history").then(setD).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Spinner />;

  const download = () => {
    const url = URL.createObjectURL(new Blob([csv(d.decisions)], { type: "text/csv" }));
    Object.assign(document.createElement("a"), { href: url, download: "decision_log.csv" }).click();
    URL.revokeObjectURL(url);
  };
  const retry = async (id: number) => {
    try { const r = await api(`/messages/${id}/retry`, { method: "POST" }); toast(`Status: ${EMAIL_STATUS[r.status] ?? r.status}`); load(); }
    catch (e: any) { toast(e.message, true); }
  };
  const open = async (id: number) => {
    try { setView(await api(`/messages/${id}`)); } catch (e: any) { toast(e.message, true); }
  };

  return (
    <div className="space-y-5">
      <PageHeader icon={<HistoryIcon className="h-6 w-6" />} title="History" tone="neutral">Every decision, every message and every change, with who did it and when.</PageHeader>
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "d", label: `Decisions (${d.decisions.length})` }, { id: "m", label: `Messages (${d.messages.length})` }, { id: "a", label: "Activity log" }]} />

      {tab === "d" && (d.decisions.length ? (
        <div className="space-y-2">
          <button className="btn" onClick={download}><Download className="h-4 w-4" /> Download as CSV</button>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-line text-left text-muted">{["When", "Candidate", "Role", "Decision", "By", "Band", "Score", "Gate", "Safety nets"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{d.decisions.map((r) => (
                <tr key={r.id} className={`border-b border-line last:border-0 ${r.undone_at ? "text-muted line-through" : ""}`}>
                  <td className="whitespace-nowrap px-3 py-2">{fmtTime(r.ts)}</td>
                  <td className="whitespace-nowrap px-3 py-2">{r.candidate_id}{r.name && ` · ${r.name}`}</td>
                  <td className="px-3 py-2">{r.role}</td>
                  <td className="px-3 py-2">{r.decision === "Advance" ? "Invite" : r.decision}{r.undone_at && " (undone)"}</td>
                  <td className="px-3 py-2">{r.decided_by ?? "-"}</td>
                  <td className="px-3 py-2">{r.band}</td>
                  <td className="px-3 py-2 tabular-nums">{Math.round(r.final)}</td>
                  <td className="px-3 py-2">{r.gate}</td>
                  <td className="px-3 py-2 text-xs">{r.floors.join(", ") || "-"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      ) : <Empty>No decisions yet.</Empty>)}

      {tab === "m" && (d.messages.length ? (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line text-left text-muted">{["", "To", "Kind", "Channel", "Status", "Updated", ""].map((h, i) => <th key={i} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{d.messages.map((m) => (
              <tr key={m.id} className="border-b border-line last:border-0">
                <td className="px-3 py-2"><button className="btn btn-ghost px-1.5 py-0.5" onClick={() => open(m.id)} aria-label="Read message"><Mail className="h-4 w-4" /></button></td>
                <td className="px-3 py-2">{m.candidate_id ?? m.to_addr}</td>
                <td className="px-3 py-2">{m.kind.replace(/_/g, " ")}</td>
                <td className="px-3 py-2">{m.channel}</td>
                <td className="px-3 py-2"><Badge tone={["failed", "bounced", "suppressed", "complained"].includes(m.status) ? "bad" : ["scheduled", "sending"].includes(m.status) ? "warn" : m.status === "cancelled" ? "neutral" : "good"}>{EMAIL_STATUS[m.status] ?? m.status}</Badge>
                  {m.error && <div className="mt-1 text-xs text-bad">{m.error}</div>}</td>
                <td className="whitespace-nowrap px-3 py-2">{fmtTime(m.updated_at)}</td>
                <td className="px-3 py-2">{m.status === "failed" && can(me, "decide") && <button className="btn py-1" onClick={() => retry(m.id)}><RefreshCw className="h-3.5 w-3.5" /> Try again</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <Empty>No messages yet. Messages are only created after someone decides.</Empty>)}

      {tab === "a" && (
        <div className="card divide-y divide-line text-sm">
          {d.log.map((l, i) => (
            <div key={i} className="grid grid-cols-[150px_180px_1fr] gap-3 px-3 py-1.5">
              <span className="text-muted">{fmtTime(l.ts)}</span><span className="font-medium">{l.event.replace(/_/g, " ")}</span>
              <span className="truncate font-mono text-xs text-muted" title={l.data}>{l.data}</span>
            </div>
          ))}
        </div>
      )}

      <Modal open={!!view} title={view?.subject || `${view?.channel} message`} onClose={() => setView(null)}>
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap font-sans text-sm">{view?.body}</pre>
      </Modal>
    </div>
  );
}
