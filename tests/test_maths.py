"""Acceptance test 1: scoring matches reference/stress_run.py on synthetic_candidates.json."""
import ast
import json

import pytest

from conftest import ROOT
from shortlister import config
from shortlister.scoring import LAYER_A_POINTS, score_role

REF = ROOT / "reference"
PARAMS = config.load_params()
CASES = json.loads((REF / "synthetic_candidates.json").read_text(encoding="utf-8"))

EXPECTED = {
    ("C01", "PM"): "Strong", ("C02", "PM"): "Not a fit", ("C03", "PM"): "Not a fit",
    ("C04", "PM"): "Borderline", ("C05", "SPM"): "Strong", ("C06", "SPM"): "Borderline",
    ("C07", "PM"): "Borderline", ("C08", "PM"): "Borderline", ("C09", "PM"): "Not a fit",
    ("C10", "PM"): "Strong", ("C11", "SPM"): "Borderline", ("C11", "PM"): "Strong",
    ("C12", "SPM"): "Borderline",
}


def reference_scorer():
    """Load derive/layer_a/score straight out of stress_run.py (the script runs
    everything at import, so pull just the function definitions)."""
    src = (REF / "stress_run.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("derive", "layer_a", "score")]
    params = json.loads((ROOT / "rubric_params_v02.json").read_text(encoding="utf-8"))
    ns = {"P": params, "H": params["hire_coding"], "OUT": params["hire_coding"]["_outcome"],
          "POS": ["P1", "P2", "P3", "P4", "P5"], "NEG": ["N1", "N2"]}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "stress_run.py", "exec"), ns)
    _, W = ns["derive"](list(ns["OUT"]))
    return ns, W


def cases():
    return [(c, role) for c in CASES for role in c["roles"]]


@pytest.mark.parametrize("case,role", cases(), ids=[f"{c['id']}-{r}" for c, r in cases()])
def test_matches_reference(case, role):
    ns, W = reference_scorer()
    A_ref = ns["layer_a"](case, W)
    _, B_ref, _, gate_ref, band_ref, _ = ns["score"](case, W, role)
    final_ref = PARAMS["blend"]["layer_a_pattern"] * A_ref + PARAMS["blend"]["layer_b_role"] * B_ref

    ours = score_role(case["A"], case["B"][role], case["pm_years"], role, PARAMS, case.get("low_conf", False))
    assert ours["band"] == band_ref
    assert ours["band"] == EXPECTED[(case["id"], role)]
    assert ours["gate"] == gate_ref
    # The Section 3 points are rounded to 1 dp and sum to 99.9, so a full-marks Layer A
    # differs from the unrounded reference by exactly 0.1. EPS absorbs float noise only.
    EPS = 1e-9
    assert abs(ours["exact"]["final"] - final_ref) <= 0.1 + EPS
    assert abs(ours["exact"]["layer_a"] - A_ref) <= 0.1 + EPS
    assert abs(ours["exact"]["layer_b"] - B_ref) <= 0.1 + EPS


def test_all_expected_cases_covered():
    assert {(c["id"], r) for c, r in cases()} == set(EXPECTED)


def test_points_are_the_authoritative_rounded_values():
    ns, W = reference_scorer()
    for v, pts in LAYER_A_POINTS.items():
        assert round(W[v], 1) == pts


def test_floor_order_and_gate_rules():
    # P1 floor lifts a gate-fail Not a fit (C12 path)...
    r = score_role({"P1": 1}, {}, 12, "SPM", PARAMS)
    assert r["gate"] == "fail" and r["band"] == "Borderline" and r["floors"] == ["gate fail", "P1 floor"]
    # ...but not when N1 > 0.
    r = score_role({"P1": 1, "N1": 1}, {}, 3, "PM", PARAMS)
    assert r["band"] == "Not a fit"
    # Role rescue never applies on gate fail.
    r = score_role({}, {"integration_platform_data": 1, "build_config_avoid_calls": 1}, 12, "SPM", PARAMS)
    assert r["layer_b"] >= 55 and r["band"] == "Not a fit"
    # Low-confidence floor applies even on gate fail (recall first).
    r = score_role({}, {}, 12, "SPM", PARAMS, low_confidence=True)
    assert r["band"] == "Borderline"
    # Near caps Strong at Borderline.
    r = score_role({"P1": 1, "P2": 1, "P3": 1, "P4": 1, "P5": 1}, {"zero_to_one_early_stage": 1,
                   "shipped_with_adoption": 1, "b2b_operational_users": 1}, 5, "PM", PARAMS)
    assert r["raw_band"] == "Strong" and r["gate"] == "near" and r["band"] == "Borderline"
