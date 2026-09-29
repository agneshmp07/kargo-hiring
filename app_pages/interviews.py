from datetime import datetime, time, timedelta, timezone

import streamlit as st

from shortlister import decisions
from ui_common import can, display_name, fmt_time, load_state, show_flash, who

state = load_state()
names = state["role_names"]
IST = timezone(timedelta(hours=5, minutes=30))

st.title("Interviews")
st.caption("Everyone you invited, from booking to outcome. Bookings made through Cal.com or Calendly update "
           "here automatically; you can also set them by hand.")
show_flash()

stages = state["stages"]
if not stages:
    st.info("Nobody invited yet. Invite candidates from the Shortlist.", icon=":material/event:")
    st.stop()

RATING_AREAS = {"P1": "Ground-level ops understanding", "P2": "Builds what's needed, unasked",
                "P3": "Owns decisions", "P4": "Handles crises", "P5": "Learns from failure"}
REC_LABEL = {"strong_yes": "Strong yes", "yes": "Yes", "no": "No", "strong_no": "Strong no"}
columns = [("invited", "Waiting to book"), ("scheduled", "Booked"), ("interviewed", "Interviewed")]
open_counts = {k: sum(1 for s in stages.values() if s["stage"] == k) for k, _ in columns}
outcomes = [s for s in stages.values() if s["stage"] in decisions.OUTCOME_STAGES]

with st.container(horizontal=True):
    for k, lbl in columns:
        st.metric(lbl, open_counts[k], border=True)
    st.metric("Outcome recorded", len(outcomes), border=True)

view = st.segmented_control("Show", [lbl for _, lbl in columns] + ["Outcomes"], default="Booked",
                            label_visibility="collapsed") or "Booked"
key_for = {lbl: k for k, lbl in columns}
rows = ([s for s in stages.values() if s["stage"] == key_for[view]] if view in key_for else outcomes)
rows.sort(key=lambda s: s.get("scheduled_for") or s["updated_at"])

if not rows:
    st.info("Nobody here right now.", icon=":material/inbox:")

for s in rows:
    c = state["by_id"].get(s["candidate_id"])
    if not c:
        continue
    obj = c["llm_json"] or {}
    cards = decisions.scorecards(c["id"])
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"#### {display_name(state, c)}")
            st.badge(names.get(s["role"], s["role"]), icon=":material/work:", color="blue")
            st.badge(decisions.STAGES[s["stage"]], icon=":material/flag:",
                     color={"selected": "green", "not_selected": "gray", "withdrawn": "gray"}.get(s["stage"], "orange"))
            if s["scheduled_for"]:
                st.badge(fmt_time(s["scheduled_for"]) + " IST", icon=":material/schedule:", color="violet")
            if cards:
                recs = [REC_LABEL[x["recommendation"]] for x in cards]
                st.badge(f"{len(cards)} scorecard(s): {', '.join(recs)}", icon=":material/rate_review:", color="green")
        if obj.get("rationale"):
            st.caption(obj["rationale"])

        left, right = st.columns([3, 2], gap="large")
        with left:
            st.markdown("**Questions to ask**")
            st.markdown("\n".join(f"{i}. {p}" for i, p in enumerate(obj.get("probes", []), 1)))
            for sc in cards:
                ratings = " · ".join(f"{k} {v}/5" for k, v in sc["ratings"].items())
                st.markdown(f"**{sc['interviewer']}**: {REC_LABEL[sc['recommendation']]} · {ratings}"
                            + (f"  \n_{sc['notes']}_" if sc["notes"] else ""))
        with right:
            if s["stage"] in decisions.OUTCOME_STAGES:
                st.success(f"{decisions.STAGES[s['stage']]} · {fmt_time(s['updated_at'])}", icon=":material/task_alt:")
                continue
            if can("schedule"):
                with st.popover("Set interview time", icon=":material/edit_calendar:"):
                    d = st.date_input("Date", value=datetime.now(IST).date() + timedelta(days=1), key=f"d-{c['id']}")
                    t = st.time_input("Time (IST)", value=time(11, 0), key=f"t-{c['id']}")
                    if st.button("Save booking", key=f"book-{c['id']}", type="primary"):
                        when = datetime.combine(d, t, IST).astimezone(timezone.utc).isoformat(timespec="minutes")
                        decisions.set_stage(c["id"], "scheduled", who(), scheduled_for=when)
                        st.rerun()
                if s["stage"] == "scheduled" and st.button("Mark as interviewed", key=f"iv-{c['id']}",
                                                           icon=":material/done:"):
                    decisions.set_stage(c["id"], "interviewed", who())
                    st.rerun()
            if can("scorecard"):
                with st.popover("Add my scorecard", icon=":material/rate_review:"):
                    with st.form(f"sc-{c['id']}", border=False):
                        ratings = {k: st.slider(v, 1, 5, 3, key=f"r-{c['id']}-{k}") for k, v in RATING_AREAS.items()}
                        rec = st.segmented_control("Recommendation", list(REC_LABEL), format_func=REC_LABEL.get,
                                                   key=f"rec-{c['id']}")
                        notes = st.text_area("Notes", key=f"n-{c['id']}")
                        if st.form_submit_button("Save scorecard", type="primary"):
                            try:
                                decisions.add_scorecard(c["id"], who(), ratings, rec or "", notes)
                                st.rerun()
                            except decisions.DecisionError as exc:
                                st.error(str(exc))
            if can("decide") and s["stage"] in ("scheduled", "interviewed"):
                st.markdown("**Outcome**")
                with st.container(horizontal=True):
                    if st.button("Selected", key=f"sel-{c['id']}", type="primary", icon=":material/thumb_up:",
                                 help="No email is sent. Offers are handled outside this system."):
                        decisions.set_stage(c["id"], "selected", who())
                        st.rerun()
                    if st.button("Not selected", key=f"ns-{c['id']}", icon=":material/thumb_down:",
                                 help="Sends a kind post-interview email after the undo window."):
                        decisions.set_stage(c["id"], "not_selected", who())
                        st.rerun()
                    if st.button("Withdrew", key=f"wd-{c['id']}", icon=":material/logout:"):
                        decisions.set_stage(c["id"], "withdrawn", who())
                        st.rerun()
