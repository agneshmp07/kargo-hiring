import altair as alt
import pandas as pd
import streamlit as st

from shortlister import analytics
from ui_common import load_state

state = load_state()
names = state["role_names"]
st.title("Analytics")

if not state["cands"]:
    st.info("Nothing to show yet.", icon=":material/insights:")
    st.stop()

with st.container(horizontal=True, vertical_alignment="center"):
    role = st.segmented_control("Role", ["All roles", *state["roles"]], default="All roles",
                                format_func=lambda r: names.get(r, r), label_visibility="collapsed") or "All roles"
    if "report_pdf" in st.session_state:
        st.download_button("Download board report", st.session_state["report_pdf"], "kargo-hiring-report.pdf",
                           mime="application/pdf", icon=":material/picture_as_pdf:", type="primary")
    elif st.button("Make board report (PDF)", icon=":material/picture_as_pdf:"):
        st.session_state["report_pdf"] = analytics.report_pdf()
        st.rerun()
    st.download_button("Training data (CSV)", analytics.training_export_csv(), "kargo-training-data.csv",
                       icon=":material/download:",
                       help="AI codes plus real outcomes per candidate, for re-deriving the weights from more than 8 hires.")

t = analytics.time_to_decision()
a = analytics.agreement()
s = analytics.spend()
with st.container(horizontal=True):
    st.metric("Median days to a decision", t["median_days"] if t["median_days"] is not None else "-", border=True)
    st.metric("Still waiting", t["waiting"], border=True)
    st.metric("Agree with the recommendation", f"{a['agreement_%']}%" if a["agreement_%"] is not None else "-",
              border=True, help="Invite on Strong/Borderline, or Pass on Not a fit")
    st.metric("AI spend", f"${s['total_usd']:.2f}", border=True,
              help=f"Per CV: ${s['per_cv_usd']:.3f}" if s["per_cv_usd"] else "No AI calls yet")

st.subheader("Funnel")
f = pd.DataFrame(analytics.funnel(None if role == "All roles" else role), columns=["Stage", "Candidates"])
chart = alt.Chart(f).mark_bar(cornerRadiusEnd=3).encode(
    x=alt.X("Candidates:Q", title=None), y=alt.Y("Stage:N", sort=None, title=None),
    tooltip=["Stage", "Candidates"]).properties(height=220)
st.altair_chart(chart)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Decisions vs recommendation")
    st.dataframe(pd.DataFrame(a["table"]).T.rename(columns={"Advance": "Invited"}))
with c2:
    st.subheader("Interview outcomes by band")
    st.caption("As outcomes come in, this shows whether the bands predict success.")
    st.dataframe(pd.DataFrame(analytics.outcomes_by_band()).T.rename(
        columns={"selected": "Selected", "not_selected": "Not selected", "withdrawn": "Withdrew", "open": "In progress"}))

st.subheader("Where candidates come from")
sq = pd.DataFrame(analytics.source_quality())
if not sq.empty:
    st.dataframe(sq[["source", "cvs", "recommended_%", "invited_%", "selected"]].rename(columns={
        "source": "Source", "cvs": "CVs", "recommended_%": "Recommended %", "invited_%": "Invited %",
        "selected": "Selected"}), hide_index=True)

st.subheader("Fairness check")
st.caption("Recommendation rates by city. A group is flagged when its rate is under 80% of the best group's "
           "(the four-fifths rule), with at least 5 CVs. Gender, age and similar are never collected, so they can't "
           "be checked here. This check never changes any score.")
fr = pd.DataFrame(analytics.fairness_by_city())
if not fr.empty:
    flagged = fr[fr["flag"]]
    if len(flagged):
        st.warning("Worth a look: " + ", ".join(flagged["city"]), icon=":material/balance:")
    else:
        st.success("No group flagged.", icon=":material/balance:")
    st.dataframe(fr[["city", "cvs", "recommended_rate", "invited", "impact_ratio"]].rename(columns={
        "city": "City", "cvs": "CVs", "recommended_rate": "Recommended %", "invited": "Invited",
        "impact_ratio": "Ratio to best"}), hide_index=True)

if s["batches"]:
    st.subheader("AI spend by batch")
    st.dataframe(pd.DataFrame(s["batches"]), hide_index=True)
