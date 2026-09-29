"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FlaskConical, Building2, ArrowRight, ArrowLeft, Terminal } from "lucide-react";
import { api } from "@/lib/api";
import { Callout, Spinner } from "@/components/ui";
import { Avatar, RouteArt, Wordmark } from "@/components/brand";

function BrandPanel() {
  return (
    <aside className="relative hidden overflow-hidden bg-navy text-white lg:flex lg:flex-col lg:justify-between lg:p-12">
      <div className="absolute inset-0 bg-[radial-gradient(700px_400px_at_80%_10%,rgb(var(--accent)/.35),transparent_60%),radial-gradient(600px_400px_at_0%_100%,rgb(var(--accent2)/.25),transparent_60%)]" />
      <RouteArt className="absolute inset-0 h-full w-full opacity-80 [mask-image:linear-gradient(90deg,transparent_0%,transparent_30%,black_70%)]" />
      {/* keep the headline readable over the routes */}
      <div className="absolute inset-0 bg-[linear-gradient(90deg,rgb(var(--navy))_0%,rgb(var(--navy)/.88)_38%,rgb(var(--navy)/.2)_78%,transparent_100%)]" />
      <div className="relative"><span className="[&_span]:text-white [&_.text-muted]:text-white/60"><Wordmark /></span></div>
      <div className="relative max-w-md animate-rise">
        <h1 className="font-display text-4xl font-bold leading-[1.1] tracking-tight xl:text-5xl">
          Hire people who&apos;ve been <span className="text-accent">on the floor</span>.
        </h1>
        <p className="mt-4 text-base text-white/70">
          Kargo reads every CV for the pattern your best hires share: hands-on ops, building unasked, owning the call.
          The system recommends. <b className="text-white">You decide.</b>
        </p>
        <div className="mt-6 flex flex-wrap gap-2 text-xs">
          {["Names hidden until you invite", "Evidence quoted from the CV", "Nothing sent until you click"].map((t) => (
            <span key={t} className="rounded-full bg-white/10 px-3 py-1.5 ring-1 ring-inset ring-white/15 backdrop-blur">{t}</span>
          ))}
        </div>
      </div>
      <p className="relative text-xs text-white/40">Built for freight forwarders and 3PLs · Mumbai</p>
    </aside>
  );
}

type State = {
  modes: ("demo" | "real")[]; mode: "demo" | "real" | null; demo: boolean; has_users: boolean | null;
  demo_users: { username: string; display_name: string; role: string; role_label: string }[];
  setup: "open" | "code" | "cli" | null;
};

