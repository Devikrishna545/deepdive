# app/ — application package

Flask-style layout on FastAPI. Start at `app/__init__.py::create_app()`.

- `routes/` are the blueprints. Pages (`pages.py`) render Jinja templates; JSON lives under
  `/api` (`api_runs.py`, `api_files.py`, `health.py`). Routes stay thin: validate input with
  Pydantic, call `services/` or `db/repository.py`, return JSON. No graph or LLM logic in routes.
- `graph/` is the coordinator (see `builder.py` docstring for the flow). Every node is wrapped by
  `tracing.traced`, which writes the audit trail and enforces `RUN_TOKEN_BUDGET`.
- `core/` is deterministic and unit-tested: keep it free of network and LLM calls
  (exception: `contradictions.py` receives the Mesh client as an argument).
- `db/repository.py` is the only module that opens DB sessions for app code.
- `templates/` + `static/`: plain HTML, one hand-written stylesheet (`static/css/app.css`, pastel
  tokens + dark mode, no CSS framework), Lucide icons from a local sprite (`static/icons/sprite.svg`,
  `icon()` in JS, `icon` macro in `partials/icons.html`) and vanilla JS. Installable as an app
  (`/manifest.webmanifest`, `/sw.js`; the service worker never caches `/api`). Use `el()` from
  `static/js/common.js` for DOM building; never `innerHTML` with API data (it contains web text).
  Keep the UI accessible: labels on inputs, visible focus, `aria-*` on tabs and dialogs.

API surface (keep stable; the UI and the eval depend on it):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | config sanity (incl. `access_code_required`, `max_runs_per_day`) (never values of keys) + Mesh balance level (ok/low/stop/unknown) |
| POST | `/api/runs` | start a run `{question, depth, file_ids, web_search?}` -> `{run_id}` (`web_search`: documents first, web for the parts they leave thin; document mode only); 402 below the balance floor; 401 without the `X-Access-Code` header when `RUN_ACCESS_CODE` is set; 429 past `MAX_RUNS_PER_DAY` |
| GET | `/api/runs` / `/api/runs/{id}` | list / one run |
| GET | `/api/runs/{id}/events` | SSE audit-trail stream |
| GET | `/api/runs/{id}/report` | report JSON (+ markdown) |
| GET | `/api/runs/{id}/claims` | every claim + verdict + cited chunks + sources |
| GET | `/api/runs/{id}/trail` | full audit trail + research log |
| GET | `/api/runs/{id}/export?fmt=md\|html` | download / printable page |
| POST | `/api/runs/{id}/followup` | continue a finished run `{question, depth?}` -> `{run_id, parent_run_id}` (202; 409 if the run isn't done; same access/cap guards as `/api/runs`). `GET /api/runs/{id}` returns `parent_run_id`, `thread` and `followups` |
| POST | `/api/runs/{id}/stop` | stop a queued/running run before its next step -> status `stopping`, then `stopped` (202; 409 if not in progress; access code when set) |
| POST | `/api/runs/{id}/rerun` | edit & run again `{question, depth}` -> new `{run_id, replaces}` with the same files and thread (202; 409 while queued/running, allowed while stopping; access/cap guards) |
| DELETE | `/api/runs/{id}` | delete one finished run with its events (409 while running; access code when set) |
| POST | `/api/runs/delete` | delete several `{run_ids}` -> `{deleted, skipped}` (running runs are skipped; access code when set) |
| POST | `/api/files` | upload PDF/DOCX/TXT for grounding; 422 for empty, scanned or damaged files; 503 if the model service can't index it; needs the access code when set |
| GET | `/api/runs/{id}/usage` | DEV_MODE only: input/output tokens, calls, cost per agent and per step |
| GET | `/dev/usage`, `/api/dev/usage` | DEV_MODE only: per-agent tokens across recent runs + average per run |

Token accounting: `traced` stores `prompt_tokens`, `completion_tokens` and the individual calls
(`calls_json`) on every `events` row; `services/usage_service.py` maps nodes to agents
(`plan`/`gap_plan`->planner, `research`->researcher, `draft`->drafter, `verify`/`cross_check`->verifier,
`synthesize`->synthesizer). New columns are added to an existing SQLite file by `init_db()`.
