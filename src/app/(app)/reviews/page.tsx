"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { Card, Review } from "@/lib/types";
import CandidateCard from "@/components/CandidateCard";
import { Empty, Segmented, Spinner, useToast, PageHeader } from "@/components/ui";
import { UsersRound as UsersRoundIcon } from "lucide-react";

type Data = { mine: (Review & { card: Card })[]; asked: Review[]; role_names: Record<string, string> };
const OPTS: Record<string, string> = { Advance: "Invite", Hold: "Hold", Pass: "Pass" };

export default function Reviews() {
  const toast = useToast();
  const [data, setData] = useState<Data | null>(null);
  const [answers, setAnswers] = useState<Record<number, { op: string; note: string }>>({});
  const load = useCallback(() => api<Data>("/reviews/mine").then(setData).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <Spinner />;

  const send = async (id: number) => {
    const a = answers[id];
    try { await api(`/reviews/${id}/answer`, { body: { opinion: a?.op, note: a?.note ?? "" } }); toast("Opinion sent"); load(); }
    catch (e: any) { toast(e.message, true); }
  };

  return (
    <div className="space-y-5">
      <PageHeader icon={<UsersRoundIcon className="h-6 w-6" />} title="Second opinions" tone="violet">Teammates asked what you think. Your opinion shows on the card; the decision-maker still decides.</PageHeader>
      {!data.mine.length && <Empty icon={<CheckCheck className="h-5 w-5" />}>Nothing waiting for you.</Empty>}
      {data.mine.map((r) => (
        <div key={r.id} className="space-y-2">
          <p className="text-sm"><b>{r.requested_by}</b> asked for your view on <b>{r.candidate_id}</b></p>
          <CandidateCard card={r.card} role={r.role} board={{ role_names: data.role_names, users: [] }} onChange={load} showButtons={false} />
          <div className="card flex flex-wrap items-center gap-2 p-3">
            <Segmented value={answers[r.id]?.op ?? ""} options={Object.keys(OPTS)} labels={OPTS}
              onChange={(op) => setAnswers({ ...answers, [r.id]: { note: answers[r.id]?.note ?? "", op } })} />
            <input className="input min-w-[200px] flex-1" placeholder="Why (one line)" value={answers[r.id]?.note ?? ""}
              onChange={(e) => setAnswers({ ...answers, [r.id]: { op: answers[r.id]?.op ?? "", note: e.target.value } })} />
            <button className="btn btn-primary" disabled={!answers[r.id]?.op} onClick={() => send(r.id)}>Send my opinion</button>
          </div>
        </div>
      ))}
      {data.asked.length > 0 && (
        <div>
          <h2 className="h2 mb-2">Opinions you asked for</h2>
          <ul className="card divide-y divide-line text-sm">
            {data.asked.map((r) => (
              <li key={r.id} className="px-4 py-2">{r.candidate_id} · {r.assignee}: {r.status === "done" ? <><b>{OPTS[r.opinion ?? ""] ?? r.opinion}</b>{r.note && `: ${r.note}`}</> : <span className="text-muted">waiting</span>}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