export default function Login() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  const load = useCallback(() => api<State>("/auth/state").then(setState).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  const choose = async (mode: "demo" | "real" | null) => {
    setBusy(true);
    setError("");
    try { await api("/auth/mode", { body: { mode } }); await load(); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  const go = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); router.replace("/shortlist"); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  };

  const submit = (e: React.FormEvent<HTMLFormElement>, path: string) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    if (path === "/auth/setup" && f.password !== f.password2) return setError("The passwords don't match.");
    go(() => api(path, { body: f }));
  };

  const multi = (state?.modes.length ?? 0) > 1;

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.15fr_1fr]">
      <BrandPanel />
      <div className="flex flex-col justify-center px-5 py-10 sm:px-10">
      <div className="mx-auto w-full max-w-md">
      <div className="mb-8 lg:hidden">
        <Wordmark />
        <p className="mt-3 font-display text-2xl font-bold leading-tight">Hire people who&apos;ve been <span className="text-accent">on the floor</span>.</p>
      </div>
      <h2 className="mb-1 hidden font-display text-2xl font-bold lg:block">Welcome</h2>
      {!state && !error && <Spinner />}
      {error && <div className="mb-4"><Callout tone="bad">{error}</Callout></div>}

      {/* ---------------- opening screen: pick a product ---------------- */}
      {state && multi && !state.mode && (
        <div className="space-y-3">
          <p className="muted mb-2">How would you like to use Kargo hiring?</p>
          <button disabled={busy} onClick={() => choose("real")}
            className="card group flex w-full animate-rise items-start gap-4 p-5 text-left transition hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-lift">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent"><Building2 className="h-5 w-5" /></span>
            <div className="flex-1">
              <div className="font-display text-base font-bold">Kargo hiring</div>
              <div className="muted mt-0.5">The real product. Your own candidates, your team&apos;s logins, and real decisions. Sign in with your account.</div>
            </div>
            <ArrowRight className="mt-1 h-5 w-5 shrink-0 text-muted transition group-hover:translate-x-0.5 group-hover:text-fg" />
          </button>
          <button disabled={busy} onClick={() => choose("demo")}
            className="card group flex w-full animate-rise items-start gap-4 p-5 text-left transition [animation-delay:80ms] hover:-translate-y-0.5 hover:border-info/50 hover:shadow-lift">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-info/10 text-info"><FlaskConical className="h-5 w-5" /></span>
            <div className="flex-1">
              <div className="font-display text-base font-bold">Try the demo</div>
              <div className="muted mt-0.5">Fictional candidates and teammates to explore every feature. Nothing is ever emailed, and it never touches real data.</div>
            </div>
            <ArrowRight className="mt-1 h-5 w-5 shrink-0 text-muted transition group-hover:translate-x-0.5 group-hover:text-fg" />
          </button>
        </div>
      )}

      {/* ---------------- demo: pick a person ---------------- */}
      {state?.mode === "demo" && (
        <div className="space-y-3">
          <Callout tone="info" icon={<FlaskConical className="h-4 w-4 text-info" />}>
            <b>Demo.</b> Fictional candidates; nothing is ever sent. Pick someone to see the app as them.
          </Callout>
          {state.demo_users.map((u, i) => (
            <div key={u.username} className="card flex animate-rise items-center justify-between gap-3 px-4 py-3" style={{ animationDelay: `${i * 60}ms` }}>
              <div className="flex items-center gap-3">
                <Avatar id={u.username} name={u.display_name} size={40} />
                <div>
                <div className="font-medium">{u.display_name}</div>
                <div className="muted">{u.role_label}</div>
                </div>
              </div>
              <button disabled={busy} className={`btn ${u.role === "founder" ? "btn-primary" : ""}`}
                onClick={() => go(() => api("/auth/demo-login", { body: { username: u.username } }))}>
                Continue as {u.display_name.split(" ")[0]}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* ---------------- real product: first account ---------------- */}
      {state?.mode === "real" && !state.has_users && state.setup === "cli" && (
        <div className="card space-y-3 p-5">
          <h1 className="h2">Kargo hiring isn&apos;t set up yet</h1>
          <p className="muted">For safety, the first (founder) account is created from the computer that manages this deployment, not from the public website.</p>
          <div className="flex items-start gap-2 rounded-lg bg-sunken p-3 font-mono text-xs">
            <Terminal className="mt-0.5 h-4 w-4 shrink-0" />
            <span>python -m shortlister adduser arjun --name &quot;Arjun Mehta&quot; --role founder --email arjun@kargo.in</span>
          </div>
          <p className="text-xs text-muted">Then come back here and sign in. Other people can be added from Settings → Team.</p>
        </div>
      )}
      {state?.mode === "real" && !state.has_users && (state.setup === "open" || state.setup === "code") && (
        <form className="card space-y-3 p-5" onSubmit={(e) => submit(e, "/auth/setup")}>
          <div>
            <h1 className="h2">Set up the first account</h1>
            <p className="muted">This is the founder account: it decides, and manages the team and settings.</p>
          </div>
          {state.setup === "code" && <div><label className="label">Setup code</label><input className="input" name="setup_code" required autoComplete="off" /><p className="mt-1 text-xs text-muted">The SETUP_CODE set for this deployment.</p></div>}
          <div><label className="label">Your name</label><input className="input" name="name" required /></div>
          <div><label className="label">Username</label><input className="input" name="username" required placeholder="e.g. arjun" /></div>
          <div><label className="label">Email (for the daily digest)</label><input className="input" name="email" type="email" /></div>
          <div><label className="label">Password</label><input className="input" name="password" type="password" required minLength={10} /><p className="mt-1 text-xs text-muted">At least 10 characters, with a number.</p></div>
          <div><label className="label">Repeat password</label><input className="input" name="password2" type="password" required /></div>
          <button disabled={busy} className="btn btn-primary w-full">Create account</button>
        </form>
      )}

      {/* ---------------- real product: sign in ---------------- */}
      {state?.mode === "real" && state.has_users && (
        <form className="card space-y-3 p-5" onSubmit={(e) => submit(e, "/auth/login")}>
          <h1 className="h2">Sign in to Kargo hiring</h1>
          <div><label className="label">Username</label><input className="input" name="username" required autoComplete="username" /></div>
          <div><label className="label">Password</label><input className="input" name="password" type="password" required autoComplete="current-password" /></div>
          <button disabled={busy} className="btn btn-primary w-full">Sign in</button>
        </form>
      )}

      {state && multi && state.mode && (
        <button className="btn btn-ghost mt-4 px-2" disabled={busy} onClick={() => choose(null)}>
          <ArrowLeft className="h-4 w-4" /> {state.mode === "demo" ? "Back: use the real product instead" : "Back: try the demo instead"}
        </button>
      )}
      </div>
      </div>
    </div>
  );
}
