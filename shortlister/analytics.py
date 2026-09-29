"""Numbers for the Analytics page and the board report: funnel, speed, sources, how often
people agree with the system, interview outcomes by band, a fairness check, AI spend,
calibration, and a training export for re-deriving the weights from real outcomes.

Fairness reporting reads cities from the vault. It is kept apart from scoring and never
feeds back into any score.
"""
from __future__ import annotations

import io
import json
import random
import statistics
from datetime import datetime

from . import store, vault
from .pipeline import primary_role

BANDS = ("Strong", "Borderline", "Not a fit")


def _data():
    with store.connect() as conn:
        cands = store.all_candidates(conn)
        decs = store.rows(conn, "SELECT * FROM decisions WHERE undone_at IS NULL ORDER BY id")
        stages = {s["candidate_id"]: s for s in store.rows(conn, "SELECT * FROM stages")}
        batches = store.rows(conn, "SELECT * FROM batches ORDER BY started_at")
    first_dec, last_dec = {}, {}
    for d in decs:
        first_dec.setdefault(d["candidate_id"], d)
        last_dec[d["candidate_id"]] = d
    return cands, first_dec, last_dec, stages, batches


def funnel(role: str | None = None) -> list[tuple[str, int]]:
    cands, _, last, stages, _ = _data()
    cs = [c for c in cands if role is None or primary_role(c) == role]
    band = lambda c: c["results_json"][primary_role(c)]["band"]  # noqa: E731
    reached = lambda c, st: c["id"] in stages and (stages[c["id"]]["stage"] in st)  # noqa: E731
    return [
        ("CVs scored", len(cs)),
        ("Recommended (Strong + Borderline)", sum(band(c) != "Not a fit" for c in cs)),
        ("Invited", sum(1 for c in cs if c["id"] in stages)),
        ("Interview booked", sum(reached(c, ("scheduled", "interviewed", "selected", "not_selected")) for c in cs)),
        ("Interviewed", sum(reached(c, ("interviewed", "selected", "not_selected")) for c in cs)),
        ("Selected", sum(reached(c, ("selected",)) for c in cs)),
    ]


def time_to_decision() -> dict:
    cands, first, _, _, _ = _data()
    days = []
    for c in cands:
        d = first.get(c["id"])
        if d and c["received_at"]:
            try:
                days.append((datetime.fromisoformat(d["ts"]) - datetime.fromisoformat(c["received_at"])).total_seconds()
                            / 86400)
            except ValueError:
                pass
    return {"decided": len(days), "median_days": round(statistics.median(days), 1) if days else None,
            "waiting": sum(1 for c in cands if c["id"] not in first)}


def source_quality() -> list[dict]:
    cands, _, last, stages, _ = _data()
    out = {}
    for c in cands:
        s = out.setdefault(c["source"] or "folder", {"source": c["source"] or "folder", "cvs": 0, "recommended": 0,
                                                     "invited": 0, "selected": 0})
        s["cvs"] += 1
        s["recommended"] += c["results_json"][primary_role(c)]["band"] != "Not a fit"
        s["invited"] += c["id"] in stages
        s["selected"] += stages.get(c["id"], {}).get("stage") == "selected"
    for s in out.values():
        s["recommended_%"] = round(100 * s["recommended"] / s["cvs"])
        s["invited_%"] = round(100 * s["invited"] / s["cvs"])
    return sorted(out.values(), key=lambda s: -s["cvs"])


def agreement() -> dict:
    """How often the human decision matched the recommendation."""
    cands, _, last, _, _ = _data()
    table = {b: {"Advance": 0, "Pass": 0, "Hold": 0} for b in BANDS}
    agree = total = 0
    for c in cands:
        d = last.get(c["id"])
        if not d:
            continue
        table[d["band"]][d["decision"]] += 1
        if d["decision"] in ("Advance", "Pass"):
            total += 1
            agree += (d["decision"] == "Advance") == (d["band"] != "Not a fit")
    return {"table": table, "agreement_%": round(100 * agree / total) if total else None, "decided": total}


def outcomes_by_band() -> dict:
    cands, _, _, stages, _ = _data()
    table = {b: {"selected": 0, "not_selected": 0, "withdrawn": 0, "open": 0} for b in BANDS}
    for c in cands:
        st = stages.get(c["id"])
        if not st:
            continue
        band = c["results_json"].get(st["role"], c["results_json"][primary_role(c)])["band"]
        key = st["stage"] if st["stage"] in ("selected", "not_selected", "withdrawn") else "open"
        table[band][key] += 1
    return table


def fairness_by_city(min_group: int = 5) -> list[dict]:
    """Recommendation and invite rates by city, with the four-fifths (80%) rule as a warning sign.
    Gender, age and similar are never collected, so they can't be reported."""
    cands, _, _, stages, _ = _data()
    try:
        ids = vault.all_identities()
    except RuntimeError:
        ids = {}
    groups = {}
    for c in cands:
        city = (ids.get(c["id"], {}).get("city") or (c["llm_json"] or {}).get("city") or "unknown").title()
        g = groups.setdefault(city, {"city": city, "cvs": 0, "recommended": 0, "invited": 0})
        g["cvs"] += 1
        g["recommended"] += c["results_json"][primary_role(c)]["band"] != "Not a fit"
        g["invited"] += c["id"] in stages
    rows = list(groups.values())
    for g in rows:
        g["recommended_rate"] = g["recommended"] / g["cvs"]
    big = [g for g in rows if g["cvs"] >= min_group]
    best = max((g["recommended_rate"] for g in big), default=0)
    for g in rows:
        g["impact_ratio"] = round(g["recommended_rate"] / best, 2) if best and g["cvs"] >= min_group else None
        g["flag"] = g["impact_ratio"] is not None and g["impact_ratio"] < 0.8
        g["recommended_rate"] = round(100 * g["recommended_rate"])
    return sorted(rows, key=lambda g: -g["cvs"])


