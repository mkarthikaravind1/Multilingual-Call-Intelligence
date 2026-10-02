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
signatures are computed over that URL. `PLIVO_STREAM_BASE_URL=wss://<host>`.

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

A Redis lock ensures that only one instance sweeps at a time. Supervisors
and admins can see waiting calls and retry them under **Administration →
Post-call processing**, or from a call's post-call analysis page.

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

Suggested alerts: `/health/ready` failing, `post_call_unprocessed_calls > 0`
for more than 30 minutes, `post_call_repairs_total{outcome="gave_up"}`
increasing, and a rising rate of `http_requests_total{status=~"5.."}`.

Logs go to stdout. `LOG_FORMAT=json` writes one JSON object per line. Each
request logs method, path, status and duration, and every log line carries
a `request_id`. It is returned to clients as `X-Request-ID` (an incoming
`X-Request-ID` is reused), so a user's error report can be traced in the
logs.

## Backups

Back up the `postgres_data` volume (e.g. `pg_dump` on a schedule). Redis
holds only live, reconstructible state.
