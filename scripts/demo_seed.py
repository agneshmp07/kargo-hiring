"""Seed a demo workspace from the 12 synthetic candidates, with no API calls.

    set KARGO_HOME=C:\\path\\to\\demo   (PowerShell: $env:KARGO_HOME = "...")
    python scripts/demo_seed.py
    python -m shortlister ui

Writes fictional CVs to $KARGO_HOME/applications and scores them with a stand-in
classifier that returns each synthetic candidate's codes. Refuses to run against
the real repo folders.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("KARGO_HOME") or Path(os.environ["KARGO_HOME"]).resolve() == ROOT:
    sys.exit("Set KARGO_HOME to a separate demo folder first; this never seeds the real workspace.")

from shortlister import config, llm, pipeline  # noqa: E402

CASES = json.loads((ROOT / "reference" / "synthetic_candidates.json").read_text(encoding="utf-8"))
NAMES = ["Asha Kulkarni", "Dev Malhotra", "Farah Sheikh", "Gopal Menon", "Hina Qureshi", "Imran Patel",
         "Jaya Pillai", "Kabir Sethi", "Lata Deshpande", "Manav Joshi", "Nisha Rao", "Omkar Bhatt"]
EVIDENCE = {
    "P1": "Ran the export documentation desk at a Nhava Sheva freight forwarder for two years.",
    "P2": "Built a shipment-exception tracker that three other ops teams adopted without being asked.",
    "P3": "Sole PM on the platform, reporting directly to the founder.",
    "P4": "During the March customs portal outage I cleared 40 held shipments manually within 8 hours.",
    "P5": "Killed the rate-quote feature after low use and wrote the post-mortem that changed our discovery process.",
    "N1": "Integrated carrier and 3PL APIs into the checkout flow.",
    "N2": "One of six PMs in the product org, working to the Head of Product's roadmap.",
    "zero_to_one_early_stage": "Launched the booking module from zero at a seed-stage startup.",
    "shipped_with_adoption": "Shipped bulk upload; 70% of daily users adopted it within a month.",
    "b2b_operational_users": "Built tools used every day by warehouse supervisors at B2B clients.",
    "integration_platform_data": "Owned the integrations platform connecting ERPs and carrier systems.",
    "build_config_avoid_calls": "Decided to configure an iPaaS instead of building connectors, and owned the migration.",
    "early_stage_unstructured": "Joined as employee 12 with no PM process in place.",
}


def cv_text(case, name):
    applying = "Senior Product Manager" if case["roles"][0] == "SPM" else "Product Manager"
    lines = [name, f"{name.split()[0].lower()}@example.com | +91 90000 0{case['id'][1:]}000 | Mumbai",
             f"Applying for: {applying}", f"Demo reference: {case['id']}. {case['label']}", "EXPERIENCE",
             f"Product Manager, {case['pm_years']} years in total."]
    lines += list(EVIDENCE.values())
    return "\n".join(lines) + "\n"


def classifier(payload):
    user = payload["messages"][0]["content"]
    ref = user.split("Demo reference: ")[1][:3]
    case = next(c for c in CASES if c["id"] == ref)
    cid = user.split("candidate_id: ")[1].split("\n")[0]
    obj = llm.empty_result(cid, "")
    for v in llm.LAYER_A_KEYS:
        code = case["A"].get(v, 0)
        obj["layer_a"][v] = {"code": code, "evidence": EVIDENCE[v] if code else None}
    for role, keys in llm.LAYER_B_KEYS.items():
        for k in keys:
            code = case["B"].get(role, {}).get(k, 0)
            obj["layer_b"][role][k] = {"code": code, "evidence": EVIDENCE[k] if code else None}
    obj.update(pm_years=case["pm_years"], pm_years_working=f"demo value from {ref}", city="Mumbai",
               open_to_relocate="yes", confidence="low" if case.get("low_conf") else "high",
               confidence_reason="sparse CV, unclear dates" if case.get("low_conf") else "clear dates",
               rationale=f"Demo candidate {ref}: {case['label'].split(':')[0]}.",
               probes=[])
    return obj, None


config.ensure_dirs()
for case, name in zip(CASES, NAMES):
    role = case["roles"][0].lower()
    (config.APPLICATIONS_DIR / f"{case['id']}_{role}.txt").write_text(cv_text(case, name), encoding="utf-8")
pipeline.run_batch(classifier=classifier, seed=7)