def spend() -> dict:
    cands, _, _, _, batches = _data()
    costs = [(c["usage_json"] or {}).get("cost_usd", 0) for c in cands]
    total = sum(costs)
    scored = sum(1 for x in costs if x)
    return {"total_usd": round(total, 4), "per_cv_usd": round(total / scored, 4) if scored else None,
            "ai_scored": scored, "batches": [{"batch": b["id"], "cvs": b["n_new"], "mode": b["mode"],
                                              "cost_usd": round(b["cost_usd"] or 0, 4)} for b in batches]}


# ---------------------------------------------------------------- calibration

def calibration_queue(rater: str, n: int = 10, seed: int | None = None) -> list[dict]:
    with store.connect() as conn:
        rated = {r["candidate_id"] for r in conn.execute("SELECT candidate_id FROM calibration WHERE rater = ?",
                                                          (rater,))}
        pool = [c for c in store.all_candidates(conn) if c["id"] not in rated and c["redacted_text"]]
    done = len(rated)
    rng = random.Random(seed if seed is not None else rater)
    rng.shuffle(pool)
    return pool[:max(0, n - done)]


def rate(cid: str, rater: str, role: str, rating: str) -> None:
    if rating not in BANDS:
        raise ValueError(rating)
    with store.connect() as conn:
        c = store.get_candidate(conn, cid)
        conn.execute("INSERT OR IGNORE INTO calibration (candidate_id, rater, role, rating, system_band, ts) "
                     "VALUES (?,?,?,?,?,?)", (cid, rater, role, rating, c["results_json"][role]["band"], store.now()))
        store.audit("calibration_rating", _conn=conn, candidate_id=cid, rater=rater)


def calibration_summary(rater: str | None = None) -> dict:
    with store.connect() as conn:
        sql = "SELECT * FROM calibration" + (" WHERE rater = ?" if rater else "")
        rows = store.rows(conn, sql, (rater,) if rater else ())
    table = {h: {s: 0 for s in BANDS} for h in BANDS}
    for r in rows:
        table[r["rating"]][r["system_band"]] += 1
    agree = sum(table[b][b] for b in BANDS)
    disagreements = [r for r in rows if r["rating"] != r["system_band"]]
    return {"rated": len(rows), "agreement_%": round(100 * agree / len(rows)) if rows else None,
            "table": table, "disagreements": disagreements,
            "verdict": None if len(rows) < 10 else
            ("Good match: fine to rely on the shortlist." if len(disagreements) <= 2 else
             "More than 2 of 10 disagree: review the weights before clearing the full batch.")}


# ---------------------------------------------------------------- exports

def training_export_csv() -> str:
    """AI codes + human outcomes, one row per candidate, for re-deriving the weights."""
    import csv

    cands, _, last, stages, _ = _data()
    buf = io.StringIO()
    cols = ["candidate_id", "role", "pm_years", "P1", "P2", "P3", "P4", "P5", "N1", "N2", "band", "decision",
            "interview_outcome"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for c in cands:
        obj = c["llm_json"] or {}
        role = primary_role(c)
        w.writerow({"candidate_id": c["id"], "role": role, "pm_years": obj.get("pm_years"),
                    **{v: obj.get("layer_a", {}).get(v, {}).get("code") for v in ("P1", "P2", "P3", "P4", "P5", "N1", "N2")},
                    "band": c["results_json"][role]["band"],
                    "decision": (last.get(c["id"]) or {}).get("decision", ""),
                    "interview_outcome": stages.get(c["id"], {}).get("stage", "")})
    return buf.getvalue()


def report_pdf() -> bytes:
    """One-page board report."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Kargo hiring report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Generated {datetime.now().strftime('%d %b %Y %H:%M')}", new_x="LMARGIN", new_y="NEXT")

    def section(title, rows):
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for label, value in rows:
            pdf.cell(95, 6, str(label))
            pdf.cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")

    section("Funnel", funnel())
    t = time_to_decision()
    section("Speed", [("Decided", t["decided"]), ("Median days to decision", t["median_days"] or "-"),
                      ("Still waiting", t["waiting"])])
    a = agreement()
    section("Human vs recommendation", [("Decisions (Invite/Pass)", a["decided"]),
                                        ("Agreement with recommendation", f"{a['agreement_%']}%" if a["agreement_%"]
                                         is not None else "-")])
    section("Sources", [(s["source"], f"{s['cvs']} CVs, {s['recommended_%']}% recommended, {s['invited_%']}% invited")
                        for s in source_quality()])
    flagged = [f for f in fairness_by_city() if f["flag"]]
    section("Fairness check (by city, 80% rule)",
            [(f["city"], f"ratio {f['impact_ratio']}") for f in flagged] or [("No groups flagged", "")])
    s = spend()
    section("AI spend", [("Total", f"${s['total_usd']:.2f}"), ("Per CV", f"${s['per_cv_usd']:.3f}" if s["per_cv_usd"]
                                                                       else "-")])
    out = pdf.output()
    return bytes(out)
