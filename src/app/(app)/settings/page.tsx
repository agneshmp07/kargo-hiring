"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Settings2, Check, Minus, Lock, LockOpen, Download, Trash2, Send, Plus, Calculator, RotateCcw, FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/labels";
import { Badge, Callout, PageHeader, Spinner, Tabs, useToast } from "@/components/ui";
import { useMe } from "@/components/AppShell";

type User = { username: string; display_name: string; role: string; email: string; active: number };
type Params = any;
type Data = {
  settings: Record<string, any>; users: User[]; role_labels: Record<string, string>; params: Params;
  history: { version: number; note: string; created_by: string; created_at: string; active: number }[];
  templates: Record<string, Record<string, { subject: string; body: string }>>; placeholders: string[];
  layer_a_points: Record<string, number>;
  integrations: { label: string; var: string; set: boolean }[];
  vault: { encrypted: boolean; location: string };
  mode: { demo: boolean; dry_run: boolean; storage: string; database: string };
  privacy_preview: string;
};
type TabId = "team" | "jobs" | "mail" | "privacy" | "int";

export default function SettingsPage() {
  const me = useMe();
  const toast = useToast();
  const [d, setD] = useState<Data | null>(null);
  const [tab, setTab] = useState<TabId>("team");
  const load = useCallback(() => api<Data>("/settings").then(setD).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { load(); }, [load]);
  if (!me.perms.includes("admin")) return <Callout tone="bad">Only an admin can change settings.</Callout>;
  if (!d) return <Spinner />;

  const save = async (patch: Record<string, unknown>, msg = "Saved.") => {
    try { await api("/settings", { body: patch }); toast(msg); load(); } catch (e: any) { toast(e.message, true); }
  };

  return (
    <div className="space-y-5">
      <PageHeader icon={<Settings2 className="h-6 w-6" />} title="Settings" tone="neutral">Team, jobs and scoring, emails and automation, privacy and integrations.</PageHeader>
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "team", label: "Team" }, { id: "jobs", label: "Jobs & scoring" }, { id: "mail", label: "Emails & automation" },
        { id: "privacy", label: "Privacy & data" }, { id: "int", label: "Integrations" },
      ]} />
      {tab === "team" && <Team d={d} save={save} reload={load} />}
      {tab === "jobs" && <Jobs d={d} reload={load} />}
      {tab === "mail" && <Mail d={d} save={save} />}
      {tab === "privacy" && <Privacy d={d} save={save} reload={load} />}
      {tab === "int" && <Integrations d={d} />}
    </div>
  );
}

/* ---------------------------------------------------------------- team */

