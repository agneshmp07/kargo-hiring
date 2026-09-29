"""Which role did the candidate apply for? Unclear -> score against every role (Section 1)."""
from __future__ import annotations

import re

_SPM_NAME = re.compile(r"(?:^|[^a-z])(spm|senior|sr)(?:[^a-z]|$)", re.I)
_PM_NAME = re.compile(r"(?:^|[^a-z])(pm|product[ _-]?manager)(?:[^a-z]|$)", re.I)
_APPLY = r"(?:applying|application|applied|position|role)\s*(?:for|:)?\s*[:\-]?\s*(?:the\s+)?"


def _role_names(params: dict | None) -> dict[str, str]:
    if params:
        from .versions import role_names

        return role_names(params)
    return {"PM": "Product Manager", "SPM": "Senior Product Manager"}


def detect_applied_role(file_name: str, text: str, params: dict | None = None) -> tuple[str | None, str]:
    """Returns (role code or None if unclear, how it was decided)."""
    names = _role_names(params)
    stem = file_name.rsplit(".", 1)[0]
    # Files saved by the upload screen / careers form / inbox are prefixed "ROLE__".
    prefix = stem.split("__", 1)[0] if "__" in stem else None
    if prefix and prefix.upper() in names:
        return prefix.upper(), "chosen at upload"
    if "SPM" in names and _SPM_NAME.search(stem):
        return "SPM", "file name"
    if "PM" in names and _PM_NAME.search(stem):
        return "PM", "file name"
    # "Applying for: <role name>". The name must follow the phrase directly, so
    # "Senior Product Manager" does not also count as "Product Manager".
    hits = [code for code, name in names.items()
            if re.search(_APPLY + re.escape(name).replace(r"\ ", r"\s+"), text, re.I)]
    if len(hits) == 1:
        return hits[0], "CV text"
    return None, "unclear, scored against every role"


def roles_to_score(applied: str | None, pm_years: float | None, params: dict) -> list[str]:
    """G3.2: also score against another role when the experience fits it (gate pass or
    near), or against every role when the applied role is unclear. Applied role first."""
    all_roles = list(params["layer_b"])
    if applied is None or applied not in all_roles:
        return all_roles
    roles = [applied]
    if pm_years is not None:
        tol = params["rules"]["gate_tolerance_years"]
        for other in all_roles:
            if other == applied:
                continue
            lo, hi = params["layer_b"][other]["gate_years_pm"]
            if lo - tol <= pm_years <= hi + tol:
                roles.append(other)
    return roles
