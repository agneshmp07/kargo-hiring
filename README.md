# Kargo hiring

Ranks PM and Senior PM applications, then runs everything after the decision. **The system recommends; a person decides.**
Nothing reaches a candidate until someone with decision rights clicks *Invite* or *Pass*, and even then the email
waits a few minutes so a misclick can be undone.

## Two ways to run it

| | Web app (for Vercel + Neon) | Local app |
|---|---|---|
| Screens | Next.js (`src/`) | Streamlit (`app.py`, `app_pages/`) |
| Engine | the same Python package (`shortlister/`), served at `/api` | the same package, in-process |
| Storage | everything in Neon (CVs too) | local files + SQLite, or Neon |
| Deploy guide | **[DEPLOY.md](DEPLOY.md)** | this README |

Both use the same scoring, redaction, emails and database, and the same tests cover both.

## Try the demo first

Double-click **`run_demo.bat`**, or run:

```bash
python -m shortlister demo            # opens http://localhost:8531
python -m shortlister demo --reset    # start the demo over
```

The demo uses its own `demo/` folder, 12 fictional candidates and 4 fictional teammates. It **never sends anything** and
**never uses Neon**, whatever `.env` says. Pick a person on the first screen to see the app with their permissions. To
test uploads, drag the files from `demo/sample_cvs/` into **Add CVs**. Without an API key, the demo scores them with a
simple keyword stand-in (clearly labelled); with a key, it uses the real AI.

| Sample CV | What it shows |
|---|---|
| Rhea Kapoor | Strong PM: port ops, sole PM, crisis, killed a feature |
| Arnav Mehra | The keyword trap: logistics only through APIs, so Not a fit |
| Sana Iyer | SPM integration owner with no ops background: Borderline |
| Tanvi Shah | Sparse CV: low confidence, kept at Borderline for a human look |
| Vikrant Rao | Great, but 12+ years: outside the range, yet kept visible by the ops floor |
| Kunal Bose | Consultant to PM, desk-side logistics: Not a fit |

## Pages

| Page | Who | What |
|---|---|---|
| Shortlist | everyone | Ranked cards per role, evidence quotes, safety-net notes, **Invite / Pass / Hold**, undo strip, bulk Pass, On hold, Random check, Backlog, comments, second opinions |
| Add CVs | founder, hiring manager, coordinator | Drag-and-drop upload with role choice; careers form and inbox status |
| Interviews | everyone | Invited, booked, interviewed and outcome; set times; scorecards; *Selected / Not selected / Withdrew* |
| Second opinions | founder, hiring manager, interviewer | Answer a teammate's request (a suggestion only) |
| Calibrate | founder, hiring manager | Blind-rate 10 CVs and see agreement with the system |
| Analytics | everyone | Funnel, speed, agreement, outcomes by band, sources, fairness check, AI spend, PDF board report, training CSV |
| History | everyone | Decisions (with who and undo), every message and its delivery status, activity log |
| Settings | founder | Team and access, jobs and scoring versions, email automation and templates, privacy, backups, integrations |

Roles: **founder** (decides, admin), **hiring manager**, **interviewer**, **coordinator**, **viewer**. Only founders
decide by default, as the brief requires. Settings > Team can extend that, and every decision records who made it.

## Setup for real use

```bash
pip install -r requirements.txt
copy .env.example .env          # fill in what you need (below)
python -m shortlister ui        # or double-click run_app.bat. The first screen creates the founder account.
python -m shortlister worker    # keep running: sends emails, reminders, digest, inbox, retention
python -m shortlister server    # optional: careers form + webhooks (needs a public address)
```

