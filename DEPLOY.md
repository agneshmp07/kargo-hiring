# Deploying to Vercel + Neon

One Vercel project serves both halves:

- **Next.js** (`src/`): the screens.
- **Python** (`api/index.py` → `shortlister/`): the scoring engine and JSON API at `/api/*`, the careers form
  (`/apply`) and the webhooks.

Neon holds everything. Vercel's disk is temporary, so CVs are stored in Neon too (`KARGO_STORAGE=db` is automatic on
Vercel).

## Two Vercel projects: demo first, then real

| | Demo | Real |
|---|---|---|
| Purpose | Try it with fictional data | Arjun's actual hiring |
| Key env var | `KARGO_DEMO=1` | (not set) |
| Database | `DEMO_DATABASE_URL`: a separate Neon branch or database | `DATABASE_URL` |
| Sends email | Never, whatever else is set | Only once `DRY_RUN=false` |
| AI | Keyword stand-in unless `ANTHROPIC_API_KEY` is set | `ANTHROPIC_API_KEY` |

The demo never reads `DATABASE_URL`, so it can't touch real data even if both are set.

## Step by step

1. **Neon.** In the Neon console, create a project in **AWS ap-south-1 (Mumbai)** or Singapore, to keep candidate data
   close to India for the DPDP Act. Create two databases, `kargo` and `kargo_vault`, and copy both connection strings
   (pooled, `?sslmode=require`). For the demo, create a branch `demo` and copy its string. You can also add Neon from
   Vercel → Storage → Marketplace, which sets `DATABASE_URL` for you.
2. **Secrets.** Run `python -m shortlister secrets` locally. It prints `VAULT_KEY`, `SESSION_SECRET` and `CRON_SECRET`.
   Store `VAULT_KEY` somewhere safe: without it, stored names and emails can't be read.
3. **Create the project.** Run `vercel link` in this folder, or import the repo in the Vercel dashboard. The framework
   (Next.js) and the Python function are picked up from `vercel.json`.
4. **Environment variables** (Project → Settings → Environment Variables):

   | Variable | Real | Demo |
   |---|---|---|
   | `DATABASE_URL` | Neon `kargo` | leave unset |
   | `VAULT_DATABASE_URL` | Neon `kargo_vault` | optional |
   | `DEMO_DATABASE_URL` | none | Neon `demo` branch |
   | `KARGO_DEMO` | none | `1` |
   | `VAULT_KEY`, `SESSION_SECRET`, `CRON_SECRET` | required | recommended |
   | `ANTHROPIC_API_KEY`, `KARGO_MODEL` | required to score | optional |
   | `DRY_RUN` | `true` until you're ready | ignored |
   | `RESEND_API_KEY`, `FROM_EMAIL`, `REPLY_TO`, `RESEND_WEBHOOK_SECRET` | when sending (see below) | none |
   | `SCHEDULING_LINK` (`_PM`, `_SPM`), `CALCOM_WEBHOOK_SECRET` / `CALENDLY_WEBHOOK_SECRET` | booking links and tracking | none |
   | `TWILIO_*`, `SLACK_WEBHOOK_URL`, `HIRING_IMAP_*` | optional | none |
   | `PUBLIC_BASE_URL` | `https://<your-domain>` | the demo URL |

5. **Deploy:** `vercel --prod`. Open the site. The first screen of the real project creates the founder account; the
   demo shows the person picker.
6. **Webhooks** (optional): point Resend at `https://<domain>/api/webhooks/resend`, and Cal.com or Calendly at
   `/api/webhooks/calcom` or `/api/webhooks/calendly`, each with its secret.

## Setting up Resend (email)

1. **Account and domain.** In Resend → Domains, add the domain you'll send from (e.g. `kargo.in`, or a subdomain such
   as `hire.kargo.in`). Add the DNS records it shows (SPF, DKIM, and ideally DMARC), then click Verify. Until then,
   Resend only sends from `onboarding@resend.dev`, and only to your own account's email address.
2. **API key.** In Resend → API Keys, create a key. A *Full access* key lets Settings show whether the domain is
   verified; a *Sending access* key works too, but the check will say it can't read domains.
3. **Vercel variables:**
   - `RESEND_API_KEY`
   - `FROM_EMAIL`, e.g. `Kargo Hiring <hiring@kargo.in>`, on the verified domain
   - `REPLY_TO`, e.g. Arjun's address, so candidate replies reach a person
4. **Delivery tracking.** In Resend → Webhooks, add `https://<your-domain>/api/webhooks/resend` and tick the email
   events (sent, delivered, delivery delayed, bounced, complained, failed, suppressed). Copy the signing secret into
   `RESEND_WEBHOOK_SECRET`. History then shows *delivered* or *bounced* (with the reason) for every email.
5. **Test.** Open Settings → Emails & automation → *Send a test email to me*. It sends one real email to you only.
6. **Go live in stages:**
   1. Keep `DRY_RUN=true`, make a few decisions, and read the saved emails in History → Messages.
   2. Set `DRY_RUN=false` together with `TEST_RECIPIENT=<your address>`. Every candidate email now comes to you instead.
   3. Remove `TEST_RECIPIENT` to send to candidates.

How sending works:
- Each email has an idempotency key tied to its record, so retries and overlapping cron runs never send it twice.
- The code backs off when Resend rate-limits and paces sends well under 10 per second.
- A bounce is never overwritten by a late "delivered" event.

## Things to know about Vercel

- **Plan.** Vercel's Hobby plan is for non-commercial use, and its cron runs at most once a day. For Kargo, use **Pro**.
  Then change the schedule in `vercel.json` to every 5 minutes (`"*/5 * * * *"`) so emails leave on time after the undo
  window. On Hobby, due emails still go out whenever anyone opens the Shortlist, plus once a day. A free external pinger
  (e.g. cron-job.org) can also call `GET /api/cron/tick` with the header `Authorization: Bearer <CRON_SECRET>`.
- **Time limit.** Each request may run up to 60 seconds. That's why *Add CVs* scores **one CV per request**, and
  the page loops with a progress bar. The cron job scores up to `CRON_SCORE_LIMIT` (default 3) waiting CVs per run.
- **Size.** The Python function installs only `requirements.txt` (no Streamlit or pandas). Local-only extras are in
  `requirements-local.txt`.
- **OCR** (Tesseract) isn't available on Vercel. Scanned PDFs are flagged for a human look instead.
- **Backups.** Neon keeps point-in-time history. Settings → Privacy also downloads a full zip backup.

## Local development (same set-up as Vercel)

```bash
pip install -r requirements-local.txt
npm install
set KARGO_DEMO=1 & set KARGO_STORAGE=db
npm run api      # Python API on :8100
npm run dev      # Next.js on :3100, proxies /api to :8100
```

The earlier Streamlit version still works locally (`python -m shortlister demo` / `ui`) and uses the same engine and
database.
