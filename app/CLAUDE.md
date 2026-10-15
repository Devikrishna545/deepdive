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
- `templates/` + `static/`: plain HTML, Tailwind (CDN) and vanilla JS. Use `el()` from
  `static/js/common.js` for DOM building; never `innerHTML` with API data (it contains web text).
  Keep the UI accessible: labels on inputs, visible focus, `aria-*` on tabs and dialogs.

API surface (keep stable; the UI and the eval depend on it):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | config sanity (never values of keys) + Mesh balance level (ok/low/stop/unknown) |
| POST | `/api/runs` | start a run `{question, depth, file_ids}` -> `{run_id}`; 402 below the balance floor |
| GET | `/api/runs` / `/api/runs/{id}` | list / one run |
| GET | `/api/runs/{id}/events` | SSE audit-trail stream |
| GET | `/api/runs/{id}/report` | report JSON (+ markdown) |
| GET | `/api/runs/{id}/claims` | every claim + verdict + cited chunks + sources |
| GET | `/api/runs/{id}/trail` | full audit trail + research log |
| GET | `/api/runs/{id}/export?fmt=md\|html` | download / printable page |
| POST | `/api/runs/{id}/followup` | bonus, returns 501 until built |
| POST | `/api/files` | upload PDF/DOCX/TXT for grounding |
| GET | `/api/runs/{id}/usage` | DEV_MODE only: input/output tokens, calls, cost per agent and per step |
| GET | `/dev/usage`, `/api/dev/usage` | DEV_MODE only: per-agent tokens across recent runs + average per run |

Token accounting: `traced` stores `prompt_tokens`, `completion_tokens` and the individual calls
(`calls_json`) on every `events` row; `services/usage_service.py` maps nodes to agents
(`plan`/`gap_plan`->planner, `research`->researcher, `draft`->drafter, `verify`/`cross_check`->verifier,
`synthesize`->synthesizer). New columns are added to an existing SQLite file by `init_db()`.
