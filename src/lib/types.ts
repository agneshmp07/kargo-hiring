export type Band = "Strong" | "Borderline" | "Not a fit";
export type Gate = "pass" | "near" | "fail" | "unknown";

export type Adjustment = { rule: string; why: string };
export type RoleResult = {
  role: string; band: Band; raw_band: Band; final: number; layer_a: number; layer_b: number;
  gate: Gate; gate_range: [number, number]; adjustments: Adjustment[]; floors: string[];
};
export type Code = { code: 0 | 0.5 | 1; evidence: string | null };
export type Decision = { id: number; decision: "Advance" | "Pass" | "Hold"; role: string; ts: string; decided_by: string | null };
export type Comment = { id: number; author: string; body: string; ts: string };
export type Review = {
  id: number; candidate_id: string; role: string; requested_by: string; assignee: string;
  status: "open" | "done"; opinion: string | null; note: string | null;
};
export type Stage = { candidate_id: string; role: string; stage: string; scheduled_for: string | null; updated_at: string };

export type Card = {
  id: string; name: string | null; applied_role: string | null; primary_role: string; better_fit: string;
  results: Record<string, RoleResult>; rationale: string; probes: string[];
  pm_years: number | null; pm_years_working: string; city: string; open_to_relocate: string;
  layer_a: Record<string, Code>; layer_b: Record<string, Record<string, Code>>;
  confidence: string; low_conf_reasons: string[]; evidence_flags: { var: string; flag: string }[];
  duplicate_of: string | null; source: string | null; backlog: boolean; received_at: string | null;
  decision: Decision | null; email_status: string | null; email_send_after: string | null; undoable: boolean;
  stage: Stage | null; comments: Comment[]; reviews: Review[]; hold_days: number | null;
};

export type Spot = { id: number; batch_id: string; candidate_id: string; role: string; verdict: string | null };
export type TeamUser = { username: string; display_name: string; role: string; can_review: boolean };

export type Board = {
  roles: string[]; role_names: Record<string, string>; cards: Card[]; spots: Spot[];
  bulk: Record<string, string[]>; users: TeamUser[]; undo_minutes: number;
};

export type Me = {
  user: { username: string; display_name: string; role: string; email: string };
  role_label: string; perms: string[];
  mode: { demo: boolean; modes: string[]; dry_run: boolean; test_recipient: boolean; api_ready: boolean; model: string; database: string; storage: string };
};