function Team({ d, save, reload }: { d: Data; save: (p: Record<string, unknown>, m?: string) => void; reload: () => void }) {
  const toast = useToast();
  const [roles, setRoles] = useState<string[]>(d.settings.decision_roles);
  const [form, setForm] = useState({ name: "", username: "", email: "", role: "hiring_manager", password: "" });
  const [edit, setEdit] = useState({ username: d.users[0]?.username ?? "", role: "", active: true, password: "" });

  const add = async () => {
    try { await api("/users", { body: form }); toast(`Added ${form.username}.`); setForm({ ...form, name: "", username: "", email: "", password: "" }); reload(); }
    catch (e: any) { toast(e.message, true); }
  };
  const change = async () => {
    try {
      await api(`/users/${edit.username}`, { method: "PATCH", body: { role: edit.role || undefined, active: edit.active, password: edit.password || undefined } });
      toast("Saved."); reload();
    } catch (e: any) { toast(e.message, true); }
  };

  return (
    <div className="space-y-5">
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-left text-muted">{["Name", "Username", "Role", "Email", "Access"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody>{d.users.map((u) => (
            <tr key={u.username} className="border-b border-line last:border-0">
              <td className="px-3 py-2 font-medium">{u.display_name}</td><td className="px-3 py-2">{u.username}</td>
              <td className="px-3 py-2">{d.role_labels[u.role]}</td><td className="px-3 py-2">{u.email || "-"}</td>
              <td className="px-3 py-2"><Badge tone={u.active ? "good" : "neutral"}>{u.active ? "active" : "deactivated"}</Badge></td>
            </tr>
          ))}</tbody>
        </table>
      </div>

      <div className="card space-y-2 p-4">
        <div className="font-semibold">Who may invite or pass candidates</div>
        <div className="flex flex-wrap gap-2">
          {Object.keys(d.role_labels).map((r) => (
            <button key={r} onClick={() => setRoles(roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r])}
              className={`rounded-full px-3 py-1 text-sm ring-1 ring-inset ${roles.includes(r) ? "bg-accent/10 text-accent ring-accent/40" : "text-muted ring-line"}`}>
              {d.role_labels[r].split(" (")[0]}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted">The build brief says the founder decides. Adding other roles is your call; every decision records who made it.</p>
        <button className="btn" disabled={!roles.length} onClick={() => save({ decision_roles: roles })}>Save decision-makers</button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-2 p-4">
          <div className="font-semibold">Add a person</div>
          <input className="input" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="input" placeholder="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input className="input" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {Object.entries(d.role_labels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {!d.mode.demo && <input className="input" type="password" placeholder="Temporary password (10+ characters, with a number)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />}
          <button className="btn btn-primary" disabled={!form.name || !form.username} onClick={add}><Plus className="h-4 w-4" /> Add</button>
        </div>
        <div className="card space-y-2 p-4">
          <div className="font-semibold">Change someone&apos;s access</div>
          <select className="input" value={edit.username} onChange={(e) => setEdit({ ...edit, username: e.target.value })}>
            {d.users.map((u) => <option key={u.username} value={u.username}>{u.display_name}</option>)}
          </select>
          <select className="input" value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value })}>
            <option value="">Keep the current role</option>
            {Object.entries(d.role_labels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} /> Active</label>
          {!d.mode.demo && <input className="input" type="password" placeholder="New password (optional)" value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} />}
          <button className="btn" onClick={change}>Save changes</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- jobs & scoring */

