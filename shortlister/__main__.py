"""CLI: python -m shortlister <command>   (python -m shortlister -h for the list)"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

from . import config


def _streamlit(port: int, extra_env: dict | None = None) -> int:
    env = {**os.environ, **(extra_env or {})}
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(config.ROOT / "app.py"),
                            "--server.port", str(port), "--server.headless", "true",
                            "--browser.gatherUsageStats", "false"], env=env, cwd=str(config.ROOT))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shortlister", description="Kargo CV shortlister")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ui", help="Open the shortlist app")
    d = sub.add_parser("demo", help="Open the demo (fictional candidates, never sends anything)")
    d.add_argument("--reset", action="store_true", help="Start the demo from scratch")
    sub.add_parser("demo-seed", help=argparse.SUPPRESS)

    r = sub.add_parser("run", help="Score new CVs in applications/ (skips unchanged ones)")
    r.add_argument("--batch-api", action="store_true", help="Use the Message Batches API (50%% cheaper, slower)")
    sub.add_parser("watch", help="Score automatically when files land in applications/")
    w = sub.add_parser("worker", help="Run the automation worker (emails, reminders, digest, inbox, retention)")
    w.add_argument("--once", action="store_true", help="Run a single tick and exit")
    s = sub.add_parser("server", help="Run the careers form and webhook receiver")
    s.add_argument("--port", type=int, default=8600)
    sub.add_parser("digest", help="Send the daily digest now")

    b = sub.add_parser("backlog", help="Flag already-opened, never-answered applications")
    b.add_argument("--files", nargs="*", default=[], help="File names in applications/")
    b.add_argument("--list", help="Text file with one file name per line")
    b.add_argument("--older-than", type=int, help="Flag CVs whose file is older than N days")

    u = sub.add_parser("adduser", help="Create a login (you'll be asked for the password)")
    u.add_argument("username")
    u.add_argument("--name", required=True)
    u.add_argument("--role", default="founder",
                   choices=["founder", "hiring_manager", "interviewer", "coordinator", "viewer"])
    u.add_argument("--email", default="")

    pw_cmd = sub.add_parser("passwd", help="Set a new password for a login (you'll be asked for it)")
    pw_cmd.add_argument("username")
    sub.add_parser("keygen", help="Print a new VAULT_KEY for encrypting the identity vault")
    sub.add_parser("secrets", help="Print fresh VAULT_KEY, SESSION_SECRET and CRON_SECRET for Vercel")
    sub.add_parser("resend-check", help="Check the Resend key and whether the sending domain is verified")
    te = sub.add_parser("test-email", help="Send one real test email to YOUR address via Resend")
    te.add_argument("to")
    sub.add_parser("encrypt-vault", help="Encrypt the existing vault with VAULT_KEY")
    sub.add_parser("backup", help="Write a backup zip to backups/")
    sub.add_parser("purge", help="Erase candidates past the retention period now")
    e = sub.add_parser("erase", help="Erase one candidate's personal data (DPDP request)")
    e.add_argument("candidate_id")
    x = sub.add_parser("export", help="Print everything held about one candidate (access request)")
    x.add_argument("candidate_id")
    sub.add_parser("recalculate", help="Recompute bands with the active settings version (no AI calls)")
    sub.add_parser("maths", help="Score synthetic_candidates.json and print the bands")
    sub.add_parser("status", help="Show counts and configuration")
    args = p.parse_args(argv)

    if args.cmd == "ui":
        return _streamlit(8530)
    if args.cmd == "demo":
        demo_home = config.ROOT / "demo"
        env = {"KARGO_DEMO": "1", "KARGO_HOME": str(demo_home)}
        if args.reset and demo_home.exists():
            # OneDrive sometimes locks empty folders; removing the files is what matters.
            shutil.rmtree(demo_home, ignore_errors=True)
            for f in sorted(demo_home.rglob("*"), reverse=True):
                try:
                    f.unlink() if f.is_file() else f.rmdir()
                except OSError:
                    pass
        if not (demo_home / "data" / "kargo.db").exists():
            print("Setting up the demo…")
            rc = subprocess.call([sys.executable, "-m", "shortlister", "demo-seed"], env={**os.environ, **env},
                                 cwd=str(config.ROOT))
            if rc:
                return rc
        print("Demo running at http://localhost:8531  (Ctrl+C to stop)")
        return _streamlit(8531, env)
    if args.cmd == "demo-seed":
        if not config.is_demo():
            p.error("demo-seed only runs in demo mode")
        from . import demo
        demo.seed()
        return 0

    if args.cmd == "run":
        from .pipeline import run_batch
        run_batch(use_batch_api=args.batch_api)
    elif args.cmd == "watch":
        from .pipeline import watch
        watch()
    elif args.cmd == "worker":
        from . import automation
        if args.once:
            print(automation.tick())
        else:
            automation.run_forever()
    elif args.cmd == "server":
        from . import server
        server.run(port=args.port)
    elif args.cmd == "digest":
        from datetime import datetime, timezone

        from . import automation
        automation.daily_digest(datetime.now(timezone.utc), force=True)
        print("Digest sent" + (" (dry run: see outbox/)" if config.dry_run() else ""))
    elif args.cmd == "backlog":
        from .pipeline import mark_backlog
        names = list(args.files)
        if args.list:
            names += [l.strip() for l in open(args.list, encoding="utf-8") if l.strip()]
        if not names and not args.older_than:
            p.error("give --files, --list or --older-than")
        marked = mark_backlog(names, args.older_than)
        print(f"Flagged {len(marked)} backlog candidate(s): {', '.join(marked) or 'none'}")
    elif args.cmd in ("adduser", "passwd"):
        import getpass

        from . import auth
        if args.cmd == "passwd" and not auth.get_user(args.username):
            print(f"There's no login called {args.username}.")
            return 1
        print("Type the password (nothing shows while you type; pasting doesn't work in this prompt).")
        for attempt in range(3):
            pw = getpass.getpass("Password (10+ characters, letters and a number): ")
            problem = auth.validate_password(pw)
            if problem:
                print(f"  That password won't work: {problem}. Try again.")
                continue
            if pw != getpass.getpass("Repeat password: "):
                print("  The two passwords didn't match. Try again.")
                continue
            break
        else:
            print("No account created. Run the command again when you're ready.")
            return 1
        if args.cmd == "passwd":
            auth.set_password(args.username, pw, by="cli")
            print(f"New password set for {args.username}. Sign in with it on the website.")
            return 0
        try:
            auth.create_user(args.username, args.name, args.role, pw, args.email, by="cli")
        except ValueError as exc:
            print(f"No account created: {exc}")
            return 1
        print(f"Created {args.username} ({args.role}). You can now sign in on the website.")
    elif args.cmd == "keygen":
        from . import vault
        print("Add this line to .env (keep it secret, and back it up: without it the vault can't be read):")
        print(f"VAULT_KEY={vault.new_key()}")
    elif args.cmd == "secrets":
        import secrets as _s

        from . import vault
        print("Add these to Vercel > Project > Settings > Environment Variables (keep them secret).")
        print("Back up VAULT_KEY: without it, stored names and emails can't be read.\n")
        print(f"VAULT_KEY={vault.new_key()}")
        print(f"SESSION_SECRET={_s.token_hex(32)}")
        print(f"CRON_SECRET={_s.token_hex(24)}")
    elif args.cmd == "resend-check":
        from . import resend_client
        st = resend_client.domain_status()
        print(f"From:      {config.from_email()}")
        print(f"Reply-to:  {config.env('REPLY_TO') or '(not set: replies go to the From address)'}")
        print(f"Domain:    {st.get('domain')}  ->  {st['state']}")
        print(f"Result:    {st['message']}")
        print(f"Sending:   {'demo, never sends' if config.is_demo() else 'practice mode (DRY_RUN=true): candidate emails are only saved' if config.dry_run() else 'LIVE'}")
    elif args.cmd == "test-email":
        from . import emails
        pid = emails.send_test(args.to, "cli")
        print(f"Sent. Resend email id: {pid}. Check {args.to} (and the spam folder).")
    elif args.cmd == "encrypt-vault":
        from . import vault
        vault.encrypt_existing()
        print("Vault encrypted.")
    elif args.cmd == "backup":
        from . import privacy
        print(f"Backup written: {privacy.backup()}")
    elif args.cmd == "purge":
        from . import privacy
        erased = privacy.purge_expired(by="cli")
        print(f"Erased {len(erased)}: {', '.join(erased) or 'none'}")
    elif args.cmd == "erase":
        from . import privacy
        privacy.erase(args.candidate_id, by="cli")
        print(f"Erased personal data for {args.candidate_id}.")
    elif args.cmd == "export":
        from . import privacy
        print(json.dumps(privacy.export(args.candidate_id), indent=2, ensure_ascii=False, default=str))
    elif args.cmd == "recalculate":
        from . import versions
        print(versions.recalculate_all("cli"))
    elif args.cmd == "maths":
        from .scoring import score_role
        params = config.load_params()
        cases = json.loads((config.ROOT / "reference" / "synthetic_candidates.json").read_text())
        for c in cases:
            for role in c["roles"]:
                r = score_role(c["A"], c["B"][role], c["pm_years"], role, params, c.get("low_conf", False))
                print(f"{c['id']} {role:3s} A={r['layer_a']:5.1f} B={r['layer_b']:5.1f} F={r['final']:5.1f} "
                      f"gate={r['gate']:4s} -> {r['band']:10s} {','.join(r['floors'])}")
    elif args.cmd == "status":
        from . import auth, store, versions
        with store.connect() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM candidates WHERE scored_at IS NOT NULL").fetchone()["n"]
            d = conn.execute("SELECT COUNT(*) AS n FROM decisions WHERE undone_at IS NULL").fetchone()["n"]
        print(f"db={store.backend()} candidates={n} decisions={d} settings_version={versions.active()['_version']} "
              f"users={len(auth.users())} model={config.model()} DRY_RUN={config.dry_run()} "
              f"TEST_RECIPIENT={'set' if config.test_recipient() else 'unset'} "
              f"VAULT_KEY={'set' if config.env('VAULT_KEY') else 'unset'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
