"""Jobs and scoring settings, versioned.

Version 1 is rubric_params_v02.json exactly as supplied, plus role metadata (names, JD text,
criteria definitions). Admins can publish new versions (new weights, new roles); every score
records the version it was computed with, and old versions are kept for audit.
"""
from __future__ import annotations

import copy
import json

from . import config, store

# Verbatim Layer B definitions from build prompt Section 3.
DEFAULT_DEFINITIONS = {
    "PM": {
        "zero_to_one_early_stage": "built a product or feature 0→1 at an early-stage company.",
        "shipped_with_adoption": "shipped features, with evidence that users actually adopted them.",
        "b2b_operational_users": "built B2B products for operational (daily-workflow) users.",
    },
    "SPM": {
        "integration_platform_data": "owned integration, platform, or data-layer products.",
        "build_config_avoid_calls": "made build-vs-configure-vs-don't-build calls and owned the consequences.",
        "early_stage_unstructured": "worked in an early-stage or unstructured environment.",
    },
}

_cache: dict[tuple, dict] = {}


def _default_v1() -> dict:
    from .parsing import parse_file

    params = config.load_params()
    roles = {}
    for code, name in config.ROLE_NAMES.items():
        jd = "(JD file not found)"
        for f in sorted(config.JDS_DIR.glob("*.docx")):
            if name in f.name and (code == "SPM" or "Senior" not in f.name):
                jd = parse_file(f).text
                break
        roles[code] = {"name": name, "jd_text": jd, "definitions": DEFAULT_DEFINITIONS[code]}
    params["_roles"] = roles
    return params


def ensure_seeded(conn) -> None:
    if not conn.execute("SELECT 1 FROM params_versions LIMIT 1").fetchone():
        conn.execute("INSERT INTO params_versions (version, params_json, note, created_by, created_at, active) "
                     "VALUES (1, ?, ?, ?, ?, 1)",
                     (json.dumps(_default_v1(), ensure_ascii=False), "v0.2-after-stress, as supplied",
                      "system", store.now()))


def active(conn=None) -> dict:
    def load(c):
        ensure_seeded(c)
        row = c.execute("SELECT version, params_json FROM params_versions WHERE active = 1 "
                        "ORDER BY version DESC LIMIT 1").fetchone()
        v = row["version"]
        key = (store.database_url() or str(store.db_path()), config.current_mode(), v)  # demo and real differ
        if key not in _cache:
            p = json.loads(row["params_json"])
            p["_version"] = v
            _cache[key] = p
        return copy.deepcopy(_cache[key])

    if conn is not None:
        return load(conn)
    with store.connect() as c:
        return load(c)


def get_version(version: int) -> dict | None:
    with store.connect() as c:
        row = c.execute("SELECT params_json FROM params_versions WHERE version = ?", (version,)).fetchone()
    return json.loads(row["params_json"]) if row else None


def history() -> list[dict]:
    with store.connect() as c:
        ensure_seeded(c)
        return store.rows(c, "SELECT version, note, created_by, created_at, active FROM params_versions "
                             "ORDER BY version DESC")


def role_codes(params: dict) -> list[str]:
    return list(params["layer_b"].keys())


def role_names(params: dict) -> dict[str, str]:
    return {r: params.get("_roles", {}).get(r, {}).get("name", r) for r in role_codes(params)}


def definitions(params: dict) -> dict[str, dict[str, str]]:
    return {r: params.get("_roles", {}).get(r, {}).get("definitions", {}) for r in role_codes(params)}


def jd_texts(params: dict) -> dict[str, str]:
    return {r: params.get("_roles", {}).get(r, {}).get("jd_text", "") for r in role_codes(params)}


