"""Batch run: applications/ -> parse -> redact -> classify -> score -> store.

Idempotent: a CV whose file hash is unchanged is never re-scored.
Two classification modes: one API call per CV (default), or the Message Batches API
(50% cheaper, results usually in minutes) with use_batch_api=True.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import config, cvstore, llm, roles, scoring, store, vault, versions
from .parsing import parse_file
from .redaction import extract_identity, leaks, redact

Classifier = Callable[[dict], tuple]


def list_applications() -> list[str]:
    """Names of every stored CV. Unsupported formats are still ingested so they surface
    as parse failures instead of being silently dropped."""
    return cvstore.names()


# Sidecar details (source, consent, opt-ins) live with the CV in cvstore.
def write_meta(name: str, **fields) -> None:
    cvstore.update_meta(name, **fields)


def read_meta(name: str) -> dict:
    return cvstore.meta(name)


def primary_role(cand: dict) -> str:
    res = cand["results_json"] or {}
    if cand["applied_role"] in res:
        return cand["applied_role"]
    return cand["better_fit"] if cand["better_fit"] in res else next(iter(res))


# ---------------- per-CV steps ----------------

def prepare(rel: str, conn, params: dict, system_prompt: str) -> dict:
    """Parse, extract identity (to the vault), redact, detect role, build the AI payload."""
    h = cvstore.file_hash(rel)
    base = Path(rel).name
    existing = store.candidate_by_file(conn, rel)
    cid = existing["id"] if existing else store.next_candidate_id(conn)
    if not existing:  # reserve the ID so a batch of many CVs gets distinct IDs
        conn.execute("INSERT INTO candidates (id, file_name, file_hash) VALUES (?, ?, ?)", (cid, rel, "pending"))

    with cvstore.local_path(rel) as path:
        parsed = parse_file(path)
    ident = extract_identity(parsed.text, base)
    vault.put(cid, name=ident.name, email=ident.email, phone=ident.phone, city=ident.city, file_name=rel)
    dups = vault.find_duplicates(cid, ident.email, ident.phone)

    redacted, removed = redact(parsed.text, ident)
    for value in leaks(redacted, ident):  # belt and braces: strip anything the patterns missed
        if value != "email pattern":
            redacted = re.sub(re.escape(value), "[REDACTED]", redacted, flags=re.I)
    applied, role_source = roles.detect_applied_role(base, parsed.text, params)
    payload = None
    if not parsed.error:
        payload = llm.build_payload(cid, redacted, applied, system_prompt, params=params)
    meta = cvstore.meta(rel)
    received = cvstore.received_at(rel)
    return {"cid": cid, "rel": rel, "hash": h, "parsed": parsed, "ident": ident, "redacted": redacted,
            "removed": removed, "applied": applied, "role_source": role_source, "payload": payload,
            "meta": meta, "received_at": received, "duplicates": dups}


def finalize(conn, ctx: dict, obj: dict | None, llm_error: str | None, usage: dict, batch_id: str,
             params: dict) -> dict:
    """Evidence rule, policy scrub, deterministic scoring, store."""
    cid, parsed = ctx["cid"], ctx["parsed"]
    low_reasons: list[str] = []
    if parsed.error:
        low_reasons.append(f"parse failure: {parsed.error}")
        obj = llm.empty_result(cid, f"CV could not be parsed ({parsed.error})", params)
    else:
        if parsed.sparse:
            low_reasons.append("sparse CV (very little text)")
        if parsed.note:
            low_reasons.append(parsed.note)
        if obj is None:
            low_reasons.append(f"classification failed twice: {llm_error}")
            obj = llm.empty_result(cid, llm_error or "classification failed", params)
    obj["candidate_id"] = cid

    evidence_flags = llm.enforce_evidence(obj, ctx["redacted"])
    policy_notes = llm.scrub_policy(obj)
    llm.fill_probes(obj)
    if obj["confidence"] == "low" and not parsed.error and not llm_error:
        low_reasons.append(f"model confidence low: {obj.get('confidence_reason', '')}")
    if obj.get("pm_years") is None and not parsed.error:
        low_reasons.append("PM years could not be worked out")
    low = bool(low_reasons)

    to_score = [r for r in roles.roles_to_score(ctx["applied"], obj.get("pm_years"), params)
                if r in obj["layer_b"]]
    results = {
        r: scoring.score_role(
            {k: v["code"] for k, v in obj["layer_a"].items()},
            {k: v["code"] for k, v in obj["layer_b"][r].items()},
            obj.get("pm_years"), r, params, low_confidence=low,
        )
        for r in to_score
    }
    best = scoring.better_fit(results)
    if not obj.get("city") or obj["city"] == "unknown":
        obj["city"] = ctx["ident"].city or "unknown"
    obj["policy_notes"] = policy_notes

    batch_mode = bool(usage.get("batch"))
    usage = {k: v for k, v in (usage or {}).items() if k != "batch"}
    if usage:
        usage["model"] = config.model()
        usage["cost_usd"] = llm.cost_usd(usage, usage["model"], batch=batch_mode)
    meta = ctx["meta"]
    rec = {
        "id": cid, "file_name": ctx["rel"], "file_hash": ctx["hash"],
        "applied_role": ctx["applied"], "role_source": ctx["role_source"],
        "redacted_text": ctx["redacted"], "redaction_removed": json.dumps(ctx["removed"]),
        "llm_json": json.dumps(obj, ensure_ascii=False), "llm_error": llm_error,
        "evidence_flags": json.dumps(evidence_flags), "results_json": json.dumps(results),
        "better_fit": best, "confidence": "low" if low else obj["confidence"],
        "low_conf_reasons": json.dumps(low_reasons), "parse_error": parsed.error,
        "batch_id": batch_id, "scored_at": store.now(),
        "source": meta.get("source", "folder"), "uploaded_by": meta.get("uploaded_by"),
        "received_at": ctx["received_at"], "whatsapp_opt_in": 1 if meta.get("whatsapp_opt_in") else 0,
        "duplicate_of": ",".join(ctx["duplicates"]) or None,
        "params_version": params.get("_version"), "usage_json": json.dumps(usage) if usage else None,
    }
    store.upsert_candidate(conn, rec)
    return store.get_candidate(conn, cid)


def _unpack(result) -> tuple:
    """Classifiers may return (obj, err) or (obj, err, usage)."""
    if len(result) == 2:
        return result[0], result[1], {}
    return result


def run_batch(classifier: Classifier | None = None, log: Callable[[str], None] = print,
              seed: int | None = None, use_batch_api: bool = False, batch_client=None,
              limit: int | None = None) -> dict:
    """Score new or changed CVs. `limit` caps how many are scored in this call (Vercel
    requests are short, so the web app scores one CV per request and repeats)."""
    config.ensure_dirs()
    batch_id = datetime.now(timezone.utc).strftime("B%Y%m%d-%H%M%S")
    files = list_applications()
    current = cvstore.hashes()
    new, skipped, failed = [], 0, 0

    with store.connect() as conn:
        params = versions.active(conn)
        conn.execute("INSERT INTO batches (id, started_at, mode) VALUES (?, ?, ?) "
                     "ON CONFLICT(id) DO UPDATE SET started_at = excluded.started_at",
                     (batch_id, store.now(), "batch-api" if use_batch_api else "sync"))
        todo = []
        for name in files:
            existing = store.candidate_by_file(conn, name)
            if existing and existing["file_hash"] == current.get(name) and existing["scored_at"]:
                skipped += 1
            elif limit is None or len(todo) < limit:
                todo.append(name)
        system_prompt = llm.build_system_prompt(versions.jd_texts(params), params) if todo else None

        def done(cand):
            nonlocal failed
            if cand["parse_error"]:
                failed += 1
            role = primary_role(cand)
            r = cand["results_json"][role]
            log(f"{cand['id']}  {role:3s}  {r['band']:10s}  F={r['final']:5.1f}  gate={r['gate']}"
                + (f"  [{', '.join(r['floors'])}]" if r["floors"] else "")
                + ("  (parse failed)" if cand["parse_error"] else ""))
            new.append(cand)

        if use_batch_api and config.llm_provider() != "anthropic":
            log("The Batch API option is Claude-only; scoring one by one with Gemini.")
            use_batch_api = False
        if use_batch_api and todo:
            ctxs = [prepare(p, conn, params, system_prompt) for p in todo]
            conn.commit()
            payloads = {c["cid"]: c["payload"] for c in ctxs if c["payload"]}
            results = llm.classify_batch(payloads, batch_client, params, log=log) if payloads else {}
            for ctx in ctxs:
                obj, err, usage = results.get(ctx["cid"], (None, None, {}))
                done(finalize(conn, ctx, obj, err, usage, batch_id, params))
                conn.commit()
        else:
            for path in todo:
                ctx = prepare(path, conn, params, system_prompt)
                obj, err, usage = None, None, {}
                if ctx["payload"]:
                    if classifier is None:
                        classifier = _live_classifier(params)
                    obj, err, usage = _unpack(classifier(ctx["payload"]))
                done(finalize(conn, ctx, obj, err, usage, batch_id, params))
                conn.commit()

        spot = pick_spot_checks(conn, batch_id, new, seed=seed)
        cost = sum((c["usage_json"] or {}).get("cost_usd", 0) for c in new)
        conn.execute("UPDATE batches SET finished_at=?, n_new=?, n_skipped=?, n_failed=?, cost_usd=? WHERE id=?",
                     (store.now(), len(new), skipped, failed, cost, batch_id))
    write_parse_failures()
    _after_ingest(new)
    summary = {"batch_id": batch_id, "new": len(new), "skipped_unchanged": skipped,
               "parse_failures": failed, "spot_checks": spot, "cost_usd": round(cost, 4),
               "remaining": max(0, len(files) - skipped - len(new)), "scored_ids": [c["id"] for c in new]}
    log(f"Batch {batch_id}: {len(new)} scored, {skipped} unchanged (skipped), {failed} parse failures. "
        f"Spot-check: {', '.join(spot) or 'none'}" + (f". AI cost ${cost:.3f}" if cost else ""))
    return summary


def _after_ingest(new_cands: list[dict]) -> None:
    """Optional acknowledgement emails (off by default; see settings.ack_enabled)."""
    if not new_cands:
        return
    from . import emails, settings

    if settings.get("ack_enabled"):
        for c in new_cands:
            emails.queue_ack(c["id"])


def pick_spot_checks(conn, batch_id: str, new_cands: list[dict], seed: int | None = None) -> list[str]:
    """G1.4: 3 random 'Not a fit' CVs per batch. If the batch has fewer than 3,
    top up from earlier undecided Not-a-fit CVs that were never spot-checked."""
    rng = random.Random(seed)

    def is_naf(c):
        return bool(c["results_json"]) and c["results_json"][primary_role(c)]["band"] == "Not a fit"

    pool = [c for c in new_cands if is_naf(c)]
    picks = rng.sample(pool, min(config.SPOT_CHECK_SIZE, len(pool)))
    if len(picks) < config.SPOT_CHECK_SIZE and new_cands:
        checked = {r["candidate_id"] for r in conn.execute("SELECT candidate_id FROM spot_checks")}
        picked = {p["id"] for p in picks}
        older = [c for c in store.all_candidates(conn)
                 if c["scored_at"] and not c["erased_at"] and is_naf(c) and c["id"] not in checked
                 and c["id"] not in picked and not store.latest_decision(conn, c["id"])]
        picks += rng.sample(older, min(config.SPOT_CHECK_SIZE - len(picks), len(older)))
    for c in picks:
        conn.execute("INSERT OR IGNORE INTO spot_checks (batch_id, candidate_id, role) VALUES (?,?,?)",
                     (batch_id, c["id"], primary_role(c)))
        store.audit("spot_check_selected", _conn=conn, batch_id=batch_id, candidate_id=c["id"])
    return [c["id"] for c in picks]


def _live_classifier(params: dict) -> Classifier:
    if config.llm_provider() == "gemini":
        from . import gemini_client

        gemini_client.check_allowed()  # fail fast, before any CV is sent
        return lambda payload: gemini_client.classify(payload, params)
    client = llm._client()
    return lambda payload: llm.classify(payload, client, params)


def write_parse_failures() -> None:
    with store.connect() as conn:
        data = store.rows(conn, "SELECT id, file_name, parse_error FROM candidates "
                                "WHERE parse_error IS NOT NULL AND erased_at IS NULL ORDER BY id")
    if config.storage_mode() == "files":  # in db mode the list is read straight from the candidates table
        (store.db_path().parent / config.PARSE_FAILURES_PATH.name).write_text(json.dumps(data, indent=2),
                                                                              encoding="utf-8")
        _update_notes(data)


NOTES_START = "<!-- parse-failures:start -->"
NOTES_END = "<!-- parse-failures:end -->"


def _update_notes(failures: list[dict]) -> None:
    notes = config.ROOT / "NOTES.md"
    if not notes.exists() or store.db_path() != config.DB_PATH or config.HOME != config.ROOT:
        return  # tests and demos use other folders; only the real workspace updates NOTES.md
    text = notes.read_text(encoding="utf-8")
    if NOTES_START not in text:
        return
    body = ("\n".join(f"- `{f['id']}`: `{f['file_name']}`: {f['parse_error']}" for f in failures)
            or "- None so far.")
    head, rest = text.split(NOTES_START, 1)
    _, tail = rest.split(NOTES_END, 1)
    notes.write_text(f"{head}{NOTES_START}\n{body}\n{NOTES_END}{tail}", encoding="utf-8")


def mark_backlog(file_names: list[str] | None = None, older_than_days: int | None = None) -> list[str]:
    """Backlog mode: flag CVs that were already opened but never answered."""
    marked = []
    cutoff = time.time() - older_than_days * 86400 if older_than_days else None
    with store.connect() as conn:
        for c in store.all_candidates(conn):
            hit = bool(file_names) and (c["file_name"] in file_names or Path(c["file_name"]).name in file_names)
            if cutoff and (c["received_at"] or "9") < datetime.fromtimestamp(cutoff, timezone.utc).isoformat():
                hit = True
            if hit and not store.latest_decision(conn, c["id"]):
                conn.execute("UPDATE candidates SET backlog = 1 WHERE id = ?", (c["id"],))
                marked.append(c["id"])
        store.audit("backlog_marked", _conn=conn, candidate_ids=marked)
    return marked


def pending_files() -> list[str]:
    """Stored CVs that are new or changed since they were scored."""
    with store.connect() as conn:
        known = {r["file_name"]: r["file_hash"] for r in conn.execute("SELECT file_name, file_hash FROM candidates "
                                                                        "WHERE scored_at IS NOT NULL")}
    return [n for n, h in cvstore.hashes().items() if known.get(n) != h]


def watch(log: Callable[[str], None] = print, debounce: float = 5.0) -> None:
    """Watch applications/ and run a batch when files land. Ctrl+C to stop."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    state = {"last": 0.0}

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if not event.is_directory and event.event_type in ("created", "modified", "moved"):
                state["last"] = time.time()

    config.ensure_dirs()
    obs = Observer()
    obs.schedule(Handler(), str(config.APPLICATIONS_DIR), recursive=True)
    obs.start()
    log(f"Watching {config.APPLICATIONS_DIR} (Ctrl+C to stop)")
    run_batch(log=log)
    try:
        while True:
            time.sleep(1)
            if state["last"] and time.time() - state["last"] > debounce:
                state["last"] = 0.0
                run_batch(log=log)
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join()
