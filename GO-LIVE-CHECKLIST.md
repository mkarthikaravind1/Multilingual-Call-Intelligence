# Go-live checklist

What to fill in when each access arrives, and the test to run straight after.
Everything is set in `.env` at the repository root (locally) or
`deploy/.env.production` (on the server). Restart the backend after a change.

Nothing here has been run against the real services yet unless it says so.
Items marked **Unverified** were built to the provider's documentation and
need the test beside them before they can be trusted.

## 1. Groq (the AI)

| Setting | What to put | Notes |
|---|---|---|
| `GROQ_API_KEY` | The paid key | From the Groq console, under API keys. |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | The main model, as today. |
| `QUESTION_CHECK_MODEL` | `openai/gpt-oss-120b` | Scored 12 of 12 where 20b scored 10–11. |
| `LIVE_ANALYSIS_SPEED` | `standard`, then `fast` | `fast` analyses after every customer line instead of every 30 seconds. |
| `LIVE_ANALYSIS_WORKERS` | `16`, or about one per 10 calls in progress | How many calls are analysed at the same time; see section 8. |
| `SUMMARY_PROVIDER` | `llm` | `rule_based` writes placeholder descriptions, which the reports' root causes leave out. |

**Test after filling in**

1. Start the backend and replay one recording with **Upload test audio** on
   the Live Call page. Complaints, tone per line and a suggested question
   should appear, and a summary after the call.
2. Set `LIVE_ANALYSIS_SPEED=fast`, restart, replay the same recording. The
   complaints and the question should follow each customer line within a few
   seconds instead of up to 30.
3. Watch the Groq console's usage for that one call.

**What fast costs.** A 2-minute call at the standard setting makes about
4 analyses and uses about 13,000 tokens. With `fast`, a call with 15
customer lines makes up to 15 analyses, so expect roughly 3 to 4 times the
tokens per call. This is an estimate from the request sizes, not a
measurement: step 3 gives the real figure.

**Malformed answers.** Once in three real answers, the complaint detector
returned malformed output. Such an answer is now asked for once more (the
same for sentiment, escalation and the combined live answer), and one bad
item no longer costs the rest of the answer. This is tested with stand-in
answers only, not yet seen on a real call. If a call ends with fewer
complaints than were clearly raised, look for "Unusable LLM" in the backend
log: it shows how the answer began. The metric `llm_unusable_answers_total`
counts answers recovered by the second request and answers dropped.

## 2. Sarvam (speech to text)

| Setting | What to put | Notes |
|---|---|---|
| `SARVAM_API_KEY` | Your key | Already in use locally. |
| `SARVAM_STT_MODE` | `codemix` | Keeps English words in English letters inside Tamil and the others. |

**Test when the other-language recordings arrive**

Telugu, Kannada and Malayalam have never been run; Tamil–English once.
Label a few recordings per language and measure them (section 7). Speech
accuracy for these languages is unknown until then.

## 3. Plivo (phone calls)

| Setting | What to put | Notes |
|---|---|---|
| `TELEPHONY_PROVIDER` | `plivo` | |
| `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN` | From the Plivo console | The token also signs the webhooks. |
| `PLIVO_PUBLIC_BASE_URL` | `https://<your host>` | Must match the address Plivo calls exactly: the signature is computed over it. |
| `PLIVO_STREAM_BASE_URL` | `wss://<your host>` | Same host, `wss`. |
| `PLIVO_VALIDATE_SIGNATURES` | `true` | Production refuses to start otherwise. |
| `TELEPHONY_STREAM_AUTH_REQUIRED` | `true` | |
| `PLIVO_STREAM_AUDIO` | `l16_16k` | Best transcription. |
| `PLIVO_ICR_DIAL_TARGETS` | One fallback number or SIP address | Rung only for a call whose location has nobody to ring. Production refuses to start when it is empty. |
| `PLIVO_ICR_CALLER_ID` | Optional | The number executives see; by default the caller's. |

**In the Plivo console**, on the application your numbers use:

- Answer URL: `https://<your host>/api/v1/telephony/plivo/answer` (POST)
- Hangup URL: `https://<your host>/api/v1/telephony/plivo/status` (POST)

**In the app**, under Administration:

1. Add each service centre as a **Location** with the Plivo number its
   customers dial.
2. Give each executive a **name**, a **location** and a **dial target** (the
   phone number or `sip:` address of their phone).

**Tests, in this order**

