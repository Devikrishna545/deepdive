# Agent Arena 2026 · Track 01 · requirements mapped to this repo

Source: the Track 01 brief on the hackathon dashboard (Oct 15 – Oct 20, 2026). Tick items as they
become demonstrable. "Where" is the file or command that proves it.

## Hard rules

| Rule | Where it is met | Status |
| --- | --- | --- |
| Every LLM/AI call routes through Mesh API (`base_url=https://api.meshapi.ai/v1`, key from `MESH_API_KEY`) | `app/llm/mesh_client.py` is the only model client; `scripts/check_mesh_only.py` in CI | Done |
| (Own rule) Spend credits carefully | balance guard ($5 alert, $1 floor), per-run USD cap, live prices, `scripts/mesh_account.py` | Done |
| Public GitHub repo with all code | https://github.com/Devikrishna545/deepdive (check it is set to Public) | Done |
| `requirements.txt` lists a web framework (FastAPI) and the LLM client used with Mesh (`openai`) | `requirements.txt` | Done |
| `README.md`: what we built, how agents cooperate, how to run, key design decisions, self-evaluation results | `README.md`, `docs/DESIGN_DECISIONS.md`, eval block | Partly (results pending) |
| `.gitignore` includes `.env`; no secrets committed | `.gitignore`, gitleaks in CI | Done |
| Repo secrets `MESH_API_KEY` and `SUBMISSION_TOKEN` (Settings → Secrets and variables → Actions) | GitHub settings | Done |
| Optional: demo video + deployed URL | — | Video: to do (19–20 Oct) |
| (Own rule) Developer views hidden for judges | `DEV_MODE` defaults to `false` | Done |

## What to build (judged)

| # | Brief item | Where | Status |
| --- | --- | --- | --- |
| 1 | Coordinator that plans, delegates, passes results, assembles the answer | `app/graph/builder.py`, `nodes.py` | Scaffolded + offline-tested |
| 1 | ≥ 3 genuinely distinct agents (own job, own prompt or tools) | `app/agents/{planner,researcher,drafter,verifier,synthesizer}/` | Scaffolded |
| 2 | Real evidence from the web, optionally from uploaded documents | `app/tools/search.py`, `fetch.py`, `documents.py` | Scaffolded; verify with real key |
| 2 | Retrieved content stored with its source | `Source` + `Chunk` in state, snapshot in `runs.snapshot_json` | Done |
| 3 | Verifier checks each claim against the source it cites; marks or removes unsupported | `app/agents/verifier/`, `app/core/guards.py` | Scaffolded + tested |
| 3 | Thin sub-question loops back for more research | `coverage_gate` → `gap_plan` → `research` | Done (offline test) |
| 4 | Structured report; every claim's citation traces to a retrieved source | `app/agents/synthesizer/`, `app/core/citation_check.py` | Done (offline test) |
| 5 | Auditable trail: sub-questions, searches, passed and rejected claims with reasons | `events` table, `/api/runs/{id}/trail`, UI "Audit trail" + "Claims" tabs | Done |
| 6 | Self-evaluation: own test questions, groundedness/completeness metrics, numbers in repo | `evaluation/`, README results block | Harness done; numbers pending |

## Bonus

| Item | Where | Status |
| --- | --- | --- |
| Structured framework (LangGraph) with explicit nodes and a real loop back | `app/graph/builder.py` | Done |
| Contradiction detection across sources | `app/core/contradictions.py`, `cross_check` node | Scaffolded |
| Source-quality weighting with visible logic | `app/core/scoring.py` | Done |
| Shareable export (PDF or page) | `/api/runs/{id}/export?fmt=md\|html` (print to PDF) | Done |
| Conversational follow-up reusing earlier research | `POST /api/runs/{id}/followup` (501 stub) | To do |

## "What a great submission looks like" checklist

- [ ] A coordinator that genuinely orchestrates distinct agents, with results passed between them
- [ ] A verification step that rejects unsupported claims, and a claim we can point to that got removed (Claims tab → Removed)
- [ ] Reports where citations really support their sentences (click any citation mark)
- [ ] A visible decision trail and honest, self-measured groundedness numbers
- [ ] Something we'd be proud to show in an interview