| Variable | Needed for |
|---|---|
| `ANTHROPIC_API_KEY`, `KARGO_MODEL` (default `claude-sonnet-5`) | scoring CVs |
| `DATABASE_URL` | **Neon** (`postgresql://…neon.tech/…?sslmode=require`); otherwise local SQLite |
| `VAULT_KEY` | encrypting names and emails at rest (`python -m shortlister keygen`) |
| `DRY_RUN` (default `true`), `TEST_RECIPIENT`, `TEST_WHATSAPP` | safety: only `DRY_RUN=false` sends |
| `RESEND_API_KEY`, `FROM_EMAIL`, `RESEND_WEBHOOK_SECRET` | sending email, then delivery and bounce tracking |
| `SCHEDULING_LINK` (or `SCHEDULING_LINK_PM`, `_SPM`) | booking link in invites (Cal.com or Calendly) |
| `CALCOM_WEBHOOK_SECRET` / `CALENDLY_WEBHOOK_SECRET` | marking interviews as booked automatically |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` | WhatsApp to candidates who opted in |
| `SLACK_WEBHOOK_URL` | digest to Slack |
| `HIRING_IMAP_HOST`, `HIRING_IMAP_USER`, `HIRING_IMAP_PASSWORD` | pulling CVs from a hiring mailbox |
| `PUBLIC_BASE_URL` | where the careers form and webhooks are reachable |

The identity vault (`vault/identities.json`) always stays a **local file**, even with Neon, so identities never sit next
to the scores (G4.3). Back it up together with `VAULT_KEY`.

## Email automation

| Trigger | Message | Default |
|---|---|---|
| Invite (after the undo window) | Interview invite with a booking link tagged with the candidate ID (+ WhatsApp if opted in) | 10-min undo |
| Pass (after the undo window) | Kind, role-specific rejection, with no scores or reasons | 10-min undo |
| Invited but not booked after N days | One gentle reminder | 3 days |
| Interview booked | Reminder N hours before | 24 h |
| *Not selected* after interview | Post-interview email | on |
| *Selected* | **Nothing**: offers stay outside the system | n/a |
| Hold older than 7 days | Reminder to decision-makers (and in-app) | on |
| Every morning | Team digest by email (and Slack): new CVs, waiting, holds, interviews, mentions, failures | 9:00 IST |
| CV received | Acknowledgement | **off** (it would reach candidates before a decision, against the brief's overriding rule) |

All templates are editable in Settings. Saving is refused if a template mentions scores, bands, reasons or offers.

## Commands

```
ui · demo [--reset] · run [--batch-api] · watch · worker [--once] · server [--port] · digest
backlog --list f.txt | --older-than N · adduser NAME --name --role --email · keygen · encrypt-vault
backup · purge · erase KG-0001 · export KG-0001 · recalculate · maths · status
```

`run --batch-api` uses the Message Batches API: half the cost; results usually arrive in minutes.

## Tests

```bash
python -m pytest -q
```

| Section 7 test | File |
|---|---|
| 1. Maths matches `stress_run.py` (bands exact, scores ±0.1) | `tests/test_maths.py` |
| 2. No name, college or email reaches the LLM payload | `tests/test_redaction.py` |
| 3. A 0.5/1 with a null quote is forced to 0 | `tests/test_evidence.py` |
| 4. No email without a logged decision | `tests/test_no_autonomous_send.py` |
| 5. The default config sends nothing | `tests/test_dry_run.py` |

`tests/test_features.py` covers:
- undo, logins and permissions, and template guardrails
- follow-ups, reminders, post-interview emails, WhatsApp opt-in, and the digest
- the careers form, signed webhooks, duplicates, erasure and export, retention, vault encryption and backups
- versioned roles, Batch API cost, analytics and PDF, calibration, and the demo stand-in

`tests/test_neon_live.py` runs against a real Neon database when `TEST_DATABASE_URL` is set.

## Layout

```
shortlister/   scoring, llm, redaction, parsing, pipeline, decisions, emails, automation, intake, privacy,
               analytics, versions, settings, auth, vault, store, server, demo, CLI
app.py, app_pages/, ui_common.py   the Streamlit app
reference/     stress_run.py, synthetic_candidates.json, rubric_params_v02.json (as supplied)
jds/           the two JDs          demo/  demo workspace (created on first run)
applications/  incoming CVs         vault/ identity map (local only)
data/          SQLite + JSONL log   outbox/ dry-run messages    backups/
```
