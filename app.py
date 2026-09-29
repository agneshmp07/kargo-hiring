"""Kargo hiring app. Run with:  python -m shortlister ui   (or: python -m shortlister demo)"""
from __future__ import annotations

import streamlit as st

from shortlister import auth, config, emails, store
from ui_common import can, user

st.set_page_config(page_title="Kargo hiring", page_icon=":material/fact_check:", layout="wide")


# ---------------------------------------------------------------- sign-in

def sign_in_screen():
    st.title(":material/fact_check: Kargo hiring")
    if config.is_demo():
        auth.seed_demo_users()
        st.info("**Demo.** Fictional candidates; nothing is ever sent. Pick someone to see the app as them.",
                icon=":material/science:")
        for u in auth.users(active_only=True):
            with st.container(border=True, horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{u['display_name']}**  \n{auth.ROLE_LABELS[u['role']]}")
                if st.button("Continue as " + u["display_name"].split()[0], key=f"as-{u['username']}",
                             type="primary" if u["role"] == "founder" else "secondary"):
                    st.session_state["user"] = {k: u[k] for k in ("username", "display_name", "role", "email")}
                    st.rerun()
        return

    if not auth.has_users():
        st.subheader("Set up the first account")
        st.write("This is the founder account: it can decide, and it manages the team and settings.")
        with st.form("setup"):
            name = st.text_input("Your name")
            username = st.text_input("Username", help="Lower-case, e.g. arjun")
            email = st.text_input("Email (for the daily digest)")
            pw = st.text_input("Password", type="password", help="At least 10 characters, with a number")
            pw2 = st.text_input("Repeat password", type="password")
            if st.form_submit_button("Create account", type="primary"):
                if pw != pw2:
                    st.error("The passwords don't match.")
                else:
                    try:
                        auth.create_user(username, name, "founder", pw, email, by="setup")
                        st.session_state["user"] = auth.authenticate(username, pw)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        return

    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.form("login"):
        st.subheader("Sign in")
        username = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            u = auth.authenticate(username, pw)
            if u:
                st.session_state["user"] = u
                st.rerun()
            st.error("That username and password don't match.")


if not user():
    sign_in_screen()
    st.stop()

# Anything whose undo window has passed goes out now (the worker does this too).
try:
    emails.send_due()
except Exception as exc:  # noqa: BLE001 - never block the UI on delivery problems
    st.toast(f"Email sending problem: {exc}", icon=":material/error:")

# ---------------------------------------------------------------- sidebar

u = user()
with st.sidebar:
    st.markdown(f"**{u['display_name']}**  \n{auth.ROLE_LABELS.get(u['role'], u['role'])}")
    if config.is_demo():
        st.info("**Demo mode.** Fictional data. Nothing is ever sent.", icon=":material/science:")
    elif config.dry_run():
        st.success("**Practice mode.** Emails are saved to the outbox, not sent.", icon=":material/science:")
    else:
        where = "to the test address only" if config.test_recipient() else "to candidates"
        st.error(f"**Live.** Emails are sent {where}.", icon=":material/send:")
    if st.button("Sign out" if not config.is_demo() else "Switch person", icon=":material/logout:"):
        st.session_state.pop("user", None)
        st.rerun()
    st.caption(f"AI: {config.model() if config.api_ready() else 'no key (demo keyword stand-in)' if config.is_demo() else 'no key set'}"
               f" · database: {store.backend()}")

# ---------------------------------------------------------------- navigation

pages = {"Hiring": [st.Page("app_pages/shortlist.py", title="Shortlist", icon=":material/fact_check:", default=True)]}
if can("upload"):
    pages["Hiring"].append(st.Page("app_pages/add_cvs.py", title="Add CVs", icon=":material/upload_file:"))
pages["Hiring"].append(st.Page("app_pages/interviews.py", title="Interviews", icon=":material/event:"))
if can("review"):
    pages["Hiring"].append(st.Page("app_pages/reviews.py", title="Second opinions", icon=":material/group:"))
insights = []
if can("calibrate"):
    insights.append(st.Page("app_pages/calibrate.py", title="Calibrate", icon=":material/tune:"))
insights += [st.Page("app_pages/analytics.py", title="Analytics", icon=":material/insights:"),
             st.Page("app_pages/history.py", title="History", icon=":material/history:")]
pages["Insights"] = insights
if can("admin"):
    pages["Admin"] = [st.Page("app_pages/settings.py", title="Settings", icon=":material/settings:")]

st.navigation(pages).run()
