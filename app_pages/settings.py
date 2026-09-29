import copy
import json

import pandas as pd
import streamlit as st

from shortlister import auth, config, emails, privacy, settings, vault, versions
from ui_common import can, flash, show_flash, who

if not can("admin"):
    st.error("Only an admin can change settings.")
    st.stop()

st.title("Settings")
show_flash()
s = settings.all_settings()
t_team, t_jobs, t_mail, t_priv, t_int = st.tabs(["Team", "Jobs & scoring", "Emails & automation", "Privacy & data",
                                                  "Integrations"])

# ---------------------------------------------------------------- team
with t_team:
    st.subheader("People")
    users = auth.users()
    st.dataframe(pd.DataFrame(users)[["username", "display_name", "role", "email", "active"]] if users else None,
                 hide_index=True)
    st.markdown("**Who may invite or pass candidates**")
    roles_pick = st.pills("Decision-makers", list(auth.ROLE_LABELS), selection_mode="multi",
                          default=s["decision_roles"], format_func=lambda r: auth.ROLE_LABELS[r].split(" (")[0],
                          label_visibility="collapsed")
    if st.button("Save decision-makers") and roles_pick:
        settings.put("decision_roles", roles_pick, who())
        flash("Saved.")
        st.rerun()
    st.caption("The build brief says the founder decides. Adding other roles is your call; every decision "
               "records who made it.")

    c1, c2 = st.columns(2)
    with c1, st.form("add-user", clear_on_submit=True):
        st.markdown("**Add a person**")
        name = st.text_input("Name")
        username = st.text_input("Username")
        email = st.text_input("Email")
        role = st.selectbox("Role", list(auth.ROLE_LABELS), format_func=auth.ROLE_LABELS.get, index=1)
        pw = st.text_input("Temporary password", type="password", help="10+ characters with a number. "
                           "Share it privately; they can be given a new one here later.")
        if st.form_submit_button("Add", type="primary"):
            try:
                auth.create_user(username, name, role, None if config.is_demo() else pw, email, by=who())
                flash(f"Added {username}.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with c2, st.form("edit-user"):
        st.markdown("**Change someone's access**")
        target = st.selectbox("Person", [u["username"] for u in users] or ["-"])
        new_role = st.selectbox("New role", ["(keep)"] + list(auth.ROLE_LABELS))
        active = st.segmented_control("Access", ["Active", "Deactivated"], default="Active")
        new_pw = st.text_input("New password (optional)", type="password")
        if st.form_submit_button("Save changes"):
            try:
                if target == who() and (active == "Deactivated" or new_role not in ("(keep)", "founder")):
                    raise ValueError("you can't remove your own admin access")
                auth.update_user(target, role=None if new_role == "(keep)" else new_role,
                                 active=active == "Active", by=who())
                if new_pw:
                    auth.set_password(target, new_pw, who())
                flash("Saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

# ---------------------------------------------------------------- jobs & scoring
with t_jobs:
    params = versions.active()
    st.caption(f"Active settings version: **v{params['_version']}**. Every score records the version it used. "
               "Changing weights here never touches past decisions; use *Recalculate* to re-band existing CVs.")
    draft = copy.deepcopy({k: v for k, v in params.items() if k != "_version"})
    names = versions.role_names(params)

    st.subheader("Roles")
    for code in versions.role_codes(params):
        lb = draft["layer_b"][code]
        meta = draft["_roles"].setdefault(code, {"name": code, "jd_text": "", "definitions": {}})
        with st.expander(f"{meta['name']} ({code})", icon=":material/work:"):
            meta["name"] = st.text_input("Role name", meta["name"], key=f"rn-{code}")
            lo, hi = st.slider("PM years the JD asks for", 0, 20, tuple(lb["gate_years_pm"]), key=f"gy-{code}")
            lb["gate_years_pm"] = [lo, hi]
            st.markdown("**Role-specific criteria (weights must add up to 100)**")
            for k in list(lb["weights"]):
                a, b = st.columns([1, 4])
                lb["weights"][k] = a.number_input(k, 0, 100, int(lb["weights"][k]), key=f"w-{code}-{k}")
                meta["definitions"][k] = b.text_input("Definition", meta["definitions"].get(k, ""),
                                                      key=f"df-{code}-{k}", label_visibility="collapsed")
            st.caption(f"Total: {sum(lb['weights'].values())}")
            meta["jd_text"] = st.text_area("Job description", meta.get("jd_text", ""), height=200, key=f"jd-{code}")

    with st.expander("Add a new role", icon=":material/add:"):
        nc = st.text_input("Code (short, capitals)", placeholder="e.g. OPSM", key="new-code")
        nn = st.text_input("Role name", placeholder="e.g. Operations Manager", key="new-name")
        ny = st.slider("PM years the JD asks for", 0, 20, (2, 5), key="new-years")
        crit = st.text_area("Criteria, one per line as  key | weight | definition",
                            placeholder="ops_leadership | 40 | led a team of 10+ in warehouse or port operations\n"
                                        "process_design | 35 | designed an operating process others adopted\n"
                                        "early_stage | 25 | worked in an early-stage company", key="new-crit")
        njd = st.text_area("Job description", key="new-jd")
        if nc and nn and crit.strip():
            weights, defs = {}, {}
            for line in crit.strip().splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 3 and parts[1].isdigit():
                    key = parts[0].lower().replace(" ", "_")
                    weights[key], defs[key] = int(parts[1]), parts[2]
            draft["layer_b"][nc.strip().upper()] = {"weights": weights, "gate_years_pm": list(ny)}
            draft["_roles"][nc.strip().upper()] = {"name": nn.strip(), "jd_text": njd, "definitions": defs}

    st.subheader("Pattern weights and thresholds")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Layer A points**")
        from shortlister import scoring

        st.caption("Fixed in code from the build brief (derived from past hires): " +
                   ", ".join(f"{k} {v:g}" for k, v in scoring.LAYER_A_POINTS.items()))
    with c2:
        wa = st.slider("Weight of the Kargo pattern (Layer A)", 0.0, 1.0, float(draft["blend"]["layer_a_pattern"]),
                       0.05)
        draft["blend"] = {"layer_a_pattern": round(wa, 2), "layer_b_role": round(1 - wa, 2)}
    with c3:
        strong = st.number_input("Strong from", 0, 100, int(draft["bands"]["strong"]))
        border = st.number_input("Borderline from", 0, 100, int(draft["bands"]["borderline"]))
        draft["bands"] = {"strong": strong, "borderline": border}
        draft["rules"]["role_rescue_B"] = st.number_input("Role rescue when role fit is at least", 0, 100,
                                                          int(draft["rules"]["role_rescue_B"]))

    changed = json.dumps(draft, sort_keys=True) != json.dumps({k: v for k, v in params.items() if k != "_version"},
                                                               sort_keys=True)
    errs = versions.validate(draft)
    for e in errs:
        st.error(e, icon=":material/error:")
    note = st.text_input("What changed and why (required)", key="ver-note")
    with st.container(horizontal=True):
        if st.button("Publish as a new version", type="primary", disabled=not changed or bool(errs) or not note):
            v = versions.publish(draft, note, who())
            flash(f"Published v{v}. New CVs use it now. Use Recalculate to re-band existing CVs.")
            st.rerun()
        if st.button("Recalculate existing CVs with the active version", icon=":material/calculate:",
                     help="No AI calls: re-bands from the stored evidence codes."):
            out = versions.recalculate_all(who())
            flash(f"Re-banded {out['recalculated']} CV(s)."
                  + (f" {len(out['skipped_roles'])} role score(s) skipped: those CVs were never classified for a "
                     "new role (re-upload to score them)." if out["skipped_roles"] else ""))
            st.rerun()
    st.caption("Before trusting new weights, re-run the blind check on the Calibrate page.")
    hist = versions.history()
    st.dataframe(pd.DataFrame(hist), hide_index=True)
    back = st.selectbox("Switch the active version", [h["version"] for h in hist],
                        format_func=lambda v: f"v{v}" + (" (active)" if v == params["_version"] else ""))
    if back != params["_version"] and st.button(f"Make v{back} active"):
        versions.activate(back, who())
        st.rerun()

# ---------------------------------------------------------------- emails & automation
with t_mail:
    st.subheader("Automation")
    with st.form("automation"):
        undo = st.number_input("Undo window before a decision email goes out (minutes)", 0, 120, int(s["undo_minutes"]))
        fu = st.number_input("Remind invited candidates who haven't booked after (days, 0 = off)", 0, 30,
                             int(s["followup_days"]))
        ir = st.number_input("Interview reminder to the candidate, hours before (0 = off)", 0, 72,
                             int(s["interview_reminder_hours"]))
        dg = st.toggle("Daily digest to the team", bool(s["digest_enabled"]))
        dh = st.slider("Digest time (IST)", 6, 12, int(s["digest_hour"]), format="%d:00")
        rec = st.text_input("Digest recipients (comma separated; empty = founders and hiring managers)",
                            ", ".join(s["digest_recipients"]))
        sl = st.toggle("Also post the digest to Slack (needs SLACK_WEBHOOK_URL)", bool(s["slack_enabled"]))
        hr = st.toggle("Email decision-makers about Holds older than 7 days", bool(s["hold_reminder_email"]))
        wa = st.toggle("WhatsApp invites and reminders to candidates who opted in (needs Twilio)",
                       bool(s["whatsapp_enabled"]))
        st.divider()
        ack = st.toggle("Send an automatic 'we received your application' email", bool(s["ack_enabled"]))
        st.caption(":orange[This email reaches the candidate before anyone decides, which the build brief's "
                   "overriding rule does not allow. Only switch it on if you've chosen to change that rule.]")
        if st.form_submit_button("Save", type="primary"):
            for k, v in {"undo_minutes": undo, "followup_days": fu, "interview_reminder_hours": ir,
                         "digest_enabled": dg, "digest_hour": dh, "slack_enabled": sl, "hold_reminder_email": hr,
                         "whatsapp_enabled": wa, "ack_enabled": ack,
                         "digest_recipients": [x.strip() for x in rec.split(",") if x.strip()]}.items():
                if v != s[k]:
                    settings.put(k, v, who())
            flash("Automation settings saved.")
            st.rerun()
    if st.button("Send a digest now", icon=":material/outgoing_mail:"):
        from datetime import datetime, timezone

        from shortlister import automation

        automation.daily_digest(datetime.now(timezone.utc), force=True)
        st.toast("Digest sent" + (" (practice mode: see outbox)" if config.dry_run() else ""))

    st.subheader("Email templates")
    st.caption("Placeholders: " + ", ".join("{" + p + "}" for p in sorted(emails.PLACEHOLDERS)) +
               ". Candidate emails can't mention scores, reasons or offers; those are refused on save.")
    kinds = [k for k in emails.DEFAULT_TEMPLATES]
    kind = st.selectbox("Template", kinds, format_func=lambda k: k.replace("_", " ").capitalize())
    role_opts = ["*"] + versions.role_codes(versions.active())
    trole = st.segmented_control("For role", role_opts, default="*",
                                 format_func=lambda r: "All roles" if r == "*" else r) or "*"
    t = emails.template_for(kind, None if trole == "*" else trole)
    subj = st.text_input("Subject", t["subject"], key=f"ts-{kind}-{trole}")
    body = st.text_area("Body", t["body"], height=260, key=f"tb-{kind}-{trole}")
    problems = emails.validate_template(subj, body)
    for p in problems:
        st.error(p)
    with st.container(horizontal=True):
        if st.button("Save template", type="primary", disabled=bool(problems)):
            emails.save_template(kind, trole, subj, body, who())
            flash("Template saved.")
            st.rerun()
        if st.button("Reset to default"):
            emails.reset_template(kind, trole, who())
            st.rerun()
    with st.expander("Preview", icon=":material/visibility:"):
        try:
            ps, pb = emails.render(kind, None if trole == "*" else trole, {"name": "Asha Kulkarni"}, "KG-0000")
            st.markdown(f"**{ps}**")
            st.text(pb)
        except (KeyError, ValueError) as exc:
            st.error(f"Can't preview: {exc}")

# ---------------------------------------------------------------- privacy & data
with t_priv:
    st.subheader("Retention and notice")
    with st.form("privacy"):
        days = st.number_input("Delete application data this many days after a final decision (0 = never)", 0,
                               3650, int(s["retention_days"]))
        contact = st.text_input("Privacy contact email", s["privacy_contact"])
        notice = st.text_area("Privacy notice (shown on the careers form)", s["privacy_notice"], height=200)
        if st.form_submit_button("Save", type="primary"):
            settings.put("retention_days", int(days), who())
            settings.put("privacy_contact", contact, who())
            settings.put("privacy_notice", notice, who())
            flash("Saved.")
            st.rerun()
    st.caption("Preview: " + settings.privacy_notice()[:300] + "…")

    st.subheader("Requests from candidates")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**Export someone's data**")
        cid = st.text_input("Candidate ID", key="exp-id", placeholder="KG-0001")
        if cid:
            try:
                data = json.dumps(privacy.export(cid.strip().upper()), indent=2, ensure_ascii=False, default=str)
                st.download_button("Download", data, f"{cid}-data.json", icon=":material/download:")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
    with c2, st.container(border=True):
        st.markdown("**Erase someone's data**")
        eid = st.text_input("Candidate ID", key="er-id", placeholder="KG-0001")
        sure = st.checkbox("I understand this can't be undone", key="er-sure")
        if st.button("Erase", type="primary", disabled=not (eid and sure), icon=":material/delete_forever:"):
            try:
                privacy.erase(eid.strip().upper(), by=who())
                flash(f"Erased {eid}. The anonymous decision record is kept for the audit trail.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.subheader("Backups and encryption")
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button("Create a backup now", icon=":material/backup:"):
            p = privacy.backup()
            st.session_state["last_backup"] = str(p)
        if st.session_state.get("last_backup"):
            st.caption(f"Saved: `{st.session_state['last_backup']}`")
    if vault.is_encrypted():
        st.success("The identity vault is encrypted.", icon=":material/lock:")
    elif config.env("VAULT_KEY"):
        if st.button("Encrypt the identity vault now", icon=":material/lock:"):
            vault.encrypt_existing()
            st.rerun()
    else:
        st.warning("The identity vault (names and emails) is not encrypted. Run `python -m shortlister keygen`, add "
                   "the key to `.env` as VAULT_KEY, restart, then come back here.", icon=":material/lock_open:")

# ---------------------------------------------------------------- integrations
with t_int:
    st.caption("Only whether each is set is shown here; values are never displayed.")
    checks = [
        ("Anthropic API (scoring)", "ANTHROPIC_API_KEY", "Scores CVs."),
        ("Neon database", "DATABASE_URL", "Shared database for the team (otherwise a local file)."),
        ("Resend (email)", "RESEND_API_KEY", "Sends email once DRY_RUN=false."),
        ("Resend webhooks", "RESEND_WEBHOOK_SECRET", "Delivery and bounce tracking."),
        ("Scheduling link", "SCHEDULING_LINK", "Booking link in invites (or SCHEDULING_LINK_PM / _SPM)."),
        ("Cal.com webhooks", "CALCOM_WEBHOOK_SECRET", "Marks candidates as booked automatically."),
        ("Calendly webhooks", "CALENDLY_WEBHOOK_SECRET", "Same, for Calendly."),
        ("WhatsApp (Twilio)", "TWILIO_AUTH_TOKEN", "WhatsApp invites and reminders."),
        ("Slack digest", "SLACK_WEBHOOK_URL", "Posts the daily digest."),
        ("Hiring inbox", "HIRING_IMAP_HOST", "Pulls CV attachments from a mailbox."),
        ("Vault encryption", "VAULT_KEY", "Encrypts names and emails at rest."),
        ("Public address", "PUBLIC_BASE_URL", "Where the careers form and webhooks are reachable."),
    ]
    for label_, var, what in checks:
        ok = bool(config.env(var) or (var == "SCHEDULING_LINK" and any(config.env(f"SCHEDULING_LINK_{r}")
                                                                        for r in versions.role_codes(versions.active()))))
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge("set" if ok else "not set", color="green" if ok else "gray",
                     icon=":material/check:" if ok else ":material/remove:")
            st.markdown(f"**{label_}**: {what} `{var}`")
    st.caption(f"Email mode: {'demo (never sends)' if config.is_demo() else 'practice (DRY_RUN)' if config.dry_run() else 'live'}"
               + (f", test recipient set" if config.test_recipient() else ""))
