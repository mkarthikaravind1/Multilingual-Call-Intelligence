# Go-live checklist

What to fill in when each access arrives, and the test to run straight after.
Everything is set in `.env` at the repository root (locally) or
`deploy/.env.production` (on the server). Restart the backend after a change.

Nothing here has been run against the real services yet unless it says so.
Items marked **Unverified** were built to the provider's documentation and
need the test beside them before they can be trusted.

Where every SRD requirement stands (met, waiting on an access, or not met
and why) is in `SRD-STATUS.md`, checked on 11 October 2026.

## 0. The order to work in when the accesses arrive

Each step proves the rows of `SRD-STATUS.md` named beside it.

1. **Paid Groq key** (section 1). Fill it in, set `LIVE_ANALYSIS_SPEED=fast`
   and replay one test recording. A complaint should appear about a second
   after its line, with no long waits. Proves row 45.
2. **Plivo** (section 3). The three tests there, in order: an incoming
   call, an outgoing call, and a two-sided call as separate tracks. Proves
   rows 25, 26, 93, 101, 121 and shows Incoming and Outgoing on screen.
3. **Recording** (section 5), if you have decided to record. One real call
   with `RECORDING_ENABLED=true`. Proves row 57.
4. **Storage bucket** (section 6, "Data safety"). Its five tests. Proves
   rows 61 and 65. Restore one backup into an empty database while there.
5. **HTTPS** in front of the web app (`DEPLOYMENT.md`, "First deployment").
   Plivo needs it for step 2 on a server. Proves row 64.
6. **SMS gateway** (section 4), on a number of your own first.
7. **Recordings in Telugu, Kannada and Malayalam**, and written-down
   transcripts for at least 30 calls per language (section 7). Proves rows
   1, 47 to 50, 109 and 113.
8. **Real executives for a week.** Their Accept and Skip choices give the
   question relevance figure (row 51) and tell you whether the screen needs
   training (rows 97, 114).
9. **Real servers.** Rebuild the Docker image (unproven since `pg_dump`,
   the S3 library and the recordings volume were added), then the load test
   of section 7 against it. Proves rows 96, 104 to 106 and 116.

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

### Changing the model, or fine-tuning one

Nothing in this system trains a model: the language model is Groq's and
the speech model is Sarvam's. Two things are in your hands.

**Switching to another model** (a newer one, or one you have fine-tuned):

1. Label a set of calls once (section 7) and run the accuracy script with
   the current model. Keep the report.
2. Change `GROQ_MODEL` (and `QUESTION_CHECK_MODEL` if you want) and restart
   the backend.
3. Run the same script on the same calls. Compare the two reports: keep
   the new model only if it is no worse on categories, tone and questions.
4. Watch `llm_unusable_answers_total` for a day: a model that often answers
   in the wrong shape shows up there first.

**Fine-tuning a model of your own.** The AI Improvement Center has a
"Training data" section (admins only) that downloads every AI output a
person has corrected or judged, with the call's transcript, as a JSON
Lines file. Lines with a known right answer carry a `messages` list in the
shape chat-model fine-tuning takes. Groq does not offer fine-tuning on its
hosted models today, so this needs a provider or a server of your own that
does; the model it produces must then be reachable the way Groq's are, or
a new connection written for it. A few hundred judged outputs per task is
the least worth trying. The file holds what customers said: treat it like
the recordings.

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
- Recordings are copied off the server and checked daily once the copies
  below are turned on ("Data safety"). Until then, back the folder up
  yourself.
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
start) and install the libraries added recently (`reportlab` 4.5 with
`uharfbuzz`, `cryptography`, `boto3`; all are in `requirements-api.txt`).

### Data safety: copies off the server, backups, replication

All off by default. `DEPLOYMENT.md` ("Backups", "Replication") has the full
steps; these are the settings.

| Setting | What to put | Notes |
|---|---|---|
| `ARCHIVE_STORAGE_PROVIDER` | `s3` | Any S3-compatible bucket. `local` (a folder) to try it first. |
| `ARCHIVE_S3_BUCKET`, `ARCHIVE_S3_ACCESS_KEY_ID`, `ARCHIVE_S3_SECRET_ACCESS_KEY` | From the storage account | A key that can read, write and delete in that bucket only. |
| `ARCHIVE_S3_ENDPOINT_URL`, `ARCHIVE_S3_REGION` | From the storage account | Endpoint empty for Amazon S3. |
| `ARCHIVE_ENCRYPTION_KEY` | A new key | Made like the recording key. Transcripts and backups are encrypted with it. |
| `BACKUP_ENABLED` | `true` | A daily encrypted database backup into the same bucket, kept `BACKUP_RETENTION_DAYS` (14). |
| `REPLICATION_PASSWORD` | A long random value | Only with `deploy/docker-compose.replica.yml`. |