def validate(params: dict) -> list[str]:
    errs = []
    try:
        b = params["blend"]
        if abs(b["layer_a_pattern"] + b["layer_b_role"] - 1) > 1e-6:
            errs.append("blend weights must add up to 1")
        if not params["bands"]["strong"] > params["bands"]["borderline"] >= 0:
            errs.append("bands: strong must be above borderline")
        for k in ("gate_tolerance_years", "role_rescue_B", "p1_floor_min"):
            if k not in params["rules"]:
                errs.append(f"rules.{k} missing")
        if not params["layer_b"]:
            errs.append("at least one role is needed")
        for role, lb in params["layer_b"].items():
            if not role.isalnum() or not role.isupper() or len(role) > 8:
                errs.append(f"role code {role!r} must be short upper-case letters/digits")
            total = sum(lb["weights"].values())
            if abs(total - 100) > 1e-6:
                errs.append(f"{role}: criteria weights add up to {total:g}, not 100")
            lo, hi = lb["gate_years_pm"]
            if not 0 <= lo <= hi:
                errs.append(f"{role}: gate years must be low <= high")
            defs = params.get("_roles", {}).get(role, {}).get("definitions", {})
            missing = [k for k in lb["weights"] if not defs.get(k)]
            if missing:
                errs.append(f"{role}: add a definition for {', '.join(missing)}")
            if not params.get("_roles", {}).get(role, {}).get("name"):
                errs.append(f"{role}: role name missing")
    except (KeyError, TypeError, ValueError) as exc:
        errs.append(f"malformed settings: {exc}")
    return errs


def publish(params: dict, note: str, by: str) -> int:
    params = {k: v for k, v in params.items() if k != "_version"}
    errs = validate(params)
    if errs:
        raise ValueError("; ".join(errs))
    if not note.strip():
        raise ValueError("please describe what changed")
    with store.connect() as c:
        ensure_seeded(c)
        v = c.execute("SELECT MAX(version) AS v FROM params_versions").fetchone()["v"] + 1
        c.execute("UPDATE params_versions SET active = 0")
        c.execute("INSERT INTO params_versions (version, params_json, note, created_by, created_at, active) "
                  "VALUES (?, ?, ?, ?, ?, 1)", (v, json.dumps(params, ensure_ascii=False), note, by, store.now()))
        store.audit("params_published", _conn=c, version=v, note=note, by=by)
    return v


def activate(version: int, by: str) -> None:
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM params_versions WHERE version = ?", (version,)).fetchone():
            raise ValueError(f"no version {version}")
        c.execute("UPDATE params_versions SET active = 0")
        c.execute("UPDATE params_versions SET active = 1 WHERE version = ?", (version,))
        store.audit("params_activated", _conn=c, version=version, by=by)


def recalculate_all(by: str) -> dict:
    """Recompute bands for every candidate from the stored AI codes with the active version.
    No AI call is needed. Roles whose criteria were never classified for a CV are skipped."""
    from . import roles as roles_mod
    from . import scoring

    params = active()
    changed, skipped = 0, []
    with store.connect() as c:
        for cand in store.all_candidates(c):
            obj = cand["llm_json"]
            if not obj or cand["erased_at"]:
                continue
            low = cand["confidence"] == "low"
            to_score = roles_mod.roles_to_score(cand["applied_role"], obj.get("pm_years"), params)
            results = {}
            for r in to_score:
                codes_b = obj.get("layer_b", {}).get(r)
                if not codes_b or set(params["layer_b"][r]["weights"]) - set(codes_b):
                    skipped.append(f"{cand['id']}:{r}")
                    continue
                results[r] = scoring.score_role(
                    {k: v["code"] for k, v in obj["layer_a"].items()},
                    {k: v["code"] for k, v in codes_b.items()}, obj.get("pm_years"), r, params, low)
            if not results:
                continue
            best = scoring.better_fit(results)
            c.execute("UPDATE candidates SET results_json = ?, better_fit = ?, params_version = ? WHERE id = ?",
                      (json.dumps(results), best, params["_version"], cand["id"]))
            changed += 1
        store.audit("params_recalculated", _conn=c, version=params["_version"], candidates=changed,
                    skipped=len(skipped), by=by)
    return {"recalculated": changed, "skipped_roles": skipped}