function Jobs({ d, reload }: { d: Data; reload: () => void }) {
  const toast = useToast();
  const original = useMemo(() => { const { _version, ...p } = d.params; return p; }, [d.params]);
  const [draft, setDraft] = useState<Params>(() => JSON.parse(JSON.stringify(original)));
  const [errors, setErrors] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [newRole, setNewRole] = useState({ code: "", name: "", lo: 2, hi: 5, criteria: "", jd: "" });
  const changed = JSON.stringify(draft) !== JSON.stringify(original);

  useEffect(() => {
    const t = setTimeout(() => api("/versions/validate", { body: { params: draft } }).then((r) => setErrors(r.errors)).catch(() => {}), 300);
    return () => clearTimeout(t);
  }, [draft]);

  const upd = (fn: (p: Params) => void) => setDraft((p: Params) => { const c = JSON.parse(JSON.stringify(p)); fn(c); return c; });
  const publish = async () => {
    try { const r = await api("/versions", { body: { params: draft, note } }); toast(`Published v${r.version}. New CVs use it now.`); setNote(""); reload(); }
    catch (e: any) { toast(e.message, true); }
  };
  const recalc = async () => {
    try { const r = await api("/recalculate", { method: "POST" }); toast(`Re-banded ${r.recalculated} CV(s).${r.skipped_roles.length ? ` ${r.skipped_roles.length} role score(s) skipped: re-upload those CVs to score a new role.` : ""}`); }
    catch (e: any) { toast(e.message, true); }
  };
  const activate = async (v: number) => {
    try { await api(`/versions/${v}/activate`, { method: "POST" }); toast(`v${v} is active.`); reload(); } catch (e: any) { toast(e.message, true); }
  };
  const addRole = () => {
    const code = newRole.code.trim().toUpperCase();
    const weights: Record<string, number> = {}, defs: Record<string, string> = {};
    newRole.criteria.split("\n").forEach((line) => {
      const [k, w, def] = line.split("|").map((s) => s.trim());
      if (k && w && def && /^\d+$/.test(w)) { const key = k.toLowerCase().replace(/\s+/g, "_"); weights[key] = Number(w); defs[key] = def; }
    });
    upd((p) => { p.layer_b[code] = { weights, gate_years_pm: [newRole.lo, newRole.hi] }; p._roles[code] = { name: newRole.name, jd_text: newRole.jd, definitions: defs }; });
    setNewRole({ code: "", name: "", lo: 2, hi: 5, criteria: "", jd: "" });
  };

  return (
    <div className="space-y-5">
      <p className="muted">Active settings version: <b>v{d.params._version}</b>. Every score records the version it used. Changing weights never touches past decisions; use <i>Recalculate</i> to re-band existing CVs.</p>

      <section className="space-y-3">
        <h2 className="h2">Roles</h2>
        {Object.keys(draft.layer_b).map((code) => {
          const lb = draft.layer_b[code];
          const meta = draft._roles[code] ?? { name: code, jd_text: "", definitions: {} };
          const total = Object.values(lb.weights as Record<string, number>).reduce((a, b) => a + b, 0);
          return (
            <details key={code} className="card p-4">
              <summary className="cursor-pointer font-medium">{meta.name} ({code}) <span className="text-sm text-muted">· PM years {lb.gate_years_pm[0]}–{lb.gate_years_pm[1]}</span></summary>
              <div className="mt-3 space-y-3">
                <div className="grid gap-2 md:grid-cols-3">
                  <label className="text-sm">Role name<input className="input mt-1" value={meta.name} onChange={(e) => upd((p) => { p._roles[code].name = e.target.value; })} /></label>
                  <label className="text-sm">PM years from<input type="number" className="input mt-1" value={lb.gate_years_pm[0]} onChange={(e) => upd((p) => { p.layer_b[code].gate_years_pm[0] = Number(e.target.value); })} /></label>
                  <label className="text-sm">PM years to<input type="number" className="input mt-1" value={lb.gate_years_pm[1]} onChange={(e) => upd((p) => { p.layer_b[code].gate_years_pm[1] = Number(e.target.value); })} /></label>
                </div>
                <div className="text-sm font-semibold">Role-specific criteria <span className={total === 100 ? "text-good" : "text-bad"}>(weights total {total}, must be 100)</span></div>
                {Object.keys(lb.weights).map((k) => (
                  <div key={k} className="grid grid-cols-[90px_1fr] gap-2">
                    <input type="number" className="input" value={lb.weights[k]} onChange={(e) => upd((p) => { p.layer_b[code].weights[k] = Number(e.target.value); })} aria-label={`${k} weight`} />
                    <input className="input" value={meta.definitions[k] ?? ""} title={k} onChange={(e) => upd((p) => { p._roles[code].definitions[k] = e.target.value; })} aria-label={`${k} definition`} />
                  </div>
                ))}
                <label className="block text-sm">Job description<textarea className="input mt-1" rows={6} value={meta.jd_text} onChange={(e) => upd((p) => { p._roles[code].jd_text = e.target.value; })} /></label>
              </div>
            </details>
          );
        })}
        <details className="card p-4">
          <summary className="cursor-pointer font-medium">Add a new role</summary>
          <div className="mt-3 space-y-2">
            <div className="grid gap-2 md:grid-cols-4">
              <input className="input" placeholder="Code, e.g. OPSM" value={newRole.code} onChange={(e) => setNewRole({ ...newRole, code: e.target.value })} />
              <input className="input md:col-span-3" placeholder="Role name, e.g. Operations Manager" value={newRole.name} onChange={(e) => setNewRole({ ...newRole, name: e.target.value })} />
              <label className="text-sm">PM years from<input type="number" className="input mt-1" value={newRole.lo} onChange={(e) => setNewRole({ ...newRole, lo: Number(e.target.value) })} /></label>
              <label className="text-sm">to<input type="number" className="input mt-1" value={newRole.hi} onChange={(e) => setNewRole({ ...newRole, hi: Number(e.target.value) })} /></label>
            </div>
            <textarea className="input font-mono text-xs" rows={4} value={newRole.criteria} onChange={(e) => setNewRole({ ...newRole, criteria: e.target.value })}
              placeholder={"key | weight | definition   (one per line, weights add up to 100)\nops_leadership | 40 | led a team of 10+ in warehouse or port operations"} />
            <textarea className="input" rows={3} placeholder="Job description" value={newRole.jd} onChange={(e) => setNewRole({ ...newRole, jd: e.target.value })} />
            <button className="btn" disabled={!newRole.code || !newRole.name || !newRole.criteria} onClick={addRole}><Plus className="h-4 w-4" /> Add to draft</button>
          </div>
        </details>
      </section>

      <section className="space-y-2">
        <h2 className="h2">Pattern weights and thresholds</h2>
        <p className="text-xs text-muted">Layer A points are fixed from the build brief (derived from past hires): {Object.entries(d.layer_a_points).map(([k, v]) => `${k} ${v}`).join(", ")}.</p>
        <div className="grid gap-3 md:grid-cols-4">
          <label className="text-sm">Kargo pattern weight (Layer A): <b>{draft.blend.layer_a_pattern}</b>
            <input type="range" min={0} max={1} step={0.05} className="w-full accent-[rgb(var(--accent))]" value={draft.blend.layer_a_pattern}
              onChange={(e) => upd((p) => { const a = Number(e.target.value); p.blend = { layer_a_pattern: +a.toFixed(2), layer_b_role: +(1 - a).toFixed(2) }; })} /></label>
          <label className="text-sm">Strong from<input type="number" className="input mt-1" value={draft.bands.strong} onChange={(e) => upd((p) => { p.bands.strong = Number(e.target.value); })} /></label>
          <label className="text-sm">Borderline from<input type="number" className="input mt-1" value={draft.bands.borderline} onChange={(e) => upd((p) => { p.bands.borderline = Number(e.target.value); })} /></label>
          <label className="text-sm">Role rescue when role fit ≥<input type="number" className="input mt-1" value={draft.rules.role_rescue_B} onChange={(e) => upd((p) => { p.rules.role_rescue_B = Number(e.target.value); })} /></label>
        </div>
      </section>

      {errors.length > 0 && <div className="space-y-1">{errors.map((e) => <Callout key={e} tone="bad">{e}</Callout>)}</div>}
      <div className="card flex flex-wrap items-center gap-2 p-4">
        <input className="input min-w-[240px] flex-1" placeholder="What changed and why (required)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn btn-primary" disabled={!changed || errors.length > 0 || !note.trim()} onClick={publish}>Publish as a new version</button>
        <button className="btn" onClick={() => setDraft(JSON.parse(JSON.stringify(original)))} disabled={!changed}><RotateCcw className="h-4 w-4" /> Discard changes</button>
        <button className="btn" onClick={recalc} title="No AI calls: re-bands from the stored evidence codes."><Calculator className="h-4 w-4" /> Recalculate existing CVs</button>
      </div>
      <p className="text-xs text-muted">Before trusting new weights, re-run the blind check on the Calibrate page.</p>

      <section className="space-y-2">
        <h2 className="h2">Versions</h2>
        <div className="card divide-y divide-line text-sm">
          {d.history.map((h) => (
            <div key={h.version} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <b>v{h.version}</b> <span className="text-muted">{h.note}</span> <span className="text-xs text-muted">by {h.created_by} · {fmtTime(h.created_at)}</span>
              {h.active ? <Badge tone="good">active</Badge> : <button className="btn ml-auto py-1" onClick={() => activate(h.version)}>Make active</button>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- emails & automation */

function Mail({ d, save }: { d: Data; save: (p: Record<string, unknown>, m?: string) => void }) {
  const toast = useToast();
  const s = d.settings;
  const [a, setA] = useState<Record<string, any>>({ ...s, digest_recipients: (s.digest_recipients ?? []).join(", ") });
  const kinds = Object.keys(d.templates);
  const [kind, setKind] = useState(kinds[0]);
  const roleOpts = ["*", ...Object.keys(d.params.layer_b)];
  const [role, setRole] = useState("*");
  const t = d.templates[kind][role] ?? d.templates[kind]["*"];
  const [subject, setSubject] = useState(t.subject);
  const [body, setBody] = useState(t.body);
  const [check, setCheck] = useState<{ errors: string[]; preview: { subject: string; body: string } | null }>({ errors: [], preview: null });

  useEffect(() => { const t2 = d.templates[kind][role] ?? d.templates[kind]["*"]; setSubject(t2.subject); setBody(t2.body); }, [kind, role, d.templates]);
  useEffect(() => {
    const id = setTimeout(() => api("/templates/check", { body: { subject, body, role } }).then(setCheck).catch(() => {}), 300);
    return () => clearTimeout(id);
  }, [subject, body, role]);

  const saveAuto = () => save({
    undo_minutes: Number(a.undo_minutes), followup_days: Number(a.followup_days), interview_reminder_hours: Number(a.interview_reminder_hours),
    digest_enabled: a.digest_enabled, digest_hour: Number(a.digest_hour), slack_enabled: a.slack_enabled, hold_reminder_email: a.hold_reminder_email,
    whatsapp_enabled: a.whatsapp_enabled, ack_enabled: a.ack_enabled,
    digest_recipients: String(a.digest_recipients).split(",").map((x: string) => x.trim()).filter(Boolean),
  }, "Automation settings saved.");
  const saveTpl = async () => { try { await api("/templates", { body: { kind, role, subject, body } }); toast("Template saved."); } catch (e: any) { toast(e.message, true); } };
  const resetTpl = async () => { try { await api("/templates/reset", { body: { kind, role } }); toast("Reset to default."); location.reload(); } catch (e: any) { toast(e.message, true); } };
  const digest = async () => { try { await api("/digest-now", { method: "POST" }); toast(d.mode.dry_run ? "Digest created (practice mode: see History > Messages)." : "Digest sent."); } catch (e: any) { toast(e.message, true); } };

  const num = (k: string, label: string, max: number) => (
    <label className="text-sm">{label}<input type="number" min={0} max={max} className="input mt-1" value={a[k]} onChange={(e) => setA({ ...a, [k]: e.target.value })} /></label>
  );
  const toggle = (k: string, label: string) => (
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!a[k]} onChange={(e) => setA({ ...a, [k]: e.target.checked })} /> {label}</label>
  );

  return (
    <div className="space-y-6">
      <ResendPanel />
      <section className="card space-y-3 p-4">
        <h2 className="h2">Automation</h2>
        <div className="grid gap-3 md:grid-cols-3">
          {num("undo_minutes", "Undo window before a decision email goes out (minutes)", 120)}
          {num("followup_days", "Remind invited candidates who haven't booked after (days, 0 = off)", 30)}
          {num("interview_reminder_hours", "Interview reminder to the candidate, hours before (0 = off)", 72)}
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {num("digest_hour", "Daily digest time (IST hour)", 23)}
          <label className="text-sm md:col-span-2">Digest recipients (comma separated; empty = founders and hiring managers)
            <input className="input mt-1" value={a.digest_recipients} onChange={(e) => setA({ ...a, digest_recipients: e.target.value })} /></label>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {toggle("digest_enabled", "Daily digest to the team")}
          {toggle("slack_enabled", "Also post the digest to Slack (needs SLACK_WEBHOOK_URL)")}
          {toggle("hold_reminder_email", "Email decision-makers about Holds older than 7 days")}
          {toggle("whatsapp_enabled", "WhatsApp invites and reminders to candidates who opted in (needs Twilio)")}
        </div>
        <div className="rounded-lg bg-warn/10 p-3 ring-1 ring-inset ring-warn/25">
          {toggle("ack_enabled", "Send an automatic 'we received your application' email")}
          <p className="mt-1 text-xs text-muted">This email reaches the candidate before anyone decides, which the build brief&apos;s overriding rule does not allow. Only switch it on if you&apos;ve chosen to change that rule.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={saveAuto}>Save</button>
          <button className="btn" onClick={digest}><Send className="h-4 w-4" /> Send a digest now</button>
        </div>
      </section>

      <section className="card space-y-3 p-4">
        <h2 className="h2">Email templates</h2>
        <p className="text-xs text-muted">Placeholders: {d.placeholders.map((p) => `{${p}}`).join(", ")}. Candidate emails can&apos;t mention scores, reasons or offers; those are refused on save.</p>
        <div className="flex flex-wrap gap-2">
          <select className="input w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>{kinds.map((k) => <option key={k} value={k}>{k.replace(/_/g, " ")}</option>)}</select>
          <select className="input w-auto" value={role} onChange={(e) => setRole(e.target.value)}>{roleOpts.map((r) => <option key={r} value={r}>{r === "*" ? "All roles" : r}</option>)}</select>
        </div>
        <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
        <textarea className="input font-mono text-xs" rows={12} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Body" />
        {check.errors.map((e) => <Callout key={e} tone="bad">{e}</Callout>)}
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={check.errors.length > 0} onClick={saveTpl}>Save template</button>
          <button className="btn" onClick={resetTpl}><RotateCcw className="h-4 w-4" /> Reset to default</button>
        </div>
        {check.preview && (
          <details className="rounded-lg bg-sunken p-3" open>
            <summary className="cursor-pointer text-sm font-medium">Preview</summary>
            <div className="mt-2 text-sm font-semibold">{check.preview.subject}</div>
            <pre className="mt-1 whitespace-pre-wrap font-sans text-sm">{check.preview.body}</pre>
          </details>
        )}
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- resend */

type ResendStatus = {
  ok: boolean | null; state: string; domain: string | null; message: string; region?: string;
  from: string; reply_to: string | null; dry_run: boolean; demo: boolean; test_recipient: boolean;
  webhook_secret: boolean; webhook_url: string;
};

function ResendPanel() {
  const me = useMe();
  const toast = useToast();
  const [st, setSt] = useState<ResendStatus | null>(null);
  const [to, setTo] = useState(me.user.email ?? "");
  const [busy, setBusy] = useState(false);
  const check = useCallback(() => api<ResendStatus>("/resend/status").then(setSt).catch((e) => toast(e.message, true)), [toast]);
  useEffect(() => { check(); }, [check]);

  const test = async () => {
    setBusy(true);
    try { const r = await api("/resend/test", { body: { to } }); toast(`Test email sent to ${r.to}. Check the inbox (and spam).`); }
    catch (e: any) { toast(e.message, true); }
    finally { setBusy(false); }
  };

  if (!st) return <section className="card p-4"><Spinner label="Checking Resend…" /></section>;
  const tone = st.ok ? "good" : st.ok === null ? "warn" : "bad";
  return (
    <section className="card space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="h2">Sending with Resend</h2>
        <Badge tone={tone}>{st.state === "no_key" ? "not connected" : st.ok ? "ready" : st.ok === null ? "check" : "needs setup"}</Badge>
        <button className="btn ml-auto py-1" onClick={check}><RotateCcw className="h-3.5 w-3.5" /> Check again</button>
      </div>
      <Callout tone={tone}>{st.message}</Callout>
      <dl className="grid gap-x-6 gap-y-1 text-sm md:grid-cols-2">
        <div><dt className="inline text-muted">From: </dt><dd className="inline">{st.from}</dd></div>
        <div><dt className="inline text-muted">Replies go to: </dt><dd className="inline">{st.reply_to ?? "the From address (set REPLY_TO to change)"}</dd></div>
        <div><dt className="inline text-muted">Mode: </dt><dd className="inline">{st.demo ? "demo, never sends" : st.dry_run ? "practice (DRY_RUN=true): candidate emails are saved, not sent" : st.test_recipient ? "live, but every email goes to TEST_RECIPIENT" : "live: candidate emails are sent"}</dd></div>
        <div><dt className="inline text-muted">Delivery tracking: </dt><dd className="inline">{st.webhook_secret ? "on" : "off (set RESEND_WEBHOOK_SECRET)"}</dd></div>
      </dl>
      {!st.webhook_secret && (
        <p className="text-xs text-muted">To track delivered / bounced / spam: in Resend → Webhooks, add <code className="rounded bg-sunken px-1">{st.webhook_url}</code> with the email events, then copy its signing secret into RESEND_WEBHOOK_SECRET.</p>
      )}
      {!st.demo && st.state !== "no_key" && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <input className="input w-72" type="email" placeholder="your@email.com" value={to} onChange={(e) => setTo(e.target.value)} />
          <button className="btn" disabled={busy || !to.includes("@")} onClick={test}><Send className="h-4 w-4" /> Send a test email to me</button>
          <span className="text-xs text-muted">Sends one real email to this address only, never to a candidate.</span>
        </div>
      )}
    </section>
  );
}

/* ---------------------------------------------------------------- privacy */

function Privacy({ d, save, reload }: { d: Data; save: (p: Record<string, unknown>, m?: string) => void; reload: () => void }) {
  const toast = useToast();
  const [p, setP] = useState({ retention_days: d.settings.retention_days, privacy_contact: d.settings.privacy_contact, privacy_notice: d.settings.privacy_notice });
  const [exp, setExp] = useState("");
  const [er, setEr] = useState("");
  const [sure, setSure] = useState(false);
  const erase = async () => {
    try { await api("/privacy/erase", { body: { candidate_id: er } }); toast(`Erased ${er}. The anonymous decision record is kept for the audit trail.`); setEr(""); setSure(false); reload(); }
    catch (e: any) { toast(e.message, true); }
  };
  const reset = async () => {
    try { await api("/demo/reset", { method: "POST" }); toast("Demo reset."); location.href = "/shortlist"; } catch (e: any) { toast(e.message, true); }
  };

  return (
    <div className="space-y-5">
      <section className="card space-y-3 p-4">
        <h2 className="h2">Retention and notice</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">Delete application data this many days after a final decision (0 = never)
            <input type="number" className="input mt-1" value={p.retention_days} onChange={(e) => setP({ ...p, retention_days: Number(e.target.value) })} /></label>
          <label className="text-sm">Privacy contact email<input className="input mt-1" value={p.privacy_contact} onChange={(e) => setP({ ...p, privacy_contact: e.target.value })} /></label>
        </div>
        <label className="block text-sm">Privacy notice (shown on the careers form)<textarea className="input mt-1" rows={6} value={p.privacy_notice} onChange={(e) => setP({ ...p, privacy_notice: e.target.value })} /></label>
        <button className="btn btn-primary" onClick={() => save(p)}>Save</button>
        <p className="text-xs text-muted">Preview: {d.privacy_preview.slice(0, 280)}…</p>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card space-y-2 p-4">
          <div className="font-semibold">Export someone&apos;s data</div>
          <input className="input" placeholder="Candidate ID, e.g. KG-0001" value={exp} onChange={(e) => setExp(e.target.value.toUpperCase())} />
          <a className={`btn ${exp ? "" : "pointer-events-none opacity-50"}`} href={`/api/privacy/export/${exp}`}><Download className="h-4 w-4" /> Download</a>
        </section>
        <section className="card space-y-2 p-4">
          <div className="font-semibold">Erase someone&apos;s data</div>
          <input className="input" placeholder="Candidate ID, e.g. KG-0001" value={er} onChange={(e) => setEr(e.target.value.toUpperCase())} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} /> I understand this can&apos;t be undone</label>
          <button className="btn btn-primary" disabled={!er || !sure} onClick={erase}><Trash2 className="h-4 w-4" /> Erase</button>
        </section>
      </div>

      <section className="card space-y-3 p-4">
        <h2 className="h2">Backups and encryption</h2>
        <a className="btn" href="/api/backup.zip"><Download className="h-4 w-4" /> Download a backup</a>
        <p className="text-xs text-muted">Neon also keeps point-in-time history of the database. Store downloaded backups somewhere safe: they contain candidate data.</p>
        {d.vault.encrypted
          ? <Callout tone="good" icon={<Lock className="h-4 w-4" />}>Names and emails are encrypted ({d.vault.location}).</Callout>
          : <Callout tone="warn" icon={<LockOpen className="h-4 w-4" />}>Names and emails are not encrypted ({d.vault.location}). Set VAULT_KEY (<code>python -m shortlister keygen</code>) in the environment.</Callout>}
      </section>

      {d.mode.demo && (
        <section className="card space-y-2 p-4">
          <div className="flex items-center gap-2 font-semibold"><FlaskConical className="h-4 w-4" /> Demo</div>
          <p className="muted">Start the demo over with fresh fictional candidates.</p>
          <button className="btn" onClick={reset}><RotateCcw className="h-4 w-4" /> Reset the demo</button>
        </section>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- integrations */

function Integrations({ d }: { d: Data }) {
  return (
    <div className="space-y-3">
      <p className="muted">Only whether each is set is shown; values are never displayed. Set them in Vercel → Project → Settings → Environment Variables.</p>
      <div className="card divide-y divide-line">
        {d.integrations.map((i) => (
          <div key={i.var} className="flex items-center gap-3 px-4 py-2 text-sm">
            <Badge tone={i.set ? "good" : "neutral"} icon={i.set ? <Check className="h-3.5 w-3.5" /> : <Minus className="h-3.5 w-3.5" />}>{i.set ? "set" : "not set"}</Badge>
            <span className="font-medium">{i.label}</span>
            <code className="ml-auto text-xs text-muted">{i.var}</code>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted">Email mode: {d.mode.demo ? "demo (never sends)" : d.mode.dry_run ? "practice (DRY_RUN)" : "live"} · storage: {d.mode.storage} · database: {d.mode.database}</p>
    </div>
  );
}
