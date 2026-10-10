# Deploying Multilingual Call Intelligence

## What runs

| Service    | Image                  | Role                                                           |
|------------|------------------------|----------------------------------------------------------------|
| `web`      | `frontend/Dockerfile`  | nginx: serves the web app, proxies `/api` (incl. WebSockets)    |
| `backend`  | `backend/Dockerfile`   | FastAPI API, telephony webhooks + media streams, background jobs |
| `postgres` | `postgres:16`          | All business data                                              |
| `redis`    | `redis:7`              | Live state shared by API instances, telephony call mapping      |

The browser, Plivo's webhooks and Plivo's media stream all reach the API
through `web`, so one public host name serves everything.

## First deployment

Run these from the repository root:

```bash
cp deploy/.env.production.example deploy/.env.production
# Replace every "replace-with-..." value: POSTGRES_PASSWORD, AUTH_SECRET_KEY,
# CORS_ALLOWED_ORIGINS, BOOTSTRAP_ADMIN_EMAIL/PASSWORD and your provider keys.
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production config --quiet
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d --build
```

`deploy/.env.production` is git-ignored; only the example (placeholders) is
committed. The file is used twice: `--env-file` fills in the compose file's
own variables (`POSTGRES_*`, `WEB_PORT`, `INSTALL_DIARIZATION`), and the
backend service loads it as its environment (`env_file`). The compose file
itself sets `APP_ENV=production`, `DATABASE_URL`, `REDIS_URL` and the Redis
store providers, so those need not be in the file.

The root `docker-compose.yml` is for local development only (a database
with a default password); never use it in production.

- **Migrations** run automatically when the backend container starts
  (`alembic upgrade head`). Set `RUN_MIGRATIONS=false` to run them yourself.
- **First admin**: with `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD`
  set, an admin is created while the user table is empty. Sign in, create
  the real accounts under **Administration**, then clear both variables.
  Alternatively, from the backend container:

  ```bash
  docker compose -f deploy/docker-compose.prod.yml exec backend python -m app.cli create-user --email you@dealer.com --role ADMIN
  ```

  (`reset-password` and `list-users` work the same way.)
- **TLS**: put a TLS-terminating proxy or load balancer in front of `web`.
  Plivo needs `https://` webhooks and a `wss://` media stream.

With `APP_ENV=production` the API refuses to start on unsafe settings (weak
`AUTH_SECRET_KEY`, missing database, wildcard CORS, telephony without
webhook signatures or stream tokens, a Redis live-state store with an
in-memory call mapping, any `replace-with-...` placeholder left from the
example file) and lists what to fix.

## Plivo

In the Plivo application, set:

- Answer URL: `https://<host>/api/v1/telephony/plivo/answer` (POST)
- Hangup/status URL: `https://<host>/api/v1/telephony/plivo/status` (POST)

