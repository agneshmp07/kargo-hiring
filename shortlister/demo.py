"""Demo mode: a self-contained workspace under demo/ with fictional candidates.

- Never sends email and never uses Neon, whatever .env says (see config.dry_run / store.database_url).
- If no Anthropic key is set, CVs are scored by a keyword stand-in (clearly labelled in the UI).
  With a key, the real AI classifier is used.

Entry point: python -m shortlister demo   (or double-click run_demo.bat)
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

from . import config, llm

DEMO_HOME = config.ROOT / "demo"
SAMPLES_DIR = DEMO_HOME / "sample_cvs"

# ---------------------------------------------------------------- keyword stand-in

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_DATE = rf"(?:(?:{_MONTHS})[a-z]*\.?\s+)?(?:19|20)\d{{2}}"
_RANGE_RE = re.compile(rf"({_DATE})\s*(?:[–—-]|to)\s*(present|current|now|{_DATE})", re.I)
_PM_TITLE_RE = re.compile(r"\b(product manager|product owner|head of product|product lead|apm|"
                          r"associate product manager|director of product|vp,? product|group pm)\b", re.I)
_LOGISTICS_RE = re.compile(r"\b(logistics|freight|supply chain|3pl|shipping|shipment|courier|delhivery|"
                           r"carrier|warehouse|port)\b", re.I)
_DESK_RE = re.compile(r"\b(api|apis|integrat\w*|consult\w*|dashboard|advis\w*|analytics)\b", re.I)

RULES = {
    # var: (strong pattern, partial pattern)
    "P1": (r"\b(operations executive|ops executive|operations associate|shift supervisor|port|terminal|cha\b|"
           r"customs|freight forward\w*|3pl operations|warehouse (?:supervisor|operations|shift)|"
           r"on the (?:port|warehouse|shop) floor|shipment documentation|dispatch desk)",
           r"\b(fulfil?ment cent(?:re|er)|manufacturing|plant floor|field ops|field operations|dark store|"
           r"last-mile operations|store operations)"),
    "P2": (r"\b(built|created|made|set up|wrote)\b.{0,100}\b(adopted|rolled out to|used by (?:other|all)|"
           r"picked up by|other (?:teams|branches|hubs)|without (?:a mandate|being asked))",
           r"\b(built|created|set up)\b (?:a|an|our) (?:tool|tracker|script|sheet|process|template|macro|bot)"),
    "P3": (r"\b(sole (?:pm|product manager|owner)|first pm|only pm|report(?:ing|s|ed)? (?:directly )?to the "
           r"(?:ceo|founder|cto|co-founder)|independently owned|owned end[- ]to[- ]end)",
           r"\b(owned|owns|led|ran) (?:the )?[\w-]+ (?:module|area|roadmap|product|workflow|squad)"),
    "P4": (r"\b(outage|crisis|incident|went down|strike|breakdown|escalation|shutdown|flood)\b.{0,140}"
           r"\b(within|in|under) \d+ (?:hours|hrs|days|minutes|mins)",
           r"\b(outage|incident|war room|crisis|escalation)\b"),
    "P5": (r"\b(killed|sunset|shut down|deprecated|retired|stopped)\b.{0,140}\b(post-mortem|postmortem|"
           r"changed|afterwards|which led to|so we)",
           r"\b(post-mortem|postmortem|lessons learned|learned from (?:the )?failure|killed)\b"),
    "zero_to_one_early_stage": (r"\b(0\s?(?:→|to|-)\s?1|zero to one|from scratch|from zero|first version)\b",
                                r"\b(launched|built) (?:a |the )?new\b"),
    "shipped_with_adoption": (r"\b(shipped|launched|released|rolled out)\b.{0,140}\b(adopted|adoption|\d+% of|"
                              r"used daily|daily active|without being asked|now used by)",
                              r"\b(shipped|launched|released)\b"),
    "b2b_operational_users": (r"\b(b2b|enterprise|clients?|customers?)\b.{0,100}\b(operations|ops teams|"
                              r"warehouse|dispatch|daily|workflow|supervisors|coordinators|floor)",
                              r"\b(b2b|saas)\b"),
    "integration_platform_data": (r"\b(owned|led|own|ran|built)\b.{0,80}\b(integrations?|platform|api platform|"
                                  r"data layer|data platform|connectors?|edi|erp)",
                                  r"\b(integrations?|api|platform|data pipeline|erp|edi)\b"),
    "build_config_avoid_calls": (r"\b(build[- ]vs\.?[- ]buy|buy[- ]vs\.?[- ]build|instead of building|"
                                 r"decided (?:not )?to build|configure .{0,40}instead|chose not to build)",
                                 r"\b(vendor evaluation|make or buy|evaluated vendors)\b"),
    "early_stage_unstructured": (r"\b(seed[- ]stage|early[- ]stage|series a|employee #?\d+|first (?:pm|product "
                                 r"hire)|no pm process|founding team|startup)\b",
                                 r"\b(greenfield|new business unit|0 to 1)\b"),
}
_EARLY_RE = re.compile(RULES["early_stage_unstructured"][0], re.I)
_N2_RE = re.compile(r"\b(one of \d+ (?:pms|product managers|engineers)|team of \d+ (?:pms|product managers)|"
                    r"under the head of product|reporting to (?:the )?(?:senior|group|lead) pm|"
                    r"supported senior pms|\d+-person pm team)\b", re.I)


def _find(lines, pattern, exclude=None):
    rx = re.compile(pattern, re.I)
    for l in lines:
        if rx.search(l) and not (exclude and exclude.search(l)):
            return l
    return None


def _code(lines, var, exclude=None):
    strong, partial = RULES[var]
    hit = _find(lines, strong, exclude)
    if hit:
        return 1, hit
    hit = _find(lines, partial, exclude)
    return (0.5, hit) if hit else (0, None)


def _to_date(s: str, end: bool) -> date:
    s = s.strip().lower()
    if s in ("present", "current", "now"):
        return date.today()
    m = re.match(rf"(?:({_MONTHS})[a-z]*\.?\s+)?(\d{{4}})", s)
    month = (_MONTHS.split("|").index(m.group(1)) + 1) if m.group(1) else (12 if end else 1)
    return date(int(m.group(2)), month, 1)


def pm_years_from(lines) -> tuple[float | None, str]:
    total, parts = 0.0, []
    for l in lines:
        if _PM_TITLE_RE.search(l) and not re.search(r"\bintern", l, re.I):
            m = _RANGE_RE.search(l)
            if m:
                a, b = _to_date(m.group(1), False), _to_date(m.group(2), True)
                yrs = max(0.0, (b - a).days / 365.25)
                total += yrs
                parts.append(f"{m.group(0)} ≈ {yrs:.1f}")
    if parts:
        return round(total, 1), " + ".join(parts) + f" = {total:.1f} yrs"
    m = re.search(r"(\d+(?:\.\d+)?)\+?\s*years? (?:of )?(?:product|pm)", " ".join(lines), re.I)
    if m:
        return float(m.group(1)), f"stated: '{m.group(0)}'"
    return None, "no product-role dates found"


def keyword_classifier(payload: dict):
    """Stand-in for the LLM in demo mode. Same output schema; codes by keyword."""
    user = payload["messages"][0]["content"]
    cid = user.split("candidate_id: ")[1].split("\n")[0]
    text = user.split("<cv>\n", 1)[1].rsplit("\n</cv>", 1)[0]
    lines = [l.strip(" •▪-—\t") for l in text.splitlines() if len(l.split()) >= 3]
    obj = llm.empty_result(cid, "")

    p1, e1 = _code(lines, "P1", exclude=_DESK_RE)
    obj["layer_a"]["P1"] = {"code": p1, "evidence": e1}
    for v in ("P2", "P3", "P4", "P5"):
        c, e = _code(lines, v)
        obj["layer_a"][v] = {"code": c, "evidence": e}
    if p1 == 0:
        e = _find(lines, _LOGISTICS_RE.pattern)
        if e:
            obj["layer_a"]["N1"] = {"code": 1, "evidence": e}
    e = _find(lines, _N2_RE.pattern)
    if e and obj["layer_a"]["P3"]["code"] < 1:
        obj["layer_a"]["N2"] = {"code": 1, "evidence": e}

    for role, keys in llm.LAYER_B_KEYS.items():
        for k in keys:
            c, e = _code(lines, k)
            if k == "zero_to_one_early_stage" and c == 1 and not _EARLY_RE.search(text):
                c = 0.5
            obj["layer_b"][role][k] = {"code": c, "evidence": e}

    years, working = pm_years_from(lines)
    city = re.search(r"City:\s*([A-Za-z ]+)", text)
    reloc = "yes" if re.search(r"(willing|open|happy) to relocate", text, re.I) else "unknown"
    if re.search(r"not (?:willing|open) to relocate", text, re.I):
        reloc = "no"
    sparse = len(text) < 350
    found = [llm_label(v) for v in ("P1", "P2", "P3", "P4", "P5") if obj["layer_a"][v]["code"] == 1]
    obj.update(
        pm_years=years, pm_years_working=working,
        city=city.group(1).strip() if city else "unknown", open_to_relocate=reloc,
        confidence="low" if sparse or years is None else "medium",
        confidence_reason=("sparse CV" if sparse else "") + ("; PM dates unclear" if years is None else "")
        or "keyword stand-in (demo), not the AI",
        rationale=("Demo keyword scoring (not the AI). "
                   + (f"Clear signs of: {', '.join(found)}." if found else "No strong pattern signals found.")),
        probes=[],
    )
    return obj, None


def llm_label(var):
    return {"P1": "hands-on ops", "P2": "building unasked", "P3": "owning decisions",
            "P4": "crisis handling", "P5": "killing / post-mortems"}[var]


# ---------------------------------------------------------------- seed data

SEED_NAMES = ["Asha Kulkarni", "Dev Malhotra", "Farah Sheikh", "Gopal Menon", "Hina Qureshi", "Imran Patel",
              "Jaya Pillai", "Kabir Sethi", "Lata Deshpande", "Manav Joshi", "Nisha Rao", "Omkar Bhatt"]
SEED_EVIDENCE = {
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
SEED_RATIONALE = {
    "C01": "Two years hands-on in freight forwarding, then sole PM at an early-stage logistics SaaS. Killed features and documented why.",
    "C02": "Solid shipping record inside a layered PM team; no hands-on operations and few decisions owned alone.",
    "C03": "Heavy logistics vocabulary, but it all comes from API integrations; no hands-on operations role.",
    "C04": "Six years in freight operations with a crisis story and a tool peers adopted; only one year as a PM.",
    "C05": "Integration-platform owner reporting to the CTO, with clear build-vs-configure calls; no logistics ops background.",
    "C06": "Owns integrations at a large logistics company, but works under a Head of Product and from the desk.",
    "C07": "One-page CV with a PM title and unclear dates; too little to judge.",
    "C08": "Three years in customs-broking operations and two as a PM; modestly written but the pattern is there.",
    "C09": "Consulting background advising logistics clients from a desk; some PM ownership inside a team.",
    "C10": "Four years hands-on in 3PL operations, then 0-to-1 PM work at an early-stage company. The career gap is not considered.",
    "C11": "Applied for SPM with four years as PM plus logistics ops; fits the PM role better.",
    "C12": "Excellent SPM pattern with deep ops roots, but twelve years is well beyond the 5-8 range.",
}


def _seed_text(case, name):
    applying = "Senior Product Manager" if case["roles"][0] == "SPM" else "Product Manager"
    start = date.today().year - int(case["pm_years"])
    lines = [name, f"{name.split()[0].lower()}.{name.split()[1].lower()}@example.com | +91 90000 {int(case['id'][1:]):05d} | Mumbai",
             f"Applying for: {applying}", f"Demo reference: {case['id']}", "EXPERIENCE",
             f"Product Manager · Demo Co · Jan {start} – Present"]
    lines += list(SEED_EVIDENCE.values())
    return "\n".join(lines) + "\n"


def _seed_classifier(cases):
    def classify(payload):
        user = payload["messages"][0]["content"]
        ref = user.split("Demo reference: ")[1][:3]
        case = next(c for c in cases if c["id"] == ref)
        cid = user.split("candidate_id: ")[1].split("\n")[0]
        obj = llm.empty_result(cid, "")
        for v in llm.LAYER_A_KEYS:
            code = case["A"].get(v, 0)
            obj["layer_a"][v] = {"code": code, "evidence": SEED_EVIDENCE[v] if code else None}
        for role, keys in llm.LAYER_B_KEYS.items():
            for k in keys:
                code = case["B"].get(role, {}).get(k, 0)
                obj["layer_b"][role][k] = {"code": code, "evidence": SEED_EVIDENCE[k] if code else None}
        low = case.get("low_conf", False)
        obj.update(pm_years=case["pm_years"], pm_years_working=f"{case['pm_years']} yrs (demo profile)",
                   city="Mumbai", open_to_relocate="yes", confidence="low" if low else "high",
                   confidence_reason="sparse CV, unclear dates" if low else "clear dates",
                   rationale=SEED_RATIONALE[ref], probes=[])
        return obj, None
    return classify


def seed(log=print) -> None:
    """Fill demo/ with the 12 reference candidates, a Hold that's 8 days old and a backlog item."""
    from . import pipeline, store

    cases = json.loads((config.ROOT / "reference" / "synthetic_candidates.json").read_text(encoding="utf-8"))
    from . import auth, cvstore, decisions, settings

    config.ensure_dirs()
    for case, name in zip(cases, SEED_NAMES):
        slug = name.lower().replace(" ", "_")
        cvstore.put(f"{slug}_{case['roles'][0].lower()}.txt", _seed_text(case, name).encode("utf-8"),
                    {"source": "demo"})

    settings.put("undo_minutes", 0, "demo")  # seed decisions go straight to the outbox
    auth.seed_demo_users()
    pipeline.run_batch(classifier=_seed_classifier(cases), log=log, seed=7)

    decisions.record("KG-0008", "PM", "Hold", source="demo seed", by="arjun")
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    with store.connect() as conn:
        conn.execute("UPDATE decisions SET ts = ? WHERE candidate_id = ?", (old, "KG-0008"))
    pipeline.mark_backlog([f"{SEED_NAMES[5].lower().replace(' ', '_')}_spm.txt"])

    # An interview pipeline to look at: one booked for tomorrow, one already interviewed.
    decisions.record("KG-0001", "PM", "Advance", source="demo seed", by="arjun")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=5, minute=30, second=0, microsecond=0)
    decisions.set_stage("KG-0001", "scheduled", "cal.com webhook", scheduled_for=tomorrow.isoformat(),
                        booking_ref="demo-booking-1")
    decisions.record("KG-0010", "PM", "Advance", source="demo seed", by="arjun")
    decisions.set_stage("KG-0010", "interviewed", "priya")
    decisions.add_scorecard("KG-0010", "rahul", {"P1": 5, "P2": 4, "P3": 4, "P4": 5, "P5": 3}, "strong_yes",
                            "Walked me through the 3PL floor in detail. Clear owner of decisions.")
    decisions.request_review("KG-0005", "SPM", "arjun", "priya")
    decisions.add_comment("KG-0004", "priya", "Six years of freight ops with only one as PM. @arjun worth a call?")
    settings.put("undo_minutes", 1, "demo")  # a short undo window, so it's easy to try
    if config.storage_mode() == "files":
        write_samples()
        log(f"Demo ready in {DEMO_HOME}. Sample CVs to upload: {SAMPLES_DIR}")
    else:
        log("Demo ready. Download the sample CVs from the Add CVs page.")


