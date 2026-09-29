import streamlit as st

from shortlister import decisions
from ui_common import load_state, render_card, show_flash, who

state = load_state()
st.title("Second opinions")
st.caption("Teammates asked what you think. Your opinion is shown on the card; the decision-maker still decides.")
show_flash()

mine = decisions.reviews(assignee=who(), open_only=True)
if not mine:
    st.success("Nothing waiting for you.", icon=":material/done_all:")

OPTIONS = {"Advance": "Invite", "Hold": "Hold", "Pass": "Pass"}
for rv in mine:
    c = state["by_id"].get(rv["candidate_id"])
    if not c:
        continue
    st.markdown(f"**{rv['requested_by']}** asked for your view on **{c['id']}**")
    render_card(state, c, rv["role"], key=f"rv-{rv['id']}", show_buttons=False)
    with st.form(f"answer-{rv['id']}"):
        op = st.segmented_control("Your suggestion", list(OPTIONS), format_func=OPTIONS.get, key=f"op-{rv['id']}")
        note = st.text_input("Why (one line)", key=f"note-{rv['id']}")
        if st.form_submit_button("Send my opinion", type="primary"):
            try:
                decisions.answer_review(rv["id"], who(), op or "", note)
                st.rerun()
            except decisions.DecisionError as exc:
                st.error(str(exc))

asked = [r for r in decisions.reviews() if r["requested_by"] == who()]
if asked:
    st.subheader("Opinions you asked for")
    for r in asked:
        state_txt = (f"**{OPTIONS.get(r['opinion'], r['opinion'])}**" + (f": {r['note']}" if r["note"] else "")
                     if r["status"] == "done" else "waiting")
        st.markdown(f"- {r['candidate_id']} · {r['assignee']}: {state_txt}")
