# Notes for Arjun

## Read this first: the weights are a hypothesis

The Layer A points come from **8 past hires**. Before trusting the shortlist, **blind-rate 10 CVs yourself**
(Strong / Borderline / Not a fit, without looking at the system's output), then compare with the system's bands.
If you disagree on more than 2 of the 10, stop and revisit the weights before clearing the full batch.
The leave-one-out run in `reference/stress_run.py` shows how unstable they are: P2 ranges from 0 to 17 points
and P4 from 15 to 34, depending on which single hire is dropped.

## Parameter concerns (flagged, not acted on)

Every parameter is exactly as given in Section 3. These are concerns only.

1. **A "Vikram-type" acceptable hire is scored Not a fit.** C02 scores Layer A = 0, because N2 (−10.9) cancels P2
   (+10.9) and nothing else fires, for a final of 15. Section 7 expects Not a fit, which the build reproduces. But
   `synthetic_candidates.json` labels C02 "Borderline (he was an acceptable hire)". People like him will only be
   caught by the random check.
2. **The rounded points sum to 99.9, not 100.** The maximum Layer A is 99.9. The difference from the unrounded
   `stress_run.py` weights is ≤ 0.1 on every synthetic case and changes no band.
3. **N1 is penalised twice.** When N1 > 0, P1 is set to 0 *and* N1 subtracts 5.4. If the model wrongly codes N1
   for someone with real ops experience, that person loses 38 points and the P1 floor no longer protects them.
   The UI marks this case ("doesn't count: the logistics exposure is desk/API only") so it is easy to spot.
4. **One gate range for "too junior" and "too senior".** The ±1-year tolerance can't tell a 12-year candidate
   (C12, over-qualified) from a 1-year one. Both rely on floors to stay visible.
5. **The low-confidence floor overrides a gate fail.** A sparse CV with 12 years still shows as Borderline.
   That is right for recall, but expect some noise in Borderline.
6. **Temperature 0 isn't available on `claude-sonnet-5`.** The API rejects sampling parameters on this model, so the
   request omits `temperature`, and codes may vary slightly if the same CV is re-scored. The hash cache means each CV
   is scored once. If you need strict repeatability, set `KARGO_MODEL` to a model that accepts `temperature=0`,
   such as `claude-haiku-4-5`; the code then sends it automatically.

## Build choices where the spec was silent

- **PM years unknown:** the gate shows "unknown", which is treated like "near" (Strong is capped at Borderline), and the
  low-confidence floor applies.
- **Cross-role scoring (G3.2):** the other role is also scored when the candidate's PM years fall within that role's range
  ±1, or when the applied role is unclear. The better fit is flagged, and Arjun chooses the role when deciding.
- **Quotes not found word for word in the CV** are flagged in the UI but not zeroed. Only a missing quote forces a 0, as the spec says.
- **Rationale sentences or probes that mention a zero-weight factor** (college, tier, gaps, gender, age, photo, metrics,
  tech stack) are removed, and fallback probes fill the gaps.
- **Education years are redacted** as an age proxy. Work dates are kept for the PM-years calculation.
- **Invite and Pass are final**, because an email has gone out. Hold can be changed later.
- **Bulk Pass** leaves out CVs in an open random check and any CV Arjun flagged as "missed".
- **Backlog:** the system has no record of which applications were opened, so Arjun supplies the list
  (`backlog --list`) or an age cut-off (`--older-than N` days).
- **Database:** Neon/Postgres through `DATABASE_URL`, with local SQLite otherwise. The identity vault always stays a local file.

## Organisation features: decisions and limits

- **The acknowledgement email is off by default.** It would reach a candidate before any human decision, which the
  brief's overriding rule forbids. It is available in Settings, with a warning, if Arjun chooses to change the rule.
- **Only founders decide by default.** Hiring managers, interviewers and coordinators can comment, give second opinions,
  add scorecards and manage schedules. Settings > Team can extend decision rights; every decision records who made it.
- **Undo window.** Invite and Pass emails wait 10 minutes (1 minute in the demo). An undone decision cancels its emails
  and puts the candidate back in the queue. Once an email has gone out, the decision is final.
- **After an invite**, emails are automated but always hang off a human action: the follow-up (if not booked in 3
  days), the interview reminder, and the post-interview email (only when someone clicks *Not selected*).
  *Selected* sends nothing, because offers are out of scope.
- **Layer A points stay fixed in code**, as the brief requires. Admins can version the blend, bands, role-rescue
  threshold, gate ranges, role criteria and JDs, and add new roles. Every score records its settings version.
  *Recalculate* re-bands from the stored AI codes without new AI calls. A new role needs its CVs re-classified.
- **The fairness check covers city only.** Gender, age and similar are never collected, by design, so they can't be
  measured. The check reads the vault and never feeds back into scores.
- **WhatsApp** only goes to candidates who ticked the opt-in on the careers form. Outside the 24-hour window, WhatsApp
  requires pre-approved templates on your Twilio sender; the sandbox works for testing.
- **Job boards:** Naukri and LinkedIn have no open API for this. Forward their application emails to the hiring inbox,
  and the worker picks up the attachments.
- **OCR** for scanned PDFs runs locally with Tesseract, so unredacted images never go to the AI. Install Tesseract to
  enable it; without it, scanned CVs are flagged low-confidence as before.
- **Before deploying:** the built-in login uses salted scrypt passwords, which is fine for a small team. For a hosted
  deployment, put it behind HTTPS and consider SSO (Google Workspace / Microsoft). The public careers form has size
  and type limits but no CAPTCHA or rate limit; add rate limiting at the host. The webhook server needs a public
  HTTPS address (`PUBLIC_BASE_URL`), and every webhook is signature-checked.

## Inputs

- The ~60 application CVs were **not in the workspace** at build time. `applications/` is empty; drop the CVs there or
  upload them in the UI.
- Past-hire CVs (`hires_…zip` in Downloads) were **not** copied into the project and are never sent to the LLM.
  Their pattern is already encoded in the weights. They were read locally, once, only to test the redaction rules.

## CVs that failed to parse

This list updates automatically after each batch.

<!-- parse-failures:start -->
- None so far.
<!-- parse-failures:end -->