def reset(log=print) -> None:
    """Wipe and re-seed the demo database (demo mode only)."""
    from . import store

    if not config.is_demo():
        raise RuntimeError("reset only runs in demo mode")
    store.wipe_all()
    seed(log)


# ---------------------------------------------------------------- sample CVs for the upload test

SAMPLES = {
    "Rhea_Kapoor_CV.docx": [
        "Rhea Kapoor", "rhea.kapoor@example.com | +91 98200 11122 | Andheri East, Mumbai",
        "EXPERIENCE",
        "Product Manager · Shipwise (seed-stage logistics SaaS) · {m36} – Present",
        "Sole PM reporting to the founder; built the carrier-booking module from scratch.",
        "Shipped automated shipping-bill checks; 80% of daily users adopted it within six weeks.",
        "Built for B2B freight forwarders whose operations teams use the tool daily.",
        "Killed the rate-comparison feature after 10 weeks of low use and wrote the post-mortem that changed our discovery process.",
        "Operations Executive · BlueAnchor Freight Forwarders, Nhava Sheva · {m72} – {m37}",
        "Handled shipment documentation and customs filing for 30 exporters on the port floor.",
        "Built a container-status sheet that the two other branches adopted without a mandate.",
        "When the ICEGATE outage hit, I refiled 55 shipping bills manually within 6 hours.",
        "EDUCATION", "B.Com · Sydenham College of Commerce · 2016–2019",
    ],
    "Arnav_Mehra_Resume.docx": [
        "Arnav Mehra", "arnav.mehra@example.com | +91 99300 22233 | Bengaluru",
        "EXPERIENCE",
        "Product Manager · ShopKart (e-commerce, 4,000 employees) · {m24} – Present",
        "One of 9 PMs in the checkout org, working to the Head of Product's quarterly roadmap.",
        "Integrated with Delhivery and Shiprocket APIs to show live logistics tracking in the app.",
        "Shipped a delivery-date predictor across the supply chain dashboard.",
        "Associate Product Manager · ShopKart · {m36} – {m25}",
        "Supported senior PMs on the returns flow and wrote specifications.",
        "EDUCATION", "MBA · IIM Lucknow · 2017–2019",
    ],
    "Sana_Iyer_SPM.docx": [
        "Sana Iyer", "sana.iyer@example.com | +91 98450 33344 | Pune | Open to relocate to Mumbai",
        "EXPERIENCE",
        "Senior Product Manager · PayBridge (Series A fintech) · {m60} – Present",
        "Owned the integrations platform connecting 40+ bank and ERP systems; reporting directly to the CTO.",
        "Ran a build-vs-buy review and chose to configure an iPaaS instead of building 20 connectors; owned the migration.",
        "Joined as employee #25 with no PM process in place.",
        "Shipped webhook retries; now used by 90% of merchants.",
        "During a bank API outage I rerouted settlement files within 4 hours.",
        "Product Manager · LedgerLoop · {m84} – {m61}",
        "Owned the data pipeline product for reconciliation.",
        "EDUCATION", "B.E. Computer Engineering · COEP · 2012–2016",
    ],
    "Tanvi_Shah.docx": [
        "Tanvi Shah", "tanvi@example.com",
        "Product Manager with experience in B2B SaaS. Worked on logistics tools. Good communicator.",
    ],
    "Vikrant_Rao_SeniorPM.docx": [
        "Vikrant Rao", "vikrant.rao@example.com | +91 98190 44455 | Navi Mumbai",
        "EXPERIENCE",
        "Head of Product · TransitGrid (Series A logistics SaaS) · {m150} – Present",
        "Sole product owner reporting to the CEO; owned the carrier and ERP integration platform.",
        "Decided not to build our own telematics stack and configured partner feeds instead; owned the outcome.",
        "Warehouse Shift Supervisor · Allcargo 3PL, Bhiwandi · {m200} – {m151}",
        "Ran warehouse operations for 120 staff across two shifts.",
        "Built a pick-path planner that the other three warehouses adopted on their own.",
        "When the truckers' strike hit, I rerouted 300 consignments by rail within 2 days.",
        "Killed the in-house yard app and wrote the post-mortem; we switched to a vendor afterwards.",
    ],
    "Kunal_Bose_CV.docx": [
        "Kunal Bose", "kunal.bose@example.com | +91 97690 55566 | Delhi",
        "EXPERIENCE",
        "Product Manager · RouteIQ (Series B logistics analytics) · {m30} – Present",
        "Owned the carrier scorecard module inside the analytics squad.",
        "Launched a new shipment-delay dashboard for enterprise clients.",
        "Senior Consultant · Bain-style strategy firm · {m84} – {m31}",
        "Advised freight and supply chain clients on network design from the client office.",
        "Ran a post-mortem after a failed pilot; lessons learned were shared with the team.",
    ],
}


