"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import {
  ClipboardCheck, Upload, CalendarDays, Users, SlidersHorizontal, BarChart3, History, Settings, LogOut,
  FlaskConical, Send, Menu, X, ArrowLeftRight,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Me } from "@/lib/types";
import { Spinner } from "./ui";
import { Avatar, Wordmark } from "./brand";

const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx)!;
export const can = (me: Me, perm: string) => me.perms.includes(perm);

const NAV = [
  { section: "Hiring", items: [
    { href: "/shortlist", label: "Shortlist", icon: ClipboardCheck, perm: "view" },
    { href: "/add-cvs", label: "Add CVs", icon: Upload, perm: "upload" },
    { href: "/interviews", label: "Interviews", icon: CalendarDays, perm: "view" },
    { href: "/reviews", label: "Second opinions", icon: Users, perm: "review" },
  ] },
  { section: "Insights", items: [
    { href: "/calibrate", label: "Calibrate", icon: SlidersHorizontal, perm: "calibrate" },
    { href: "/analytics", label: "Analytics", icon: BarChart3, perm: "view" },
    { href: "/history", label: "History", icon: History, perm: "view" },
  ] },
  { section: "Admin", items: [{ href: "/settings", label: "Settings", icon: Settings, perm: "admin" }] },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const path = usePathname();

  useEffect(() => {
    api<Me>("/auth/me").then(setMe).catch((e) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
    });
  }, [router]);
  useEffect(() => setOpen(false), [path]);

  if (!me) return <div className="mx-auto max-w-5xl px-4"><Spinner /></div>;

  const signOut = async () => {
    await api("/auth/logout", { method: "POST" });
    router.replace("/login");
  };
  const switchProduct = async () => {
    await api("/auth/mode", { body: { mode: me.mode.demo ? "real" : "demo" } });
    router.replace("/login");
  };
  const m = me.mode;

  const nav = (
    <nav className="flex h-full flex-col gap-6 p-4">
      <div className="px-2 pt-1"><Wordmark /></div>
      {NAV.map((s) => {
        const items = s.items.filter((i) => can(me, i.perm));
        if (!items.length) return null;
        return (
          <div key={s.section}>
            <div className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted/80">{s.section}</div>
            {items.map((i) => {
              const active = path?.startsWith(i.href);
              return (
                <Link key={i.href} href={i.href}
                  className={`group relative flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition ${active ? "bg-accent/10 font-semibold text-fg" : "text-muted hover:bg-sunken hover:text-fg"}`}>
                  {active && <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-accent" />}
                  <i.icon className={`h-4 w-4 transition ${active ? "text-accent" : "group-hover:scale-110"}`} /> {i.label}
                </Link>
              );
            })}
          </div>
        );
      })}
      <div className="mt-auto space-y-2">
        <div className={`flex items-start gap-2 rounded-xl px-3 py-2.5 text-xs ring-1 ring-inset ${m.demo || m.dry_run ? "bg-info/10 ring-info/25" : "bg-bad/10 ring-bad/25"}`}>
          {m.demo || m.dry_run ? <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" /> : <Send className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" />}
          <span>
            {m.demo ? <><b>Demo.</b> Fictional data. Nothing is ever sent.</>
              : m.dry_run ? <><b>Practice mode.</b> Emails are saved, not sent.</>
              : <><b>Live.</b> Emails are sent {m.test_recipient ? "to the test address only" : "to candidates"}.</>}
          </span>
        </div>
        <div className="flex items-center gap-3 rounded-xl bg-sunken/70 p-2.5 ring-1 ring-inset ring-line">
          <Avatar id={me.user.username} name={me.user.display_name} size={36} />
          <div className="min-w-0 flex-1 text-sm leading-tight">
            <div className="truncate font-semibold">{me.user.display_name}</div>
            <div className="truncate text-xs text-muted">{me.role_label}</div>
          </div>
          <button onClick={signOut} className="btn btn-ghost px-2" title={m.demo ? "Switch person" : "Sign out"} aria-label={m.demo ? "Switch person" : "Sign out"}>
            <LogOut className="h-4 w-4" />
          </button>
        </div>
        {m.modes.length > 1 && (
          <button onClick={switchProduct} className="btn btn-ghost w-full justify-start px-3 text-muted">
            <ArrowLeftRight className="h-4 w-4" /> {m.demo ? "Go to the real product" : "Try the demo"}
          </button>
        )}
        <div className="px-3 text-[11px] leading-snug text-muted/80">
          AI: {m.api_ready ? m.model : m.demo ? "keyword stand-in (no key)" : "no key set"} · {m.database}
        </div>
      </div>
    </nav>
  );

  return (
    <MeCtx.Provider value={me}>
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-line/70 bg-surface/80 backdrop-blur-xl md:block">{nav}</aside>
        {open && (
          <div className="fixed inset-0 z-40 bg-black/40 md:hidden" onClick={() => setOpen(false)}>
            <aside className="h-full w-64 bg-surface" onClick={(e) => e.stopPropagation()}>{nav}</aside>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 flex items-center gap-2 border-b border-line bg-bg/90 px-4 py-2 backdrop-blur md:hidden">
            <button className="btn btn-ghost px-2" onClick={() => setOpen(!open)} aria-label="Menu">
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <Wordmark />
          </header>
          <main className="mx-auto max-w-6xl animate-rise px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>
      </div>
    </MeCtx.Provider>
  );
}
