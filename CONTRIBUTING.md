# Contributing

## Setup

Backend (Python 3.12 — the telephony path needs the `audioop` module that
3.13 removed):

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

Frontend (Node 22):

```bash
cd frontend
npm ci
```

## Checks to run before you push

These are the same checks CI runs (`.github/workflows/ci.yml`).

| Where | Command | What it checks |
|---|---|---|
| `backend/` | `ruff check .` | syntax errors, unused or undefined names |
| `backend/` | `python -m pytest -q` | the backend test suite |
| `frontend/` | `npm run lint` | ESLint |
| `frontend/` | `npm test` | Vitest unit and component tests |
| `frontend/` | `npm run build` | type check and production build |

## Tests

- Backend tests live in `backend/tests/` and use pytest.
- Frontend tests sit beside the code as `*.test.ts` / `*.test.tsx` and use
  Vitest with Testing Library (jsdom). Mock the API client or `fetch`
  rather than calling a server.

## Branches and commits

Work on a branch and open a pull request. Keep a commit to one change and
say why in the message.
