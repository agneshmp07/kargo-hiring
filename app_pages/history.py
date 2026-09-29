import json

import pandas as pd
import streamlit as st

from shortlister import emails, store, vault
from ui_common import EMAIL_STATUS, can, load_state

state = load_state()
st.title("History")
st.caption("Every decision, every message and every change, with who did it and when.")

tab_d, tab_e, tab_a = st.tabs(["Decisions", "Messages", "Activity log"])

with tab_d:
    with store.connect() as conn:
        rows = store.rows(conn, "SELECT * FROM decisions ORDER BY id DESC")
    if not rows:
        st.info("No decisions yet.", icon=":material/history:")
    else:
        df = pd.DataFrame(rows)
        df["email"] = df["id"].map(lambda i: EMAIL_STATUS.get((state["email_by_decision"].get(i) or {}).get("status"), "-"))
        df["safety_nets"] = df["floors"].map(lambda f: ", ".join(a["rule"] for a in json.loads(f or "[]")))
        advanced = set(df.loc[(df["decision"] == "Advance") & df["undone_at"].isna(), "candidate_id"])
        df["name"] = df["candidate_id"].map(lambda c: vault.get(c).get("name", "") if c in advanced else "")
        df["when"] = df["ts"].str.slice(0, 16).str.replace("T", " ")
        df["status"] = df["undone_at"].map(lambda u: "undone" if isinstance(u, str) and u else "")
        cols = ["when", "candidate_id", "name", "role", "decision", "status", "decided_by", "band", "final",
                "layer_a", "layer_b", "gate", "safety_nets", "email", "source", "rationale_shown"]
        st.dataframe(df[cols], hide_index=True)
        st.download_button("Download as CSV", df[cols].to_csv(index=False), "decision_log.csv",
                           icon=":material/download:")

with tab_e:
    msgs = state["emails"]
    if not msgs:
        st.info("No messages yet. Messages are only created after someone decides.", icon=":material/mail:")
    else:
        edf = pd.DataFrame(msgs)
        edf["status"] = edf["status"].map(lambda s: EMAIL_STATUS.get(s, s))
        st.dataframe(edf[["id", "candidate_id", "kind", "channel", "status", "attempts", "provider_event", "error",
                          "send_after", "updated_at"]], hide_index=True)
        for e in [e for e in msgs if e["status"] in ("failed", "bounced")]:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.error(f"{e['kind']} to {e['candidate_id'] or e['to_addr']} {e['status']}: {e['error'] or e['provider_event']}",
                         icon=":material/error:")
                if e["status"] == "failed" and can("decide") and st.button("Try again", key=f"retry-{e['id']}",
                                                                           icon=":material/refresh:"):
                    emails.deliver(e["id"])
                    st.rerun()

with tab_a:
    with store.connect() as conn:
        log = store.rows(conn, "SELECT ts, event, data FROM audit_log ORDER BY id DESC LIMIT 500")
    if log:
        st.dataframe(pd.DataFrame(log), hide_index=True)