| # | Do this | Expect | Status |
|---|---|---|---|
| 1 | Call a location's number from a mobile. | The call appears on Live Calls; an executive's phone rings. | **Unverified**: webhook signature on a real request. |
| 2 | An executive answers. | The call shows that executive and the location. | **Unverified**: the field names of Plivo's dial callback (`DialAction`, `DialBLegTo`, `DialALegUUID`). If the executive stays "Not recorded", look for `/telephony/plivo/dial` in the log and compare the fields Plivo sent. |
| 3 | Talk for a minute, both sides. | Customer and executive lines are labelled correctly, with a tone on customer lines. | **Unverified**: two separate tracks from a real call. |
| 4 | Hang up. | The call completes within a few seconds and gets a summary. | |
| 5 | Unplug the network mid-call, or kill the call from the Plivo console. | The call is completed by the sweep within about 12 minutes (`STALE_CALL_IDLE_SECONDS` + `STALE_CALL_SWEEP_INTERVAL_SECONDS`). | **Unverified** on a real call. |
| 6 | An executive dials a customer through Plivo from their own dial target. | The call is recorded as **Outgoing**, under that executive; the customer sees the location's number; the roles are the right way round. | **Unverified**: the whole outgoing flow. |

A call started through Plivo's API (a dialler) is not treated as outgoing:
there is no dialler in this system.

## 4. SMS gateway (the customer's summary text)

| Setting | What to put | Notes |
|---|---|---|
| `CUSTOMER_SUMMARY_ENABLED` | `true` | **This sends real texts.** Leave `false` until the test below. |
| `CUSTOMER_SUMMARY_DELIVERY_PROVIDER` | `sms_gate` | |
| `SMS_GATE_USERNAME`, `SMS_GATE_PASSWORD` | From the SMS Gateway app | |
| `SMS_GATE_URL` | Leave as it is unless you host the gateway yourself | |
| `SMS_GATE_SIM_NUMBER` | Optional: which SIM sends | |
| `CUSTOMER_SUMMARY_CONSENT_REQUIRED` | `true` | A customer without consent on record gets nothing. |

**Test after filling in**

1. Put **your own number** in the CRM file as a customer with consent.
2. Replay one recording with that number as the caller. You should receive
   one text.
3. Open the call's page: the delivery should show as sent, once.
4. **Unverified**: that the gateway refuses a repeated send of the same
   message rather than delivering it twice. Check that you received exactly
   one text even if the backend was restarted during step 2.

For any other check, start the backend with the `backend-test-audio` launch
configuration, which turns customer texts off.

## 5. Call recordings

Off by default. Recording calls needs the customer's consent: decide that
before turning it on.

| Setting | What to put | Notes |
|---|---|---|
| `RECORDING_ENABLED` | `true` | |
| `RECORDING_ENCRYPTION_KEY` | A new key | Make one from `backend/` with `python -c "from app.services.recording_archive import generate_key; print(generate_key())"`. |
| `RECORDING_DIR` | A folder with room | About 1.9 MB per minute per side: 3.8 MB a minute for a two-sided call. |
| `RECORDING_RETENTION_DAYS` | `90`, or your policy | Recordings are removed after this. |

**Before relying on it**

- **Keep a copy of the key somewhere safe.** If it is lost or changed, no
  stored recording can be read.
- With more than one backend server, `RECORDING_DIR` must be a folder they
  all share.
- Archive to cloud storage and backups are **not built**. Back the folder
  up yourself until they are.
- If a call's audio stream drops and reconnects, only the first part is
  recorded.

**Test after filling in**

1. Make a call (or replay a recording), end it, and open its page as a
   supervisor. "Call recording" should show its length and keep-until date.
2. Press **Load recording** and listen. A two-sided call has the caller on
   the left and the executive on the right. **Unverified** on a real
   two-sided call.
3. Look in `RECORDING_DIR`: the file must not open in an audio player.

## 6. Production settings

`APP_ENV=production` makes the backend refuse to start on unsafe settings
and say what to fix. See `DEPLOYMENT.md` for the full first deployment. The
ones people forget:

