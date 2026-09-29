import streamlit as st

from shortlister import config, intake, pipeline
from ui_common import flash, load_state, show_flash, who

state = load_state()
names = state["role_names"]

st.title("Add CVs")
st.write("Drag and drop CVs: PDF or Word, as many as you like. Names, contact details and colleges are removed "
         "before the AI reads anything.")
show_flash()

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

use_standin = config.is_demo() and not config.api_ready()
can_score = config.api_ready() or use_standin


def score_now(expected: int):
    bar = st.progress(0.0, text="Reading and scoring CVs…")
    done = {"n": 0}

    def log(line: str):
        if line.startswith("KG-"):
            done["n"] += 1
            bar.progress(min(done["n"] / max(expected, 1), 1.0), text=f"Scored {done['n']} of {expected}")

    kwargs = {}
    if use_standin:
        from shortlister.demo import keyword_classifier

        kwargs["classifier"] = keyword_classifier
    try:
        summary = pipeline.run_batch(log=log, **kwargs)
    except Exception as exc:  # noqa: BLE001
        bar.empty()
        st.error(f"Scoring stopped: {exc}", icon=":material/error:")
        return
    bar.empty()
    msg = f"Done: {summary['new']} CV(s) scored. Open the Shortlist to review them."
    if summary["parse_failures"]:
        msg += f" {summary['parse_failures']} couldn't be read and are marked for you to check."
    if summary.get("cost_usd"):
        msg += f" AI cost: ${summary['cost_usd']:.3f}."
    flash(msg)
    st.rerun()


with st.container(border=True):
    choices = {**{n: c for c, n in names.items()}, "Not sure: check every role": ""}
    role_label = st.segmented_control("Which role are these CVs for?", list(choices),
                                      default="Not sure: check every role", key="upload-role")
    files = st.file_uploader("CV files", type=sorted(e.strip(".") for e in intake.ALLOWED_EXT),
                             accept_multiple_files=True, key=f"uploader-{st.session_state.uploader_key}",
                             label_visibility="collapsed")
    go = st.button("Save and score" if can_score else "Save CVs", type="primary", icon=":material/play_arrow:",
                   disabled=not files)
    if use_standin:
        st.caption(":material/science: Demo: with no API key, CVs are scored by a simple keyword stand-in, not "
                   "the AI. Try the files in `demo/sample_cvs`.")
    elif not config.api_ready():
        st.info("To score CVs, add your Anthropic API key to `.env` (`ANTHROPIC_API_KEY=...`) and restart. "
                "You can still save CVs now.", icon=":material/key:")

if go and files:
    saved, notes = [], []
    for f in files:
        name, note = intake.save_incoming(f.name, f.getvalue(), choices[role_label or "Not sure: check every role"],
                                          source="upload", uploaded_by=who())
        (saved if name else notes).append(name or note)
    st.session_state.uploader_key += 1
    for n in notes:
        st.info(n, icon=":material/content_copy:")
    if saved and can_score:
        score_now(len(pipeline.pending_files()))
    elif saved:
        flash(f"Saved {len(saved)} CV(s). Add the API key to score them.")
        st.rerun()

waiting = pipeline.pending_files()
if waiting:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(f"{len(waiting)} CV(s) saved but not scored yet: " + ", ".join(waiting[:8])
                   + (" …" if len(waiting) > 8 else ""))
        if st.button(f"Score {len(waiting)} waiting CV(s)", icon=":material/refresh:", disabled=not can_score):
            score_now(len(waiting))

st.subheader("Other ways CVs arrive")
c1, c2, c3 = st.columns(3)
with c1, st.container(border=True):
    st.markdown("**:material/public: Careers form**")
    st.write("A public page where candidates apply, with consent and an optional WhatsApp opt-in.")
    st.code(f"{config.public_base_url()}/apply", language=None)
    st.caption("Start it with `python -m shortlister server`.")
with c2, st.container(border=True):
    st.markdown("**:material/mail: Hiring inbox**")
    if intake.inbox_configured():
        st.success(f"Checking {config.env('HIRING_IMAP_USER')} for CV attachments.", icon=":material/check:")
    else:
        st.write("Forward applications (including from Naukri or LinkedIn) to a hiring mailbox and the worker "
                 "picks up the attachments.")
        st.caption("Set HIRING_IMAP_HOST, HIRING_IMAP_USER and HIRING_IMAP_PASSWORD in `.env`.")
with c3, st.container(border=True):
    st.markdown("**:material/folder: Folder**")
    st.write("Copy files into the applications folder and click *Score waiting CVs*, or run the worker to score "
             "automatically.")
    st.code(str(config.APPLICATIONS_DIR), language=None)
