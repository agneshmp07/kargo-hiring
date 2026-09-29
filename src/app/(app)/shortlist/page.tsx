"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCheck, Inbox, PauseCircle, PartyPopper, Search, ThumbsUp, Flag, Undo2, Play, Hourglass, Star, Scale, MinusCircle, Dices } from "lucide-react";
import { api } from "@/lib/api";
import type { Board, Card } from "@/lib/types";
import { BAND_RANK, EMAIL_STATUS, fmtTime } from "@/lib/labels";
import CandidateCard, { BandBadge } from "@/components/CandidateCard";
import { Empty, Metric, Modal, Segmented, Spinner, Tabs, useToast } from "@/components/ui";
import { can, useMe } from "@/components/AppShell";
import { ProgressRing } from "@/components/brand";
import ReviewDeck from "@/components/ReviewDeck";

function greeting() {
  const h = Number(new Date().toLocaleString("en-IN", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }));
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const isOpen = (c: Card) => !c.decision || c.decision.decision === "Hold";

export default function Shortlist() {
  const me = useMe();
  const toast = useToast();
  const [board, setBoard] = useState<Board | null>(null);
  const [tab, setTab] = useState<string>("");
  const [show, setShow] = useState<"waiting" | "all">("waiting");
  const [q, setQ] = useState("");
  const [bulkRole, setBulkRole] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);

  const load = useCallback(() => api<Board>("/board").then((b) => {
    setBoard(b);
    setTab((t) => t || b.roles[0]);
  }).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { load(); }, [load]);

  const byId = useMemo(() => Object.fromEntries((board?.cards ?? []).map((c) => [c.id, c])), [board]);
  if (!board) return <Spinner />;
  const { cards, roles, role_names: names } = board;

  const open = cards.filter(isOpen);
  const bandOf = (c: Card) => c.results[c.primary_role].band;
  const pendingSpots = board.spots.filter((s) => s.verdict === null);
  const holds = cards.filter((c) => c.decision?.decision === "Hold");
  const backlog = cards.filter((c) => c.backlog && isOpen(c));
  const recent = cards.filter((c) => c.decision && c.decision.decision !== "Hold" && c.undoable);

  const verdict = async (id: number, v: "correct" | "missed") => {
    try { await api(`/spot-checks/${id}`, { body: { verdict: v } }); toast("Thanks, your check is logged"); load(); }
    catch (e: any) { toast(e.message, true); }
  };
  const undo = async (c: Card) => {
    try { await api(`/decisions/${c.decision!.id}/undo`, { method: "POST" }); toast("Undone. The email was cancelled before sending."); load(); }
    catch (e: any) { toast(e.message, true); }
  };
  const bulkPass = async () => {
    try { const r = await api("/bulk-pass", { body: { role: bulkRole } }); toast(`Passed ${r.count}. Each can be undone for a few minutes.`); setBulkRole(null); load(); }
    catch (e: any) { toast(e.message, true); }
  };

  const tabs = [
    ...roles.map((r) => ({ id: r, label: `${names[r]} (${cards.filter((c) => c.primary_role === r && isOpen(c)).length})` })),
    { id: "_hold", label: `On hold (${holds.length})` },
    { id: "_spot", label: `Random check (${pendingSpots.length})` },
    { id: "_backlog", label: `Backlog (${backlog.length})` },
  ];

  const reviewRole = roles.includes(tab) ? tab : roles[0];
  const waitingInRole = cards.filter((c) => c.primary_role === reviewRole && isOpen(c)).length;

  return (
    <div className="space-y-6">
      {/* ---------------- hero ---------------- */}
      <section className="card relative overflow-hidden p-5 md:p-7">
        <div className="pointer-events-none absolute -right-16 -top-24 h-64 w-64 rounded-full bg-accent/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 left-1/3 h-56 w-56 rounded-full bg-accent2/10 blur-3xl" />
        <div className="relative grid grid-cols-[auto_1fr] items-center gap-x-5 gap-y-4 md:grid-cols-[auto_1fr_auto] md:gap-x-6">
          <ProgressRing done={cards.length - open.length} total={cards.length} />
          <div className="min-w-0">
            <p className="text-sm font-medium text-muted">{greeting()}, {me.user.display_name.split(" ")[0]}</p>
            <h1 className="mt-0.5 font-display text-2xl font-bold leading-tight tracking-tight md:text-3xl">{open.length ? <>{open.length} candidate{open.length === 1 ? "" : "s"} waiting for you</> : "You're all caught up"}</h1>
            <p className="muted mt-1 hidden max-w-xl sm:block">The system recommends; you decide. Nothing reaches a candidate until you click, and emails wait {board.undo_minutes} minute{board.undo_minutes === 1 ? "" : "s"} so you can undo.</p>
          </div>
          {can(me, "decide") && waitingInRole > 0 && (
            <button className="btn btn-primary col-span-2 px-5 py-2.5 text-base md:col-span-1" onClick={() => setReviewing(true)}>
              <Play className="h-4 w-4 fill-current" /> Start review
              <span className="ml-1 rounded-full bg-white/20 px-2 text-xs">{waitingInRole}</span>
            </button>
          )}
        </div>
      </section>

      {recent.length > 0 && can(me, "decide") && (
        <div className="card space-y-2 border-accent/30 bg-accent/5 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold"><Undo2 className="h-4 w-4 text-accent" /> Undo a recent decision</div>
          {recent.map((c) => (
            <div key={c.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span>{c.decision!.decision === "Advance" ? "Invited" : "Passed"} <b>{c.id}{c.name && ` · ${c.name}`}</b> · email {EMAIL_STATUS[c.email_status ?? ""] ?? ""}{c.email_send_after && `, goes out ${fmtTime(c.email_send_after)}`}</span>
              <button className="btn ml-auto py-1" onClick={() => undo(c)}><Undo2 className="h-4 w-4" /> Undo</button>
            </div>
          ))}
        </div>
      )}

      {!cards.length ? <Empty icon={<Inbox className="h-5 w-5" />}>No candidates yet. Go to <b>Add CVs</b> to upload some.</Empty> : (
        <>
          <div className="flex flex-wrap gap-3">
            <Metric label="Waiting" value={open.length} icon={<Hourglass className="h-5 w-5" />} tone="accent" />
            <Metric label="Strong" value={open.filter((c) => bandOf(c) === "Strong").length} icon={<Star className="h-5 w-5" />} tone="good" />
            <Metric label="Borderline" value={open.filter((c) => bandOf(c) === "Borderline").length} icon={<Scale className="h-5 w-5" />} tone="warn" />
            <Metric label="Not a fit" value={open.filter((c) => bandOf(c) === "Not a fit").length} icon={<MinusCircle className="h-5 w-5" />} />
            <Metric label="Random checks" value={pendingSpots.length} icon={<Dices className="h-5 w-5" />} tone="violet" />
          </div>

          <Tabs value={tab} tabs={tabs} onChange={setTab} />

          {roles.includes(tab) && (() => {
            const list = cards.filter((c) => c.primary_role === tab)
              .filter((c) => (show === "all" || isOpen(c)) && (!q || c.id.includes(q.trim().toUpperCase())))
              .sort((a, b) => BAND_RANK[b.results[tab].band] - BAND_RANK[a.results[tab].band] || b.results[tab].final - a.results[tab].final);
            const bulk = board.bulk[tab] ?? [];
            let current = "";
            return (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Segmented value={show} options={["waiting", "all"]} labels={{ waiting: "Waiting for a decision", all: "Everyone" }} onChange={setShow} />
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted" />
                    <input className="input w-52 pl-8" placeholder="Find by ID, e.g. KG-0004" value={q} onChange={(e) => setQ(e.target.value)} />
                  </div>
                  {can(me, "decide") && (
                    <button className="btn ml-auto" disabled={!bulk.length} onClick={() => setBulkRole(tab)}>
                      <CheckCheck className="h-4 w-4" /> Pass all &lsquo;Not a fit&rsquo; ({bulk.length})
                    </button>
                  )}
                </div>
                <p className="text-xs text-muted"><b>Invite</b> sends an interview email with a booking link · <b>Pass</b> sends a polite rejection · <b>Hold</b> sends nothing and reminds you in 7 days.</p>
                {!list.length && <Empty icon={<PartyPopper className="h-5 w-5" />}>All done here. Every candidate in this role has a decision.</Empty>}
                {list.map((c) => {
                  const band = c.results[tab].band;
                  const header = band !== current ? (current = band) : null;
                  return (
                    <div key={c.id} className="space-y-3">
                      {header && <div className="flex items-center gap-2 pt-2"><BandBadge band={band} /><span className="text-sm text-muted">{list.filter((x) => x.results[tab].band === band).length}</span></div>}
                      <CandidateCard card={c} role={tab} board={board} onChange={load} />
                    </div>
                  );
                })}
              </div>
            );
          })()}

          {tab === "_hold" && (
            <div className="space-y-3">
              <p className="muted">Candidates you put on hold. They show a reminder after 7 days.</p>
              {!holds.length && <Empty icon={<PauseCircle className="h-5 w-5" />}>Nothing on hold.</Empty>}
              {holds.map((c) => <CandidateCard key={c.id} card={c} role={c.decision!.role} board={board} onChange={load} />)}
            </div>
          )}

          {tab === "_spot" && (
            <div className="space-y-3">
              <p className="muted">Random CVs the system marked &lsquo;Not a fit&rsquo;. Take a quick look. If one deserves a second chance, flag it: it&apos;s kept out of the bulk Pass so you can decide it yourself.</p>
              {!pendingSpots.length && <Empty icon={<CheckCheck className="h-5 w-5" />}>Nothing to check right now.</Empty>}
              {pendingSpots.map((s) => byId[s.candidate_id] && (
                <div key={s.id} className="space-y-2">
                  {can(me, "decide") && (
                    <div className="flex gap-2">
                      <button className="btn" onClick={() => verdict(s.id, "correct")}><ThumbsUp className="h-4 w-4" /> Agree: not a fit</button>
                      <button className="btn btn-primary" onClick={() => verdict(s.id, "missed")}><Flag className="h-4 w-4" /> We missed this one</button>
                    </div>
                  )}
                  <CandidateCard card={byId[s.candidate_id]} role={s.role} board={board} onChange={load} showButtons={false} />
                </div>
              ))}
              {board.spots.some((s) => s.verdict) && (
                <p className="text-xs text-muted">Past checks: {board.spots.filter((s) => s.verdict).map((s) => `${s.candidate_id} (${s.verdict === "missed" ? "missed" : "agreed"})`).join(", ")}</p>
              )}
            </div>
          )}

          {tab === "_backlog" && (
            <div className="space-y-3">
              <p className="muted">Older applications that were opened but never answered. Clear them with the same three buttons.</p>
              {!backlog.length && <Empty icon={<Inbox className="h-5 w-5" />}>No backlog.</Empty>}
              {backlog.map((c) => <CandidateCard key={c.id} card={c} role={c.primary_role} board={board} onChange={load} />)}
            </div>
          )}
        </>
      )}

      {reviewing && <ReviewDeck board={board} role={reviewRole} reload={load} onClose={() => { setReviewing(false); load(); }} />}

      <Modal open={!!bulkRole} title="Pass all 'Not a fit' candidates?" onClose={() => setBulkRole(null)}>
        {bulkRole && (
          <div className="space-y-3 text-sm">
            <p>This passes <b>{board.bulk[bulkRole]?.length}</b> {names[bulkRole]} candidate(s) and sends each a polite rejection email{me.mode.dry_run ? " (practice mode: saved, not sent)" : ""}.</p>
            <p className="text-muted">Left out: CVs in an open random check, and any you flagged as missed. {board.bulk[bulkRole]?.join(", ")}</p>
            <div className="flex justify-end gap-2">
              <button className="btn" onClick={() => setBulkRole(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={bulkPass}><CheckCheck className="h-4 w-4" /> Yes, pass them</button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