| Setting | What to put |
|---|---|
| `AUTH_SECRET_KEY` | At least 32 random characters. |
| `CORS_ALLOWED_ORIGINS` | The web app's address, not `*`. |
| `LIVE_STATE_STORE_PROVIDER`, `CALL_MAPPING_STORE_PROVIDER` | `redis` with more than one backend server. |
| `ROLE_PROVIDER` | `session`. |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` | Set for the first start, then clear. |

Run the migrations (`alembic upgrade head`; the Docker image does it at
start) and install the two libraries added recently (`reportlab`,
`cryptography`; both are in `requirements-api.txt`).

## 7. Measuring against the SRD's targets

**Accuracy.** Label a set of recordings and run, from `backend/`:

```bash
python -m scripts.measure_accuracy eval/ --question-outcomes --report accuracy-report.md
```

The label format is in `backend/scripts/accuracy_label_template.json` and
the script's own help. It reports speech recognition (95%), complaint
categories (92%), several categories on one call (88%), sentiment (90%) and
question relevance (85%) as measured, out of how many, and whether each
meets its target. Question relevance comes from the Accept and Skip buttons
and shows "not enough data yet" below 30 choices. The run uses the real
speech recogniser and AI, so it costs credits.

Aim for at least 30 labelled calls per language before reading the result
as more than a first impression.

A first try on the five existing test recordings, on 10 October 2026, with
labels written from their stored transcripts (so speech recognition itself
was not measured): complaint categories 15 of 17 right (88%), all
categories found on 2 of 3 calls with several, sentiment the exact label on
3 of 5 calls and the right side (negative or not) on 5 of 5. Five calls and
one person's labels: an illustration of the report, not a result.

**Load.** From `backend/`:

```bash
python -m scripts.load_test --calls 50 --seconds 60
```

This costs nothing: it starts its own backend with stand-ins for the speech
recogniser and the AI and in-memory storage, and touches no real service.
See section 8 for what it found on the development laptop.

**Not measured by either tool:** the SRD's speed targets with the real
providers (transcript within 2 s, categories within 3 s, a question within
1.5 s), 99.9% availability, failover and disaster recovery, and penetration
testing.

## 8. What the load test found

Run on the development laptop on 10 October 2026: one backend process,
two-sided calls of 60 seconds, the stand-in speech recogniser answering in
0.4 s and each stand-in AI request in 1 s, storage in memory.

| Calls at once | Calls completed | Speech transcribed | First analysis (worst) | Live Calls page (worst) | Kept up |
|---|---|---|---|---|---|
| 25 | 25 | all | 6 s | 0.2 s | yes |
| 50 | 50 | all | 6 s | 0.3 s | yes |
| 100 | 100 | all | 13 s | 0.3 s | yes |
| 200 | 200 | all | 31 s | 2.3 s | no: the analysis fell just behind |

**What it found and fixed.** Before the fix in this stage, only four calls
at a time got their live analysis (complaints, tone, suggested questions):
with 25 or 50 calls, every other call saw its first complaint only after it
had ended (62 s into a 60 s call). A call waiting out its 30-second interval
was holding one of four workers. Waiting calls now hold no worker, and the
number of workers is a setting (`LIVE_ANALYSIS_WORKERS`, default 16).

**What limits it now.** At 200 calls, transcription still kept up; the
analysis was the first thing to fall behind, because 16 workers cannot get
round 200 calls inside 30 seconds when each analysis takes 3 seconds. Raise
`LIVE_ANALYSIS_WORKERS` to about one per 10 calls in progress. With the
real AI the ceiling is the provider's rate limit, not this setting.

**What it does not show.**

- 500 calls at once. The laptop was not asked to try; run it on the real
  server.
- The real speech recogniser, AI and PostgreSQL. Their speed and limits
  replace the stand-ins' 0.4 s and 1 s.
- More than one backend process.

**The Live Calls page was reworked for 500 calls after this test** (the
figures in the table are the old page's; it took 2.3 s at 200 calls and
listed at most 100). It now makes the same four reads however many calls
are in progress, loads no transcript, writes nothing, and shows 50 calls a
page, most urgent first, with filters by location, executive, tone and
alert. Many open pages share one read every `LIVE_CALLS_CACHE_SECONDS`
(default 2). Alerts are kept up to date in the background every
`LIVE_ALERT_SWEEP_SECONDS` (default 10). Tests show the number of reads is
the same for 5 and for 500 calls; the page's real load time at 500 calls
on your PostgreSQL and Redis has not been measured (SRD: under 3 s). Apply
migration 0020 (an index the page's query uses).

## 9. In the SRD and not built

- Call status "On Hold".
- Cloud archive and backups of recordings.
- A real CRM connection (customers come from a file), WhatsApp delivery,
  failover and disaster recovery, penetration testing: set aside by decision.

## 10. Known weak spots

- **Speaker roles on a single mixed stream** are sometimes wrong. Separate
  Plivo tracks (section 3, test 3) should not have this.
- **The first call right after a backend restart** can end with no
  transcript if it is shorter than the speech models' warm-up (under a
  minute). Wait a minute after a restart before the first test call.
- **Coverage scores** are meaningful only for calls made after the
  "asked about" check was added (10 October 2026); earlier calls read 0%.
- **Root causes in reports** group complaints by shared words, so the same
  cause in different words stays in separate groups.
- **PDF exports** print only Latin script; use Excel or CSV when names are
  in Tamil or another Indian script.
- **Alerts** (not asked about, poor audio) are checked when a call is
  analysed and by a background sweep every `LIVE_ALERT_SWEEP_SECONDS`
  (default 10), so they can be up to 10 seconds late on any screen.
