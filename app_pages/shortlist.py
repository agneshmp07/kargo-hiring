import streamlit as st

from shortlister import config, decisions
from shortlister.pipeline import primary_role
from ui_common import BAND_STYLE, can, flash, is_open, load_state, render_card, show_flash, sort_key, who

state = load_state()
cands, roles, names = state["cands"], state["roles"], state["role_names"]

st.title("Shortlist")
st.caption("The system recommends. You decide. Nothing is sent to a candidate until you click, and decision "
           "emails wait a few minutes so you can undo.")
show_flash()

if not cands:
    st.info("No candidates yet. Go to **Add CVs** to upload some.", icon=":material/inbox:")
    st.stop()


@st.dialog("Pass all 'Not a fit' candidates?")
def confirm_bulk(role, ids):
    st.write(f"This passes **{len(ids)}** {names[role]} candidate(s) and sends each a polite rejection email"
             + (" (practice mode: saved to the outbox)." if config.dry_run() else "."))
    st.caption("Left out: CVs in an open random check, and any you flagged as missed. " + ", ".join(ids))
    if st.button("Yes, pass them", type="primary", icon=":material/done_all:"):
        n = len(decisions.bulk_pass(role, by=who()))
        flash(f"Passed {n} candidate(s). You can undo each one for a few minutes.")
        st.rerun()


def spot_verdict(spot_id, v):
    decisions.spot_check_verdict(spot_id, v, by=who())
    st.toast("Thanks, your check is logged", icon=":material/check_circle:")


# Decisions whose email is still in the undo window: keep them visible so a misclick is easy to fix.
recent = [d for cid, d in state["latest"].items()
          if d and d["decision"] in ("Advance", "Pass") and state["undoable"].get(cid)]
if recent and can("decide"):
    from ui_common import EMAIL_STATUS, display_name, fmt_time, undo

    with st.container(border=True):
        st.markdown("**:material/undo: Undo a recent decision** (emails wait before sending)")
        for d in sorted(recent, key=lambda d: d["id"], reverse=True):
            email = state["email_by_decision"].get(d["id"])
            when = fmt_time(email["send_after"]) if email else "-"
            what = "Invited" if d["decision"] == "Advance" else "Passed"
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"{what} **{display_name(state, state['by_id'][d['candidate_id']])}** · email goes out "
                            f"at {when}")
                st.button("Undo", key=f"recent-undo-{d['id']}", icon=":material/undo:", on_click=undo,
                          args=(d["id"],))

pending_spots = [s for s in state["spots"] if s["verdict"] is None]
holds = [c for c in cands if (state["latest"].get(c["id"]) or {}).get("decision") == "Hold"]
backlog = [c for c in cands if c["backlog"] and is_open(state, c["id"])]
groups = {r: sorted([c for c in cands if primary_role(c) == r], key=lambda c: sort_key(c, r)) for r in roles}

open_c = [c for c in cands if is_open(state, c["id"])]
band_of = lambda c: c["results_json"][primary_role(c)]["band"]  # noqa: E731
with st.container(horizontal=True):
    st.metric("Waiting for a decision", len(open_c), border=True)
    st.metric("Strong", sum(band_of(c) == "Strong" for c in open_c), border=True)
    st.metric("Borderline", sum(band_of(c) == "Borderline" for c in open_c), border=True)
    st.metric("Not a fit", sum(band_of(c) == "Not a fit" for c in open_c), border=True)
    st.metric("Random checks", len(pending_spots), border=True)

labels = [f"{names[r]} ({sum(is_open(state, c['id']) for c in groups[r])})" for r in roles]
labels += [f"On hold ({len(holds)})", f"Random check ({len(pending_spots)})", f"Backlog ({len(backlog)})"]
tabs = st.tabs(labels)

for tab, role in zip(tabs, roles):
    with tab:
        cands_r = groups[role]
        if not cands_r:
            st.info("No candidates for this role yet.", icon=":material/inbox:")
            continue
        with st.container(horizontal=True, vertical_alignment="center"):
            show = st.segmented_control("Show", ["Waiting for a decision", "Everyone"], default="Waiting for a decision",
                                        key=f"show-{role}", label_visibility="collapsed") or "Waiting for a decision"
            search = st.text_input("Find by ID", key=f"find-{role}", placeholder="Find by ID, e.g. KG-0004",
                                   label_visibility="collapsed")
            if can("decide"):
                bulk_ids = decisions.bulk_pass_candidates(role)
                if st.button(f"Pass all 'Not a fit' ({len(bulk_ids)})", key=f"bulk-{role}",
                             icon=":material/done_all:", disabled=not bulk_ids):
                    confirm_bulk(role, bulk_ids)
        st.caption("**Invite** sends an interview email with a booking link · **Pass** sends a polite rejection · "
                   "**Hold** sends nothing and reminds you in 7 days.")
        visible = [c for c in cands_r if (show == "Everyone" or is_open(state, c["id"]))
                   and (not search or search.strip().upper() in c["id"])]
        if not visible:
            st.success("All done here. Every candidate in this role has a decision.", icon=":material/celebration:")
        current = None
        for c in visible:
            band = c["results_json"][role]["band"]
            if band != current:
                current = band
                n = sum(1 for x in visible if x["results_json"][role]["band"] == band)
                st.subheader(f"{BAND_STYLE[band][1]} {band} ({n})")
            render_card(state, c, role, key=f"{role}-{c['id']}")

with tabs[len(roles)]:
    st.write("Candidates you put on hold. They'll show a reminder after 7 days.")
    for c in sorted(holds, key=lambda c: state["latest"][c["id"]]["ts"]):
        role = state["latest"][c["id"]]["role"]
        render_card(state, c, role, key=f"hold-{c['id']}")
    if not holds:
        st.info("Nothing on hold.", icon=":material/pause_circle:")

with tabs[len(roles) + 1]:
    st.write("Here are random CVs the system marked 'Not a fit'. Take a quick look. If one deserves a second "
             "chance, flag it: it's kept out of the bulk Pass so you can decide it yourself.")
    if not pending_spots:
        st.success("Nothing to check right now.", icon=":material/done_all:")
    for s in pending_spots:
        c = state["by_id"].get(s["candidate_id"])
        if not c:
            continue
        with st.container(horizontal=True):
            st.button("Agree: not a fit", key=f"spot-ok-{s['id']}", icon=":material/thumb_up:",
                      on_click=spot_verdict, args=(s["id"], "correct"))
            st.button("We missed this one", key=f"spot-miss-{s['id']}", icon=":material/flag:", type="primary",
                      on_click=spot_verdict, args=(s["id"], "missed"))
        render_card(state, c, s["role"], key=f"spot-{s['id']}", show_buttons=False)
    done = [s for s in state["spots"] if s["verdict"]]
    if done:
        st.caption("Past checks: " + ", ".join(
            f"{s['candidate_id']} ({'missed' if s['verdict'] == 'missed' else 'agreed'})" for s in done))

with tabs[len(roles) + 2]:
    st.write("Older applications that were opened but never answered. Clear them with the same three buttons.")
    for c in sorted(backlog, key=lambda c: sort_key(c, primary_role(c))):
        render_card(state, c, primary_role(c), key=f"backlog-{c['id']}")
    if not backlog:
        st.info("No backlog. To load one: `python -m shortlister backlog --list opened.txt`", icon=":material/inbox:")
