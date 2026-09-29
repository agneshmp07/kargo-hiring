"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, ChevronLeft, ChevronRight, PartyPopper, Keyboard, CalendarCheck, Pause } from "lucide-react";
import type { Board, Card } from "@/lib/types";
import { BAND_RANK } from "@/lib/labels";
import CandidateCard from "./CandidateCard";
import { Confetti } from "./brand";

type Decision = "Advance" | "Pass" | "Hold";
const EXIT: Record<Decision, string> = { Advance: "animate-out-right", Pass: "animate-out-left", Hold: "animate-out-down" };

/** One candidate at a time, full screen, keyboard first: I invite · P pass · H hold · → skip · ← back. */
export default function ReviewDeck({ board, role, onClose, reload }: {
  board: Board; role: string; onClose: () => void; reload: () => void;
}) {
  // The queue is fixed when the deck opens, so decided cards don't reshuffle it.
  const queue = useMemo(() => board.cards
    .filter((c) => c.primary_role === role && (!c.decision || c.decision.decision === "Hold"))
    .sort((a, b) => BAND_RANK[b.results[role].band] - BAND_RANK[a.results[role].band] || b.results[role].final - a.results[role].final)
    .map((c) => c.id),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [role]);
  const [i, setI] = useState(0);
  const [exit, setExit] = useState<string>("");
  const [tally, setTally] = useState<Record<Decision, number>>({ Advance: 0, Pass: 0, Hold: 0 });
  const box = useRef<HTMLDivElement>(null);
  const byId = Object.fromEntries(board.cards.map((c) => [c.id, c])) as Record<string, Card>;
  const card = queue[i] ? byId[queue[i]] : null;
  const done = i >= queue.length;

  const next = useCallback(() => setI((x) => Math.min(x + 1, queue.length)), [queue.length]);
  const prev = useCallback(() => setI((x) => Math.max(x - 1, 0)), []);

  const decided = (d: Decision) => {
    setTally((t) => ({ ...t, [d]: t[d] + 1 }));
    setExit(EXIT[d]);
    setTimeout(() => { setExit(""); next(); }, 280);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      if (e.key === "Escape") return onClose();
      if (done) return;
      const action = { i: "Advance", p: "Pass", h: "Hold" }[e.key.toLowerCase()];
      if (action) {
        const btn = box.current?.querySelector<HTMLButtonElement>(`[data-action="${action}"]`);
        if (btn && !btn.disabled) { e.preventDefault(); btn.click(); }
      } else if (e.key === "ArrowRight" || e.key.toLowerCase() === "s") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [done, next, prev, onClose]);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, []);

  const total = queue.length;
  const pct = total ? (Math.min(i, total) / total) * 100 : 100;

  // Rendered on <body> so no animated/transformed ancestor can shrink the full-screen layer.
  return createPortal(
    <div className="fixed inset-0 z-50 flex flex-col bg-bg/95 backdrop-blur-xl" role="dialog" aria-modal="true" aria-label="Review candidates">
      {/* top bar */}
      <div className="border-b border-line/70 bg-surface/70">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-3">
          <div className="min-w-0">
            <div className="font-display text-base font-bold">Review · {board.role_names[role] ?? role}</div>
            <div className="text-xs text-muted">{done ? "All done" : `${i + 1} of ${total}`} · invited {tally.Advance} · passed {tally.Pass} · held {tally.Hold}</div>
          </div>
          <div className="ml-auto hidden items-center gap-1.5 text-xs text-muted md:flex">
            <Keyboard className="h-4 w-4" />
            <span className="kbd">I</span> invite <span className="kbd">P</span> pass <span className="kbd">H</span> hold <span className="kbd">→</span> skip <span className="kbd">Esc</span> close
          </div>
          <button className="btn btn-ghost ml-auto px-2 md:ml-2" onClick={onClose} aria-label="Close review"><X className="h-5 w-5" /></button>
        </div>
        <div className="h-1 bg-sunken"><div className="h-full bg-gradient-to-r from-accent to-accent2 transition-all duration-500" style={{ width: `${pct}%` }} /></div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-4 py-6">
          {done ? (
            <div className="mx-auto max-w-md animate-pop py-16 text-center">
              {tally.Advance + tally.Pass + tally.Hold > 0 && <Confetti />}
              <div className="mx-auto grid h-20 w-20 place-items-center rounded-3xl bg-accent/10 text-accent"><PartyPopper className="h-10 w-10" /></div>
              <h2 className="mt-5 font-display text-3xl font-bold">{total ? "That's the queue cleared" : "Nothing waiting here"}</h2>
              <p className="mt-2 text-muted">
                {total ? `You invited ${tally.Advance}, passed ${tally.Pass} and held ${tally.Hold}. Emails wait in the undo window, so you can still change your mind from the Shortlist.`
                  : "Every candidate in this role already has a decision."}
              </p>
              <div className="mt-6 flex justify-center gap-2">
                <button className="btn" onClick={() => setI(0)} disabled={!total}><ChevronLeft className="h-4 w-4" /> Look again</button>
                <button className="btn btn-primary" onClick={onClose}>Back to the Shortlist</button>
              </div>
            </div>
          ) : card && (
            <div ref={box} key={card.id} className={exit || "animate-pop"}>
              <CandidateCard card={card} role={role} board={board} onChange={reload} keys onDecided={decided} />
            </div>
          )}
        </div>
      </div>

      {!done && (
        <div className="border-t border-line/70 bg-surface/70">
          <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-2.5">
            <button className="btn btn-ghost" onClick={prev} disabled={i === 0}><ChevronLeft className="h-4 w-4" /> Previous</button>
            <span className="hidden text-xs text-muted sm:flex sm:items-center sm:gap-3">
              <span className="flex items-center gap-1"><CalendarCheck className="h-3.5 w-3.5 text-accent" /> Invite sends an interview email</span>
              <span className="flex items-center gap-1"><Pause className="h-3.5 w-3.5" /> Hold sends nothing</span>
            </span>
            <button className="btn btn-ghost" onClick={next}>Skip <ChevronRight className="h-4 w-4" /></button>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
