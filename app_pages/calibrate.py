import pandas as pd
import streamlit as st

from shortlister import analytics
from shortlister.pipeline import primary_role
from ui_common import load_state, who

state = load_state()
names = state["role_names"]
st.title("Calibrate")
st.write("The weights come from only 8 past hires, so check them against your own judgement. Rate **10 CVs** "
         "without seeing the system's answer, then compare. If you disagree on more than 2, revisit the weights "
         "before clearing a full batch.")

summary = analytics.calibration_summary(who())
queue = analytics.calibration_queue(who(), n=10)
st.progress(min(summary["rated"], 10) / 10, text=f"{summary['rated']} of 10 rated")


def rate(cid, role, rating):
    analytics.rate(cid, who(), role, rating)


if queue:
    c = queue[0]
    role = primary_role(c)
    with st.container(border=True):
        st.markdown(f"#### {c['id']} · {names.get(role, role)}")
        st.caption("The CV as the AI saw it, with identity removed. The system's rating is hidden.")
        st.text_area("CV", c["redacted_text"], height=380, disabled=True, label_visibility="collapsed")
        st.markdown("**Your rating**")
        with st.container(horizontal=True):
            for band, icon in (("Strong", ":material/star:"), ("Borderline", ":material/balance:"),
                               ("Not a fit", ":material/remove_circle_outline:")):
                st.button(band, key=f"cal-{c['id']}-{band}", icon=icon, on_click=rate, args=(c["id"], role, band),
                          type="primary" if band == "Strong" else "secondary")
elif summary["rated"] == 0:
    st.info("No CVs to rate yet. Add some first.", icon=":material/inbox:")

if summary["rated"]:
    st.subheader("How you compare")
    if summary["verdict"]:
        (st.success if "Good match" in summary["verdict"] else st.warning)(summary["verdict"], icon=":material/tune:")
    st.metric("Agreement with the system", f"{summary['agreement_%']}%", border=True)
    table = pd.DataFrame(summary["table"]).T
    table.index.name = "You said"
    table.columns.name = "System said"
    st.dataframe(table)
    if summary["disagreements"]:
        st.markdown("**Where you disagreed**")
        for d in summary["disagreements"]:
            st.markdown(f"- {d['candidate_id']}: you said **{d['rating']}**, the system said **{d['system_band']}**")

team = analytics.calibration_summary()
if team["rated"] > summary["rated"]:
    st.caption(f"Whole team: {team['rated']} ratings, {team['agreement_%']}% agreement.")
