"""Deterministic scoring. The LLM classifies; this module calculates (G5.2).

Reproduces reference/stress_run.py `score()` using the authoritative points in
rubric_params_v02.json / build prompt Section 3. Pure functions, no I/O.
"""
from __future__ import annotations

POS = ("P1", "P2", "P3", "P4", "P5")
NEG = ("N1", "N2")
LAYER_A_VARS = POS + NEG

# Section 3 of the build prompt. Authoritative; do not re-derive.
LAYER_A_POINTS = {
    "P1": 32.6, "P2": 10.9, "P3": 21.7, "P4": 21.7, "P5": 13.0,
    "N1": -5.4, "N2": -10.9,
}

BAND_RANK = {"Not a fit": 0, "Borderline": 1, "Strong": 2}
VALID_CODES = (0, 0.5, 1)


def layer_a(codes: dict, params: dict) -> float:
    """Layer A = max(0, sum(points x code)). If N1 > 0, P1 is set to 0 first."""
    x = {v: float(codes.get(v, 0) or 0) for v in LAYER_A_VARS}
    if x["N1"] > 0 and params["rules"].get("n1_caps_p1_at_zero", True):
        x["P1"] = 0.0
    return max(0.0, sum(LAYER_A_POINTS[v] * x[v] for v in LAYER_A_VARS))


def layer_b(codes: dict, role: str, params: dict) -> float:
    weights = params["layer_b"][role]["weights"]
    return sum(w * float(codes.get(k, 0) or 0) for k, w in weights.items())


def gate(pm_years: float | None, role: str, params: dict) -> str:
    """pass / near / fail. `unknown` when years could not be extracted."""
    if pm_years is None:
        return "unknown"
    lo, hi = params["layer_b"][role]["gate_years_pm"]
    tol = params["rules"]["gate_tolerance_years"]
    y = float(pm_years)
    if lo <= y <= hi:
        return "pass"
    if lo - tol <= y <= hi + tol:
        return "near"
    return "fail"


def score_role(
    a_codes: dict,
    b_codes: dict,
    pm_years: float | None,
    role: str,
    params: dict,
    low_confidence: bool = False,
) -> dict:
    """Score one candidate against one role. Returns every intermediate so the UI
    can explain exactly what happened."""
    lb_params = params["layer_b"][role]
    A = layer_a(a_codes, params)
    B = layer_b(b_codes, role, params)
    blend = params["blend"]
    final = blend["layer_a_pattern"] * A + blend["layer_b_role"] * B

    bands = params["bands"]
    raw_band = (
        "Strong" if final >= bands["strong"]
        else "Borderline" if final >= bands["borderline"]
        else "Not a fit"
    )
    band = raw_band
    g = gate(pm_years, role, params)
    lo, hi = lb_params["gate_years_pm"]
    yrs = "unknown" if pm_years is None else f"{pm_years:g}"
    adjustments: list[dict] = []

    # Gate (rule 6)
    if g == "fail":
        adjustments.append({"rule": "gate fail",
                            "why": f"{yrs} yrs PM is outside {lo}-{hi} +/-1; recommendation set to Not a fit"})
        band = "Not a fit"
    elif g in ("near", "unknown") and band == "Strong":
        # Unknown years are treated like "near": a Strong cannot be confirmed without years.
        band = "Borderline"
        why = (f"{yrs} yrs PM is within 1 yr of the {lo}-{hi} range; Strong capped at Borderline"
               if g == "near" else "PM years could not be read; Strong capped at Borderline")
        adjustments.append({"rule": f"gate {g}", "why": why})

    rules = params["rules"]
    # Floors, in order (rule 7 / G1.2)
    p1 = float(a_codes.get("P1", 0) or 0)
    n1 = float(a_codes.get("N1", 0) or 0)
    if p1 >= rules.get("p1_floor_min", 1) and n1 == 0 and BAND_RANK[band] < 1:
        band = "Borderline"
        adjustments.append({"rule": "P1 floor",
                            "why": f"P1 = {p1:g} (hands-on ops) with N1 = 0; kept at Borderline"})
    if low_confidence and rules.get("low_confidence_to_borderline", True) and BAND_RANK[band] < 1:
        band = "Borderline"
        adjustments.append({"rule": "low-confidence floor",
                            "why": "extraction confidence is low; kept at Borderline for a human look"})
    if B >= rules.get("role_rescue_B", 999) and BAND_RANK[band] < 1 and g != "fail":
        band = "Borderline"
        adjustments.append({"rule": "role rescue",
                            "why": f"Layer B = {B:.1f} >= {rules['role_rescue_B']} and gate is not fail"})

    return {
        "role": role,
        "layer_a": round(A, 1),
        "layer_b": round(B, 1),
        "final": round(final, 1),
        "exact": {"layer_a": A, "layer_b": B, "final": final},
        "gate": g,
        "gate_range": [lo, hi],
        "raw_band": raw_band,
        "band": band,
        "adjustments": adjustments,
        "floors": [a["rule"] for a in adjustments],
    }


def better_fit(results: dict[str, dict]) -> str:
    """Role with the higher band, then the higher final score."""
    return max(results, key=lambda r: (BAND_RANK[results[r]["band"]], results[r]["final"]))