`PLIVO_PUBLIC_BASE_URL=https://<host>` must match exactly, because webhook
signatures (Plivo's V3 scheme) are computed over that URL and the form
fields. `PLIVO_STREAM_BASE_URL=wss://<host>`.

Set `PLIVO_ICR_DIAL_TARGETS` to the ICR's phone number (E.164) or SIP
endpoint (`sip:icr@...`). Several, comma-separated, ring together. The answer
XML then starts a background stream of both sides of the call
(`audioTrack="both"`, 16 kHz linear PCM by default, see `PLIVO_STREAM_AUDIO`)
and dials the ICR. The customer and the
ICR arrive as separate tracks, which makes speaker roles exact.
`PLIVO_ICR_CALLER_ID` sets the number the ICR sees (by default, the
caller's). Production refuses to start with telephony on and no dial target.

Plivo's docs do not state the byte order of 16 kHz linear PCM (`l16_16k`);
the backend reads it as little-endian. Check the first real call's transcript:
if it is empty or nonsense, set `PLIVO_STREAM_AUDIO=mulaw_8k` and report it.

With `POST_CALL_RETRANSCRIPTION_ENABLED=true`, the call's audio is kept in
memory until post-call processing transcribes it again in long windows and
replaces the live transcript (about double the ASR cost). The recording lives
on the API instance that served the media stream; if post-call processing runs
on another instance, the live transcript is kept.

Every media stream URL carries a signed token for that one call
(`TELEPHONY_STREAM_TOKEN_TTL_SECONDS`, default one hour to connect); the
stream endpoint refuses connections without it.

## Scaling

Run **one uvicorn worker per container** and scale by adding backend
containers. Everything that must be shared between instances is:

- persistent data in PostgreSQL (calls, transcripts, complaint coverage,
  escalations, summaries, learning data);
- in Redis (`LIVE_STATE_STORE_PROVIDER=redis`): open media streams, speaker
  roles, job locks and job status, and each active call's latest live
  analysis (sentiment, next-question suggestion, service estimate) with a
  revision number. The live analysis expires after
  `LIVE_ANALYSIS_TTL_SECONDS` without new speech (default 4 hours) and is
  dropped when the call completes; transcripts and audio are never put in
  Redis;
- the Plivo call mapping in Redis (`CALL_MAPPING_STORE_PROVIDER=redis`).

So a browser's poll or WebSocket can land on any instance and still see the
analysis produced by the instance that processed the speech. Each open
live-call WebSocket checks the call's revision in Redis every
`LIVE_CALL_PUSH_INTERVAL_SECONDS` (one small `GET`) and pushes the new
analysis when it changes. If Redis is briefly unavailable, calls continue
and reads fall back to what PostgreSQL holds (coverage and escalations,
without the live sentiment/suggestion) until it is back.

Browser live-call WebSockets do not carry the access token in the URL. The
web app first calls `POST /api/v1/calls/{call_id}/live-token` (with the
normal `Authorization` header) and connects with the returned ticket, which
is bound to the user and the call, expires after
`LIVE_CALL_WS_TOKEN_TTL_SECONDS` (default 60) and works once (enforced
through Redis across instances).

A status webhook that lands on a different instance than the call's media
stream waits (up to 30 s) for that stream to finish its final audio before
completing the call. A media stream that reconnects to another instance
keeps its speaker roles.

The load balancer should keep WebSocket connections open for the length of
a call (the bundled nginx allows 3 hours).

## Post-call repair

Post-call processing (summary, complaint close-out, customer message,
emerging-complaint discovery) normally runs right after a call ends.
Emerging-complaint discovery runs in the background, never blocks call
completion, starts at most every
`EMERGING_COMPLAINT_DISCOVERY_MIN_INTERVAL_SECONDS` (default 300), runs on
one instance at a time, reads at most `EMERGING_COMPLAINT_DISCOVERY_MAX_CALLS`
recent calls, and is skipped when no completed call changed since the last
run, so an LLM discovery provider is not asked the same question twice. If it
doesn't finish (a crash, a provider outage), the repair sweep retries it:

- every `POST_CALL_REPAIR_INTERVAL_SECONDS` (default 300; `0` disables it),
- once a call has been waiting `POST_CALL_REPAIR_MIN_AGE_SECONDS`,
- with exponential backoff, up to `POST_CALL_REPAIR_MAX_ATTEMPTS` times.

A call stopped by the LLM's rate limit does not use up an attempt. All
repairs then wait until the LLM said the limit clears, at the latest
`POST_CALL_REPAIR_RATE_LIMIT_RETRY_SECONDS` (default 3600), and a call is
given up on once it has waited `POST_CALL_REPAIR_RATE_LIMIT_GIVE_UP_SECONDS`
(default 86400). So calls made after the day's LLM quota is used get their
summary when the quota returns.

A Redis lock ensures that only one instance sweeps at a time. Supervisors
and admins can see waiting calls and retry them under **Administration →
Post-call processing**, or from a call's post-call analysis page.

## Customer file (CRM)

With `CRM_PROVIDER=json_file`, production refuses to start if
`CRM_JSON_PATH` is missing or the file cannot be read.

- An invalid customer in the file is skipped and logged as a warning; the
  other customers still load.
- A phone number shared by two customers matches neither automatically: the
  ICR identifies the caller by hand.
- The file is read again within a few seconds of being changed (for example
  when a customer withdraws consent). If the new version cannot be read, the
  previous one stays in use and an error is logged.
- Setting a call's customer by hand is logged with the user, the call and the
  customer ids (phone numbers show their last four digits only). On a
  completed call only a supervisor or admin can change the customer.

## Customer summary texts

With `CUSTOMER_SUMMARY_ENABLED=true` the app refuses to start in production
unless a real delivery provider is set (`sms_gate` with `SMS_GATE_USERNAME`
and `SMS_GATE_PASSWORD`).

- Each call's text is recorded before it is sent, so two runs for the same
  call (a retry overlapping the first attempt) send it once.
- A text that failed, or whose customer could not be looked up because the
  CRM was unreachable, is tried again every
  `CUSTOMER_SUMMARY_RETRY_INTERVAL_SECONDS` (default 300), up to
  `CUSTOMER_SUMMARY_MAX_ATTEMPTS` attempts (default 5), and only within 24
  hours of the call.
- An SMS longer than `CUSTOMER_SUMMARY_SMS_MAX_PARTS` parts (default 3: about
  450 English or 200 Tamil characters) is sent without its greeting line if
  that makes it fit, otherwise replaced by a short standard message.
- "Sent" means the SMS gateway accepted the text; the phone sends it
  afterwards, and its delivery reports are not read.

## Stale calls

A phone call is completed by Plivo's hangup webhook. If that webhook is
missed (the backend was restarting, or the hangup URL is not set in Plivo),
a sweep completes the call instead, so it still gets its summary:

- every `STALE_CALL_SWEEP_INTERVAL_SECONDS` (default 120; `0` disables it),
- once the call's media stream is closed and nothing has been said for
  `STALE_CALL_IDLE_SECONDS` (default 600).

Only calls started by Plivo are swept, never manual ones. Each completion is
logged as a warning, as is a hangup webhook that matches no call.

## Monitoring

| Endpoint        | Use                                                                 |
|-----------------|----------------------------------------------------------------------|
| `/health/live`  | Liveness: the process answers. Used by the container `HEALTHCHECK`. |
| `/health/ready` | Readiness: database and Redis answer; `503` otherwise.              |
| `/metrics`      | Prometheus text format. Protect it with `METRICS_TOKEN`.            |

`/metrics` is not proxied by `web`; scrape the backend on port 8000 from
your monitoring network. It includes:

- `http_requests_total{method,route,status}` and `http_request_duration_seconds`;
- `calls{status}`, `escalations_open{level}`, `complaints_open{kind}`;
- `telephony_streams_open`, `post_call_unprocessed_calls`, `post_call_repairs_total{outcome}`.
- `background_job_overdue_intervals{name}`: time since each background job's last
  run ended, in its own intervals (about 1 when it runs on time).

- `dependency_up{dependency}` (the `/health/ready` checks);
- live calls: `live_audio_chunks_total{stream,outcome}`,
  `live_audio_chunk_processing_seconds`,
  `ai_provider_request_duration_seconds{provider}` and
  `ai_provider_errors_total{provider}` (asr, language, diarization, llm), and
  `speaker_roles_decided_total{method}` (track, content, llm, other_speaker).

### Prometheus, Grafana and e-mail alerts

`deploy/docker-compose.prod.yml` also runs the monitoring stack, configured
in `deploy/monitoring/`:

| Service      | What it does                                                     |
|--------------|------------------------------------------------------------------|
| prometheus   | Scrapes the backend every 15 s (sends `METRICS_TOKEN`); keeps 30 days (`PROMETHEUS_RETENTION`). |
| alertmanager | E-mails alerts to `ALERT_EMAIL_TO` through `SMTP_SMARTHOST` (STARTTLS), critical ones repeated hourly, others every 4 h, plus a "resolved" mail. See [E-mail alerts](#e-mail-alerts). |
| grafana      | Published on `GRAFANA_PORT` (3000). Sign in with `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`. Opens on the **Multilingual Call Intelligence** dashboard. |

Set the monitoring values in `deploy/.env.production` (see the example
file). Keep Grafana behind your TLS proxy or on an internal network.

Alert rules (`deploy/monitoring/prometheus/alerts.yml`):

| Alert | Fires when |
|---|---|
| BackendDown (critical) | `/metrics` cannot be scraped for 2 min |
| DependencyDown (critical) | a `/health/ready` dependency fails for 2 min |
| AsrFailing (critical) | more than 20% of speech-to-text calls fail for 10 min |
| HighServerErrorRate | more than 5% of requests return 5xx for 10 min |
| SlowApi | API p95 above 2 s for 15 min |
| AsrSlow / DiarizationSlow | ASR p95 above 5 s / diarization p95 above 3 s |
| LlmFailing | more than 20% of LLM calls fail (usually Groq 429s: a call uses about 13,000 tokens; see "LLM usage and Groq limits" in the README) |
| LiveChunksFailing / LiveTranscriptLagging | more than 20% of chunks fail / chunk-to-transcript p95 above 8 s |
| PostCallProcessingStuck | calls without a post-call summary for 30 min |
| PostCallRepairGaveUp | the repair sweep gave up on a call |
| BackgroundJobNotRunning | a background job (repair, stale calls, summary texts) has not finished a run for 3 of its intervals, for 10 min |
| CriticalEscalationOpen | a critical escalation is unacknowledged for 15 min |

The thresholds are starting points. Tune them once you know real call
volumes.

#### E-mail alerts

Each e-mail's subject names the alert and its severity, e.g.
`[Call Intelligence] FIRING CRITICAL: BackendDown - The backend is not
answering /metrics`. The body lists every firing alert with its "what to
check" description and start time (UTC), and links to the Grafana dashboard
when `GRAFANA_URL` is set. When the alert clears, a "RESOLVED" e-mail
follows. The layout is in `deploy/monitoring/alertmanager/templates/email.tmpl`.

SMTP settings in `deploy/.env.production`:

| Provider | `SMTP_SMARTHOST` | `SMTP_USERNAME` / `ALERT_EMAIL_FROM` | `SMTP_PASSWORD` |
|---|---|---|---|
| Gmail | `smtp.gmail.com:587` | your Gmail address | an App Password (myaccount.google.com/apppasswords; needs 2-Step Verification), without spaces |
| Yahoo | `smtp.mail.yahoo.com:587` | your Yahoo address | an app password (login.yahoo.com/account/security → Generate app password) |
| Other | `host:587` | as your provider says | as your provider says |

Your normal account password does not work for Gmail or Yahoo. Keep
`SMTP_REQUIRE_TLS=true` for any real mail server.

**Try it locally first (no real e-mail).** The local monitoring stack runs
the same Alertmanager config and template but sends to
[Mailpit](https://mailpit.axllent.org/), a mail catcher that keeps every
message and relays nothing:

```bash
docker compose -f deploy/monitoring/local/docker-compose.yml up -d
```

```bash
sh deploy/monitoring/send-test-alert.sh
```

Open http://localhost:8025. The test e-mail arrives in about 30 s.
`send-test-alert.sh critical` fires a critical one, and
`send-test-alert.sh --resolve` (or `--resolve critical`) clears it, which
sends the "resolved" e-mail. The script only talks to an Alertmanager on
this machine. The real rules also fire locally: stop the backend for 2
minutes and a `BackendDown` e-mail appears in Mailpit.

**Test production on purpose.** This sends a real e-mail to `ALERT_EMAIL_TO`:

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production exec alertmanager amtool alert add alertname=TestAlert severity=warning test=true --annotation=summary="Test alert: ignore this message" --annotation=description="Checking that alert e-mails arrive." --alertmanager.url=http://localhost:9093
```

If nothing arrives, the reason is in the Alertmanager log (look for
`Notify for alerts failed`; `535` means a wrong username or app password):

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production logs alertmanager
```

#### Checking the configuration

CI runs these checks on every push. Run them yourself after editing the
monitoring files. They only read the files and send nothing.

Prometheus config and alert rules:

```bash
docker run --rm --entrypoint /bin/sh -v "$PWD/deploy/monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro" -v "$PWD/deploy/monitoring/prometheus/alerts.yml:/etc/prometheus/alerts.yml:ro" prom/prometheus:v2.53.2 -c "touch /tmp/metrics_token && promtool check config /etc/prometheus/prometheus.yml"
```

Alertmanager config and e-mail template, rendered as at start-up:

```bash
docker run --rm --entrypoint /bin/sh -e ALERT_EMAIL_TO=oncall@example.com -e SMTP_SMARTHOST=smtp.example.com:587 -v "$PWD/deploy/monitoring/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.template.yml:ro" -v "$PWD/deploy/monitoring/alertmanager/templates:/etc/alertmanager/templates:ro" -v "$PWD/deploy/monitoring/alertmanager/entrypoint.sh:/etc/alertmanager/entrypoint.sh:ro" prom/alertmanager:v0.27.0 /etc/alertmanager/entrypoint.sh --check
```

Logs go to stdout. `LOG_FORMAT=json` writes one JSON object per line. Each
request logs method, path, status and duration, and every log line carries
a `request_id`. It is returned to clients as `X-Request-ID` (an incoming
`X-Request-ID` is reused), so a user's error report can be traced in the
logs.

## Backups

Back up the `postgres_data` volume (e.g. `pg_dump` on a schedule). Redis
holds only live, reconstructible state.
