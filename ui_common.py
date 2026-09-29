"""Shared pieces for the Streamlit pages: the signed-in user, per-run data, labels and the candidate card."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from shortlister import auth, config, decisions, store, vault, versions
from shortlister.pipeline import primary_role
from shortlister.scoring import BAND_RANK

BAND_STYLE = {
    "Strong": ("green", ":material/star:"),
    "Borderline": ("orange", ":material/balance:"),
    "Not a fit": ("gray", ":material/remove_circle_outline:"),
}
GATE_STYLE = {"pass": ("green", "fits the range"), "near": ("orange", "just outside the range"),
              "fail": ("red", "well outside the range"), "unknown": ("gray", "couldn't be read")}
VAR_LABEL = {
    "P1": "Hands-on logistics / ops work", "P2": "Built something unasked that others adopted",
    "P3": "Owned decisions with no layer above", "P4": "Personally resolved a live crisis",
    "P5": "Killed something / ran a post-mortem",
    "N1": "Logistics only via systems or a desk", "N2": "Always had decision-makers above them",
    "zero_to_one_early_stage": "Built 0→1 at an early-stage company",
    "shipped_with_adoption": "Shipped features users adopted",
    "b2b_operational_users": "Built for B2B daily-workflow users",
    "integration_platform_data": "Owned integration / platform / data products",
    "build_config_avoid_calls": "Made build vs configure vs don't-build calls",
    "early_stage_unstructured": "Worked in early-stage / unstructured settings",
}
SAFETY_NET = {
    "gate near": "Experience is just outside the JD range, so the top band is capped at Borderline.",
    "gate unknown": "Years of PM experience couldn't be read, so the top band is capped at Borderline.",
    "gate fail": "Experience is well outside the JD range. Shown so you can decide.",
    "P1 floor": "Has real hands-on ops experience, so it's kept at Borderline rather than dropped.",
    "low-confidence floor": "The CV was hard to read, so it's kept at Borderline for you to check.",
    "role rescue": "Strong role-specific fit, so it's kept at Borderline rather than dropped.",
}
SOURCE_LABEL = {"upload": "uploaded", "careers": "careers form", "inbox": "hiring inbox", "folder": "folder",
                "demo": "demo"}
EMAIL_STATUS = {"scheduled": "waiting (undo window)", "dry_run": "saved to outbox (practice mode)", "sent": "sent",
                "failed": "failed, see History", "bounced": "bounced", "cancelled": "cancelled", "queued": "queued",
                "complained": "marked as spam", "delivered": "delivered", "sending": "sending",
                "suppressed": "not delivered (suppressed)"}


def label(var: str) -> str:
    return VAR_LABEL.get(var, var.replace("_", " ").capitalize())


# ---------------------------------------------------------------- user

def user() -> dict | None:
    return st.session_state.get("user")


def can(perm: str) -> bool:
    return auth.can(user(), perm)


def who() -> str | None:
    u = user()
    return u["username"] if u else None


def flash(msg: str) -> None:
    st.session_state["flash"] = msg


def show_flash() -> None:
    if msg := st.session_state.pop("flash", None):
        st.success(msg, icon=":material/check_circle:")


# ---------------------------------------------------------------- data for one run

def load_state() -> dict:
    with store.connect() as conn:
        cands = store.all_candidates(conn)
        latest = {}
        for c in cands:
            d = store.latest_decision(conn, c["id"])
            latest[c["id"]] = dict(d) if d else None
        all_emails = store.emails(conn)
        spots = store.rows(conn, "SELECT * FROM spot_checks ORDER BY id DESC")
        stages = {s["candidate_id"]: s for s in store.rows(conn, "SELECT * FROM stages")}
        comments, reviews = {}, {}
        for cm in store.rows(conn, "SELECT * FROM comments ORDER BY id"):
            comments.setdefault(cm["candidate_id"], []).append(cm)
        for rv in store.rows(conn, "SELECT * FROM reviews ORDER BY id DESC"):
            reviews.setdefault(rv["candidate_id"], []).append(rv)
        undoable = {cid: decisions.undoable(conn, d) for cid, d in latest.items() if d}
    params = versions.active()
    email_by_decision = {}
    for e in sorted(all_emails, key=lambda e: e["id"]):
        if e["decision_id"] and e["channel"] == "email" and e["kind"] in ("invite", "rejection"):
            email_by_decision.setdefault(e["decision_id"], e)
    return {
        "cands": cands, "by_id": {c["id"]: c for c in cands}, "latest": latest, "emails": all_emails,
        "email_by_decision": email_by_decision, "spots": spots, "stages": stages, "comments": comments,
        "reviews": reviews, "users": auth.users(active_only=True),
        "undoable": undoable, "params": params, "roles": versions.role_codes(params),
        "role_names": versions.role_names(params), "reminders": {r["candidate_id"]: r for r in decisions.hold_reminders()},
    }


def is_open(state, cid) -> bool:
    d = state["latest"].get(cid)
    return d is None or d["decision"] == "Hold"


def sort_key(c, role):
    r = c["results_json"][role]
    return (-BAND_RANK[r["band"]], -r["final"], c["id"])


def display_name(state, c) -> str:
    """Candidate ID, plus the name once someone has been invited (names stay hidden before)."""
    d = state["latest"].get(c["id"])
    if d and d["decision"] == "Advance":
        return f"{c['id']} · {vault.get(c['id']).get('name') or 'name not found'}"
    return c["id"]


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    from datetime import timedelta

    return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %I:%M %p")


# ---------------------------------------------------------------- actions (callbacks)

def act(cid, role, decision):
    try:
        out = decisions.record(cid, role, decision, by=who())
    except decisions.DecisionError as exc:
        st.toast(str(exc), icon=":material/error:")
        return
    email = out["email"]
    if decision == "Advance":
        msg = f"{cid} invited: {vault.get(cid).get('name') or 'name not found'}"
    elif decision == "Pass":
        msg = f"{cid} passed"
    else:
        msg = f"{cid} on hold. You'll be reminded in {config.HOLD_REMINDER_DAYS} days"
    if email:
        msg += f" · email {EMAIL_STATUS.get(email['status'], email['status'])}"
    st.toast(msg, icon=":material/check_circle:")


def undo(decision_id):
    try:
        decisions.undo(decision_id, by=who())
        st.toast("Undone. The email was cancelled before sending.", icon=":material/undo:")
    except decisions.DecisionError as exc:
        st.toast(str(exc), icon=":material/error:")


# ---------------------------------------------------------------- candidate card

def render_card(state, c, role, key, show_buttons=True, compact=False):
    obj = c["llm_json"] or {}
    res = c["results_json"]
    r = res[role]
    dec = state["latest"].get(c["id"])

    with st.container(border=True):
        color, icon = BAND_STYLE[r["band"]]
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"#### {display_name(state, c)}")
            st.badge(r["band"], icon=icon, color=color)
            st.markdown(f"**{r['final']:.0f}**/100")
            gcolor, gtext = GATE_STYLE[r["gate"]]
            lo, hi = r["gate_range"]
            yrs = obj.get("pm_years")
            st.badge(f"{'?' if yrs is None else f'{yrs:g}'} yrs PM · role asks {lo}–{hi} ({gtext})",
                     icon=":material/work_history:", color=gcolor)
            reloc = obj.get("open_to_relocate", "unknown")
            city = obj.get("city", "unknown")
            in_mumbai = "mumbai" in str(city).lower()
            st.badge(f"{city}" + ("" if in_mumbai else f" · relocate: {reloc}"), icon=":material/location_on:",
                     color="blue" if in_mumbai or reloc == "yes" else "gray")
            if c["confidence"] == "low":
                st.badge("Check this CV yourself", icon=":material/visibility:", color="violet")
            if c.get("duplicate_of"):
                st.badge(f"Also applied as {c['duplicate_of']}", icon=":material/content_copy:", color="red")
            if c.get("source") and c["source"] not in ("folder", "demo"):
                st.badge(SOURCE_LABEL.get(c["source"], c["source"]), icon=":material/input:", color="gray")

        for adj in r["adjustments"]:
            st.caption(f":material/shield: **Safety net:** {SAFETY_NET.get(adj['rule'], adj['why'])}")
        if c["confidence"] == "low" and c["low_conf_reasons"]:
            st.caption(":material/info: Why: " + "; ".join(c["low_conf_reasons"]))
        for o in [o for o in res if o != role]:
            ro = res[o]
            better = c["better_fit"] == o
            st.caption(f":material/swap_horiz: Also checked for **{state['role_names'].get(o, o)}**: {ro['band']}, "
                       f"{ro['final']:.0f}/100" + (" · :green[**looks like the better fit**]" if better else ""))
        if obj.get("rationale"):
            st.markdown(f"**Summary.** {obj['rationale']}")

        if not compact:
            left, right = st.columns([3, 2], gap="large")
            with left:
                evidence(c, obj, role)
            with right:
                st.markdown("**Ask in the interview**")
                st.markdown("\n".join(f"{i}. {p}" for i, p in enumerate(obj.get("probes", []), 1)))
                st.caption(f"Pattern score {r['layer_a']:.0f} · role fit {r['layer_b']:.0f} · "
                           f"PM years: {obj.get('pm_years_working', '')}")

        _team_row(state, c, role, key)

        if dec and dec["decision"] != "Hold":
            email = state["email_by_decision"].get(dec["id"])
            status = EMAIL_STATUS.get(email["status"], email["status"]) if email else "none"
            what = "Invited to interview" if dec["decision"] == "Advance" else "Passed"
            by = f" by {dec['decided_by']}" if dec.get("decided_by") else ""
            with st.container(horizontal=True, vertical_alignment="center"):
                st.success(f"{what} ({state['role_names'].get(dec['role'], dec['role'])}){by} on {dec['ts'][:10]} "
                           f"· email {status}", icon=":material/task_alt:")
                if state["undoable"].get(c["id"]) and can("decide"):
                    st.button("Undo", key=f"{key}-undo", icon=":material/undo:", on_click=undo, args=(dec["id"],))
            return
        if dec and dec["decision"] == "Hold":
            rem = state["reminders"].get(c["id"])
            st.warning(f"On hold since {dec['ts'][:10]}" + (f": {rem['days']} days, time to decide?" if rem else ""),
                       icon=":material/pause_circle:")
        if not show_buttons:
            return
        if not can("decide"):
            st.caption(":material/lock: Only the decision-maker can invite or pass. You can comment or give a "
                       "second opinion.")
            return

        decide_role = role
        with st.container(horizontal=True, vertical_alignment="center"):
            if len(res) > 1:
                decide_role = st.segmented_control(
                    "Decide for", list(res), default=c["better_fit"], key=f"{key}-role",
                    format_func=lambda x: state["role_names"].get(x, x)) or c["better_fit"]
            st.button("Invite to interview", key=f"{key}-adv", type="primary", icon=":material/event_available:",
                      on_click=act, args=(c["id"], decide_role, "Advance"))
            st.button("Pass", key=f"{key}-pass", icon=":material/close:",
                      on_click=act, args=(c["id"], decide_role, "Pass"))
            if not (dec and dec["decision"] == "Hold"):
                st.button("Hold for later", key=f"{key}-hold", icon=":material/pause:",
                          on_click=act, args=(c["id"], decide_role, "Hold"))


def evidence(c, obj, role):
    flags = {f["var"]: f for f in (c["evidence_flags"] or [])}
    la = obj.get("layer_a", {})
    n1_caps = la.get("N1", {}).get("code", 0) > 0 and la.get("P1", {}).get("code", 0) > 0
    found, missing, watch = [], [], []
    items = [(v, la[v], flags.get(v)) for v in ("P1", "P2", "P3", "P4", "P5") if v in la]
    items += [(k, v, flags.get(f"{role}.{k}")) for k, v in obj.get("layer_b", {}).get(role, {}).items()]
    for var, v, flag in items:
        code = v.get("code", 0)
        if code == 0:
            missing.append(label(var))
            continue
        strength = "✓" if code == 1 else "◐ partly"
        note = ""
        if var == "P1" and n1_caps:
            note = " :orange[(doesn't count: the logistics exposure is desk/API only)]"
        elif flag:
            note = f" :orange[({flag['flag']})]"
        found.append(f"- **{strength} {label(var)}**: “{v.get('evidence', '')}”{note}")
    for var in ("N1", "N2"):
        v = la.get(var, {})
        if v.get("code", 0) > 0:
            quote = f": “{v['evidence']}”" if v.get("evidence") else ""
            watch.append(f"- :material/warning: **{label(var)}**{quote}")
    st.markdown("**What the CV shows**")
    st.markdown("\n".join(found) if found else "_No supporting evidence found in the CV._")
    if watch:
        st.markdown("**Watch-outs**\n" + "\n".join(watch))
    if missing:
        st.caption("Not found in the CV: " + " · ".join(missing))


def _team_row(state, c, role, key):
    """Comments and second opinions, tucked into popovers so the card stays short."""
    cms = state["comments"].get(c["id"], [])
    n = len(cms)
    ops = state["reviews"].get(c["id"], [])
    with st.container(horizontal=True, vertical_alignment="center"):
        with st.popover(f"Comments ({n})", icon=":material/chat:"):
            for cm in cms:
                st.markdown(f"**{cm['author']}** · {fmt_time(cm['ts'])}\n\n{cm['body']}")
            if can("comment"):
                with st.form(f"{key}-cform", clear_on_submit=True, border=False):
                    body = st.text_area("Add a comment", placeholder="Use @username to mention someone",
                                        key=f"{key}-ctext")
                    if st.form_submit_button("Post", icon=":material/send:"):
                        try:
                            decisions.add_comment(c["id"], who(), body)
                            st.rerun()
                        except decisions.DecisionError as exc:
                            st.error(str(exc))
        done = [o for o in ops if o["status"] == "done"]
        waiting = [o for o in ops if o["status"] == "open"]
        label_ = f"Second opinions ({len(done)})" + (f" · {len(waiting)} waiting" if waiting else "")
        with st.popover(label_, icon=":material/group:"):
            for o in done:
                st.markdown(f"**{o['assignee']}** suggests **{ {'Advance': 'Invite'}.get(o['opinion'], o['opinion']) }**"
                            + (f": {o['note']}" if o["note"] else ""))
            for o in waiting:
                st.caption(f"Waiting for {o['assignee']} (asked by {o['requested_by']})")
            if can("comment"):
                others = [u for u in state["users"] if u["username"] != who()
                          and auth.can(u, "review")]
                if others:
                    pick = st.selectbox("Ask a teammate", [u["username"] for u in others], key=f"{key}-rv",
                                        format_func=lambda u: next(x["display_name"] for x in others
                                                                   if x["username"] == u))
                    if st.button("Ask for a second opinion", key=f"{key}-rvb", icon=":material/person_add:"):
                        decisions.request_review(c["id"], role, who(), pick)
                        st.toast("Asked. They'll see it under Second opinions.")
                        st.rerun()
