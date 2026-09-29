import type { Band, Gate } from "./types";

export const VAR_LABEL: Record<string, string> = {
  P1: "Hands-on logistics / ops work",
  P2: "Built something unasked that others adopted",
  P3: "Owned decisions with no layer above",
  P4: "Personally resolved a live crisis",
  P5: "Killed something / ran a post-mortem",
  N1: "Logistics only via systems or a desk",
  N2: "Always had decision-makers above them",
  zero_to_one_early_stage: "Built 0→1 at an early-stage company",
  shipped_with_adoption: "Shipped features users adopted",
  b2b_operational_users: "Built for B2B daily-workflow users",
  integration_platform_data: "Owned integration / platform / data products",
  build_config_avoid_calls: "Made build vs configure vs don't-build calls",
  early_stage_unstructured: "Worked in early-stage / unstructured settings",
};
export const label = (v: string) => VAR_LABEL[v] ?? v.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export const SAFETY_NET: Record<string, string> = {
  "gate near": "Experience is just outside the JD range, so the top band is capped at Borderline.",
  "gate unknown": "Years of PM experience couldn't be read, so the top band is capped at Borderline.",
  "gate fail": "Experience is well outside the JD range. Shown so you can decide.",
  "P1 floor": "Has real hands-on ops experience, so it's kept at Borderline rather than dropped.",
  "low-confidence floor": "The CV was hard to read, so it's kept at Borderline for you to check.",
  "role rescue": "Strong role-specific fit, so it's kept at Borderline rather than dropped.",
};

export const BAND_TONE: Record<Band, Tone> = { Strong: "good", Borderline: "warn", "Not a fit": "neutral" };
export const BAND_RANK: Record<Band, number> = { Strong: 2, Borderline: 1, "Not a fit": 0 };
export const GATE: Record<Gate, { tone: Tone; text: string }> = {
  pass: { tone: "good", text: "fits the range" },
  near: { tone: "warn", text: "just outside the range" },
  fail: { tone: "bad", text: "well outside the range" },
  unknown: { tone: "neutral", text: "couldn't be read" },
};
export const EMAIL_STATUS: Record<string, string> = {
  scheduled: "waiting (undo window)", sending: "sending", dry_run: "saved (practice mode)", sent: "sent",
  delivered: "delivered", failed: "failed, see History", bounced: "bounced", suppressed: "not delivered (suppressed)",
  cancelled: "cancelled", complained: "marked as spam",
};
export const SOURCE_LABEL: Record<string, string> = {
  upload: "uploaded", careers: "careers form", inbox: "hiring inbox", folder: "folder", demo: "demo",
};
export const STAGE_TONE: Record<string, Tone> = {
  invited: "warn", scheduled: "info", interviewed: "violet", selected: "good", not_selected: "neutral", withdrawn: "neutral",
};

export type Tone = "good" | "warn" | "bad" | "info" | "violet" | "neutral" | "accent";

const IST = "Asia/Kolkata";
export function fmtTime(iso?: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", { timeZone: IST, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
export const fmtDate = (iso?: string | null) => (iso ? iso.slice(0, 10) : "-");
