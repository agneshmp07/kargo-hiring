"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, Play, RefreshCw, Globe, Mail, Download, KeyRound, FlaskConical, FileText, X } from "lucide-react";
import { api } from "@/lib/api";
import { Callout, Segmented, Spinner, useToast, PageHeader } from "@/components/ui";
import { Upload as UploadIcon } from "lucide-react";
import { can, useMe } from "@/components/AppShell";

type Pending = { pending: string[]; can_score: boolean; score_block: string | null; standin: boolean; role_names: Record<string, string>; inbox: boolean; careers_url: string; demo: boolean };
const EXT = [".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".md"];

export default function AddCVs() {
  const me = useMe();
  const toast = useToast();
  const [info, setInfo] = useState<Pending | null>(null);
  const [role, setRole] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [result, setResult] = useState<string>("");
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api<Pending>("/cvs/pending").then(setInfo).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { load(); }, [load]);
  if (!info) return <Spinner />;

  const add = (list: FileList | null) => {
    if (!list) return;
    const ok = Array.from(list).filter((f) => EXT.some((e) => f.name.toLowerCase().endsWith(e)));
    if (ok.length < list.length) toast("Some files were skipped: only PDF, Word and text files work.", true);
    setFiles((cur) => [...cur, ...ok.filter((f) => !cur.some((c) => c.name === f.name && c.size === f.size))]);
  };

  /** Score waiting CVs one per request, so each request stays inside Vercel's time limit. */
  const scoreAll = async (total: number) => {
    setProgress({ done: 0, total });
    let done = 0, failed = 0, cost = 0;
    try {
      for (let i = 0; i < total + 5; i++) {
        const r = await api("/cvs/score-next", { method: "POST" });
        done += r.scored.length;
        failed += r.parse_failures;
        cost += r.cost_usd ?? 0;
        setProgress({ done, total: Math.max(total, done + r.remaining) });
        if (!r.remaining || !r.scored.length) break;
      }
      setResult(`Done: ${done} CV(s) scored.${failed ? ` ${failed} couldn't be read and are marked for you to check.` : ""}${cost ? ` AI cost $${cost.toFixed(3)}.` : ""} Open the Shortlist to review them.`);
    } catch (e: any) {
      toast(`Scoring stopped: ${e.message}`, true);
    } finally {
      setProgress(null);
      load();
    }
  };

  const save = async () => {
    const form = new FormData();
    form.append("role", role);
    files.forEach((f) => form.append("files", f));
    try {
      const r = await api("/cvs/upload", { form });
      r.notes.forEach((n: string) => toast(n, true));
      setFiles([]);
      setResult("");
      if (r.saved.length && info.can_score) {
        const p = await api<Pending>("/cvs/pending");
        await scoreAll(p.pending.length);
      } else if (r.saved.length) {
        toast(`Saved ${r.saved.length} CV(s). Add the API key to score them.`);
        load();
      }
    } catch (e: any) { toast(e.message, true); }
  };

  const roleOpts = ["", ...Object.keys(info.role_names)];
  const roleLabels = { "": "Not sure: check every role", ...info.role_names };

  return (
    <div className="space-y-5">
      <PageHeader icon={<UploadIcon className="h-6 w-6" />} title="Add CVs" tone="accent">Drag and drop CVs: PDF or Word, as many as you like. Names, contact details and colleges are removed before the AI reads anything.</PageHeader>
      {result && <Callout tone="good">{result}</Callout>}

      {can(me, "upload") && (
        <div className="card space-y-4 p-5">
          <div>
            <div className="label">Which role are these CVs for?</div>
            <Segmented value={role} options={roleOpts} labels={roleLabels} onChange={setRole} />
          </div>
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
            onClick={() => input.current?.click()}
            className={`group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-4 py-12 text-center transition ${drag ? "scale-[1.01] border-accent bg-accent/10" : "border-line hover:border-accent/50 hover:bg-accent/5"}`}>
            <span className={`grid h-14 w-14 place-items-center rounded-2xl bg-accent/10 text-accent transition ${drag ? "scale-110" : "group-hover:-translate-y-0.5"}`}><Upload className="h-7 w-7" /></span>
            <div className="font-display text-base"><b>Drop CVs here</b> or click to choose</div>
            <div className="text-xs text-muted">PDF, Word or text · up to 10 MB each</div>
            <input ref={input} type="file" multiple hidden accept={EXT.join(",")} onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
          </div>
          {files.length > 0 && (
            <ul className="space-y-1 text-sm">
              {files.map((f) => (
                <li key={f.name + f.size} className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-muted" /> {f.name} <span className="text-xs text-muted">{Math.ceil(f.size / 1024)} KB</span>
                  <button className="btn btn-ghost ml-auto px-1.5 py-0.5" onClick={() => setFiles(files.filter((x) => x !== f))} aria-label="Remove"><X className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ul>
          )}
          {progress ? (
            <div className="space-y-1">
              <div className="h-2 overflow-hidden rounded-full bg-sunken"><div className="h-full bg-accent transition-all" style={{ width: `${(100 * progress.done) / Math.max(progress.total, 1)}%` }} /></div>
              <p className="text-xs text-muted">Scored {progress.done} of {progress.total}… you can keep this page open.</p>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn btn-primary" disabled={!files.length} onClick={save}><Play className="h-4 w-4" /> {info.can_score ? "Save and score" : "Save CVs"}</button>
              {info.pending.length > 0 && !files.length && (
                <button className="btn" disabled={!info.can_score} onClick={() => scoreAll(info.pending.length)}><RefreshCw className="h-4 w-4" /> Score {info.pending.length} waiting CV(s)</button>
              )}
            </div>
          )}
          {info.standin && (
            <Callout tone="info" icon={<FlaskConical className="h-4 w-4 text-info" />}>
              Demo: with no API key, CVs are scored by a simple keyword stand-in, not the AI.{" "}
              <a className="font-medium underline" href="/api/demo/samples.zip">Download 6 sample CVs</a> to try it.
            </Callout>
          )}
          {!info.can_score && !info.standin && (
            <Callout tone="warn" icon={<KeyRound className="h-4 w-4 text-warn" />}>
              {info.score_block ?? "To score CVs, add an AI key (GEMINI_API_KEY or ANTHROPIC_API_KEY) to the environment."} You can still save CVs now.
            </Callout>
          )}
          {info.pending.length > 0 && <p className="text-xs text-muted">{info.pending.length} CV(s) saved but not scored yet: {info.pending.slice(0, 6).join(", ")}{info.pending.length > 6 && " …"}</p>}
        </div>
      )}

      <div>
        <h2 className="h2 mb-2">Other ways CVs arrive</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="card space-y-2 p-4">
            <div className="flex items-center gap-2 font-medium"><Globe className="h-4 w-4" /> Careers form</div>
            <p className="muted">A public page where candidates apply, with consent and an optional WhatsApp opt-in.</p>
            <a className="block truncate rounded bg-sunken px-2 py-1 font-mono text-xs" href="/apply" target="_blank">{info.careers_url}</a>
          </div>
          <div className="card space-y-2 p-4">
            <div className="flex items-center gap-2 font-medium"><Mail className="h-4 w-4" /> Hiring inbox</div>
            <p className="muted">{info.inbox ? "Checking the hiring mailbox for CV attachments." : "Forward applications (including from Naukri or LinkedIn) to a hiring mailbox; the scheduled job picks up the attachments."}</p>
            {!info.inbox && <p className="text-xs text-muted">Set HIRING_IMAP_HOST, HIRING_IMAP_USER and HIRING_IMAP_PASSWORD.</p>}
          </div>
          <div className="card space-y-2 p-4">
            <div className="flex items-center gap-2 font-medium"><Download className="h-4 w-4" /> Scheduled scoring</div>
            <p className="muted">Anything waiting is also scored automatically by the scheduled job, a few CVs at a time.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