**Before relying on it**

- **Keep `ARCHIVE_ENCRYPTION_KEY` and `RECORDING_ENCRYPTION_KEY` outside
  the bucket and outside the server.** Without them nothing in the bucket
  can be read.
- **A real bucket has not been tried.** The S3 code is tested against a
  stand-in that answers like S3, and the whole path against a folder. The
  first test below is the proof.
- **Restore a backup once** (`DEPLOYMENT.md`, "Restoring") before you
  count on it.
- **The Docker image has not been rebuilt here** since `pg_dump`, the S3
  library and the recordings volume were added to it.
- The daily recording check compares each file with its checksum, and each
  copy by its size. A copy changed inside the bucket without its size
  changing is found only when it is needed for a restore.
- Transcript copies are kept for good: retention removes recordings and
  their copies, not transcripts.

**Test after filling in**

1. Open Administration > Data safety. "Copies off the server" should read
   On and name the bucket.
2. Finish a call, wait a quarter of an hour (or press **Copy now**), and
   look in the bucket: `transcripts/<year>/<month>/<call>.json.enc`, and
   `recordings/...` if recording is on. Neither should open as text or
   audio.
3. Press **Back up now**. A file should appear under `backups/` and the
   page should show its size. Then restore it into an empty database.
4. With recording on, press **Check now**: the page should read Intact.
5. With the replica: the query under "Replication" in `DEPLOYMENT.md`
   should show one row with `streaming`.

### Audit log and AI log

Both are on without any setting, and administrators read them under
Administration > Logs. Decide these before real customers call:

| Setting | Default | Notes |
|---|---|---|
| `AUDIT_LOG_RETENTION_DAYS` | `365` | Who did what, and when. Holds no request content. |
| `AI_LOG_MODE` | `full` | `full` keeps every prompt and answer, which contain what the customer said. `details` keeps everything but that text. `off` keeps nothing. |
| `AI_LOG_RETENTION_DAYS` | `30` | Keep it short while the mode is `full`. |