SAMPLES_README = (
    "Fictional CVs for trying the 'Add CVs' page. Drag them into the upload box.\n"
    "Rhea: strong PM · Arnav: keyword trap (logistics via APIs only) · Sana: strong SPM, no ops\n"
    "Tanvi: sparse CV (low confidence) · Vikrant: great but 12+ yrs (over the SPM range) · Kunal: consultant-to-PM\n")


def sample_files() -> dict[str, bytes]:
    """The sample CVs as .docx bytes, with dates relative to today."""
    import io

    import docx

    today = date.today()

    def ago(months: int) -> str:
        y, m = divmod(today.year * 12 + today.month - 1 - months, 12)
        return date(y, m + 1, 1).strftime("%b %Y")

    stamps = {f"m{n}": ago(n) for n in (24, 25, 30, 31, 36, 37, 60, 61, 72, 84, 150, 151, 200)}
    out = {}
    for name, lines in SAMPLES.items():
        d = docx.Document()
        for l in lines:
            d.add_paragraph(l.format(**stamps))
        buf = io.BytesIO()
        d.save(buf)
        out[name] = buf.getvalue()
    return out


def samples_zip() -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sample_files().items():
            z.writestr(name, data)
        z.writestr("README.txt", SAMPLES_README)
    return buf.getvalue()


def write_samples() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in sample_files().items():
        (SAMPLES_DIR / name).write_bytes(data)
    (SAMPLES_DIR / "README.txt").write_text(SAMPLES_README, encoding="utf-8")