- **The AI log holds customer speech** in `full` mode. Only administrators
  can read it, and each time one opens it (or one request's text) is in the
  audit log. If your policy does not allow keeping it, set `details`.
- **Space.** A one-line test call made 7 requests and stored about 18 KB.
  A two-minute call is estimated at about 60 KB (from its token count, not
  measured), so 10,000 calls a month is roughly 0.6 GB before the 30-day
  clean-up. `LIVE_ANALYSIS_SPEED=fast` makes more requests per call and
  will store several times that.
- **Token counts per call** are now real figures from Groq: open a finished
  call as an administrator and follow "AI log for this call".

**Test after filling in**

1. Sign in, change something (rename a location, say), and open
   Administration > Logs > Audit log. Both should be listed with your name.
2. Make a call, end it, and open "AI log for this call" on its page. Each
   request should show its task, time taken and tokens; "Show text" shows
   what was asked and answered.

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

**Speed, as measured on 11 October 2026** in five replays on this laptop
with the real speech recogniser and the free Groq key (times read off the
screen's data every 2 seconds, so each is good to about 2 seconds):

- A transcript line appeared about 1 to 3 seconds after the speaker
  stopped. The SRD asks for under 2 seconds: not met for longer lines,
  because speech is transcribed at each pause, not as it is spoken.
- With `LIVE_ANALYSIS_SPEED=fast`, each analysis took about 1 second after
  the line was transcribed, and the complaint and its questions were on
  screen about 4 seconds after the customer finished speaking. The SRD
  asks for 3 seconds (categories) and 1.5 seconds (questions) from the end
  of the utterance: the category target is within reach on the paid key,
  the question target is not without a streaming speech recogniser.
- In the standard mode the analysis runs every 30 seconds, by decision.

**Not measured by anything here:** 99.9% availability, failover and
disaster recovery, and penetration testing.

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

## 9. In the SRD and not met

The full list, with the reason for each, closes `SRD-STATUS.md`. In short:

- **Set aside by decision:** a real CRM connection (customers come from a
  file), automatic failover and disaster-recovery testing, penetration
  testing.
- **Needs a streaming speech recogniser:** a transcript within 2 seconds
  and a question within 1.5 seconds of the end of an utterance.
- **Not done by this system:** training or retraining AI models. The
  models are Groq's and Sarvam's; what improves here is the instructions
  given to them. The reviewed corrections can be downloaded as a training
  file for the day you fine-tune a model of your own (section 1).
- **Outside the software:** a data-protection review, and a measured
  figure for data reliability.

Not in the SRD and built anyway: service estimates from a price list, the
customer's summary by SMS, and the AI Improvement Center.

## 10. Known weak spots

- **A management user sees what a finished call's page shows**: the
  transcript, the summary, the complaints, tone, escalation, service
  estimate and audit. Not the customer's name, phone or vehicle panel, not
  the recording, and nothing of a call still in progress. The summary and
  transcript can still contain a name the customer said aloud.

- **The audit log names the user by id.** The name shown is the user's
  name today; a changed name shows as the new one on old entries.
- **Both logs are written a moment after the event**, in the background. If
  the database is down or cannot keep up, entries are dropped rather than
  slowing a call, and counted in `log_entries_dropped_total` on `/metrics`.
  Entries still waiting when the backend is stopped are lost.
- **Background work is not in the audit log**: only requests made by a user
  or by the telephony provider. What the retention jobs remove is in the
  server log.
- **The address a request came from** is the proxy's unless the proxy
  passes the real one on (`proxy_headers` is on; the proxy must set
  `X-Forwarded-For`).

- **On Hold is what the executive marks in the web app** (Hold / Resume on
  the call screen). Plivo does not report a hold made on the handset: the
  call then stays "Connected" and hold music may be transcribed.

- **Speaker roles on a single mixed stream.** In five replays on
  11 October 2026 (three English, two Tamil-English, 56 lines) every line
  got the right speaker except where a quick reply was joined to the
  other person's line: "When did you notice it? The same evening itself."
  is stored as one line with one speaker. The speech recogniser gives
  timings per phrase, not per word, so such a line cannot be split.
  Separate Plivo tracks (section 3, test 3) do not have this. The opening
  lines, stored before the speakers are told apart, now get their speaker
  as soon as it is known.
- **The first call right after a backend restart** waits for the speech
  models (about a minute): its transcript appears late, all at once. A
  41-second call replayed straight after a restart kept all 9 lines and
  its summary; before, it lost them.
- **A call recorded in parts** (its audio stream dropped and came back) has
  its parts joined into one recording, without the silence in between. It
  is not transcribed again after the call (POST_CALL_RETRANSCRIPTION), as
  the parts cannot be lined up with the transcript: it keeps its live
  transcript.
- **The fast setting on the free Groq key.** One 41-second replay with
  `LIVE_ANALYSIS_SPEED=fast` made 14 AI requests (17,655 tokens) against 5
  to 9 in the standard mode, and the sixth live analysis waited 35 seconds
  for Groq's free limit. Each analysis itself took about 1 second, and the
  complaint and questions were on screen within about 4 seconds of the
  customer's line being transcribed. Use the fast setting with the paid
  key only.
- **Audit scores** are estimates by fixed rules (listed on the call's audit
  panel and on Reports > Performance); nobody listened to the call. Like the
  coverage score, they are meaningful only for calls made after the "asked
  about" check was added (10 October 2026): earlier calls score close to 0.
  "Tone got better or worse during the call" needs a tone per line, which
  calls from before 10 October 2026 do not have.
- **Coverage scores** are meaningful only for calls made after the
  "asked about" check was added (10 October 2026); earlier calls read 0%.
- **Root causes in reports** group complaints by a list of words that mean
  the same at a service centre (bill and invoice, late and delayed, car and
  vehicle, and so on). It is a word list, not understanding: the same
  cause put in quite different words still lands in separate groups, and
  the list is English.
- **PDF exports** print Tamil, Telugu, Kannada and Malayalam in bundled
  Noto Sans fonts (Google Fonts, SIL Open Font License; the licences are
  beside the fonts in `backend/app/assets/fonts`). Seen correct on a sample
  report by eye; I do not read these scripts, so have a native reader look
  once. Text in those scripts copied out of the PDF, or searched for in it,
  does not come back correctly: use Excel or CSV for that. Any other
  script (Hindi, say) is shown as `[...]` with a note. A rupee sign in
  Latin text is written "Rs".
- **E-mail alerts** were checked in Docker on 11 October 2026 with the
  local mail catcher: a test alert arrived with the right subject and
  template. The "resolved" e-mail (sent up to five minutes later) and a
  real mail server were not checked.
- **Phone and tablet.** Every page was opened at phone (375) and tablet
  (768) width and none scrolls sideways; wide tables scroll inside their
  own panel. This was a check for overflow, not a design review of each
  page, and a call in progress was not open during it.
- **Alerts** (not asked about, poor audio) are checked when a call is
  analysed and by a background sweep every `LIVE_ALERT_SWEEP_SECONDS`
  (default 10), so they can be up to 10 seconds late on any screen.
