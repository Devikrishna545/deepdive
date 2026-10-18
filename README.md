# DeepDive — a self-verifying research analyst

DeepDive answers a research question with a structured report in which **every sentence has
been checked against the source passage it cites**. Claims the sources don't support are
removed, thin topics trigger more research, and the whole run is logged so you can see what
was kept, what was rejected, and why.

Built for **Agent Arena 2026 · Track 01 (DeepDive)**. All LLM and embedding calls go through
**[Mesh API](https://meshapi.ai)**.

## How the agents cooperate

```mermaid
flowchart LR
    Q([Question]) --> P[Planner]
    P -->|one task per sub-question, in parallel| R[Researcher x N]
    R --> D[Drafter]
    D --> V[Verifier]
    V --> G{Coverage gate}
    G -->|thin: new queries, max 2 loops| GP[Planner: gap queries]
    GP --> R
    G -->|ok| X[Contradiction check]
    X --> S[Synthesizer]
    S --> C[Citation check]
    C --> O([Report + audit trail])
```

| Agent | Job | Sees |
| --- | --- | --- |
| **Planner** | Splits the question into sub-questions with search queries; on a loop-back, writes new queries from the verifier's rejection reasons | the question |
| **Researcher** | Searches the web (and your uploaded documents), fetches pages, stores every chunk with its source, extracts findings that cite chunk IDs | the chunks it fetched |
| **Drafter** | Turns findings into atomic claims, one checkable fact each, citing chunks | findings + their chunks |
| **Verifier** | Checks **one claim against only the text it cites**: supported, partial, unsupported or contradicted, with an exact evidence quote | one claim + its chunks |
| **Synthesizer** | Writes the report from **verified claims only**; every sentence lists its claim IDs. Code then adds a verified figure the writer left out when two passages agree on it | kept claims |

The coordinator is a LangGraph `StateGraph`: parallel research with `Send`, a conditional
**coverage gate** that loops back to research when a sub-question has fewer than 2 verified
claims from 2 independent domains (bounded by `MAX_LOOPS`), and deterministic code for routing and citation checks.

### What makes the citations trustworthy

1. **Isolated verifier on a different model family** from the drafter, so the system is not grading itself.
2. **Quote guard in code:** the verifier must quote the source verbatim; if the quote isn't
   literally in the cited chunk, the claim is downgraded to unsupported.
3. **Partial claims are narrowed** to what the source actually says and re-verified once.
4. **Citation check in code:** any report sentence without a verified claim ID is deleted and logged.
5. **Audit trail:** sub-questions, queries, URLs fetched and failed, every verdict with its reason,
   loop-backs, removed sentences, tokens and latency per step.

### Built for a small credit balance

- Balance read from Mesh (`GET /v1/balance`) before every run: a banner below **$5**, new runs refused below **$1**.
- Every call is priced with live Mesh prices; cost is shown per step and per run, and a run stops at `RUN_BUDGET_USD`.
- Cheap models for extraction, drafting and writing; a cheap reasoning model for planning (`gpt-5-nano`,
  falling back to `gpt-oss-120b`), since the plan decides every search; the stronger model only for the
  verifier, where accuracy is decided.
- Short prompts, compact output formats, `max_tokens` on every call, and a free code path that accepts claims copied word for word from a whole source sentence.
- `python -m scripts.mesh_account` (free) shows your balance, the price of each configured model and the estimated cost per run.
- Developer view (`DEV_MODE=true`): a **Tokens (dev)** tab on each run and a `/dev/usage` page show input and output tokens, calls and cost per agent and per step, live while a run is going.

Bonus features: explicit LangGraph loop, contradiction detection across sources, visible
source-quality weighting (`app/core/scoring.py`), document upload, Markdown and printable export.

## Run it

```bash
git clone <this repo> && cd deepdive
python -m venv .venv && source .venv/bin/activate      # Python 3.10+
pip install -r requirements.txt
cp .env.example .env                                     # add your MESH_API_KEY (rsk_...)
python -m scripts.mesh_account                           # free: balance, model prices, cost per run
python -m scripts.smoke_mesh                             # checks each configured model via Mesh (< 1 cent)
python -m scripts.check_search                           # free: checks web search returns results
python run.py                                            # http://127.0.0.1:8000
```

- Web UI: ask a question, watch the pipeline, read the report, click any citation mark to see
  the exact passage, open the **Claims** tab to see what was removed, and the **Audit trail** tab.
- Terminal: `python -m scripts.cli "your question"`
- API docs: http://127.0.0.1:8000/docs
- No key yet? `python -m scripts.offline_demo` creates a demo run from fake data so you can see the UI.

Search: set `TAVILY_API_KEY` (free tier, no card) for reliable results. Without it DuckDuckGo is
used, which often rate-limits and returns nothing. `python -m scripts.check_search` (free) tests
search before you spend credits; a run that finds no sources at all stops before drafting.
Search is not an LLM call.

## Self-evaluation

We measure two things separately: whether the verifier catches bad citations (labelled pairs
with known answers), and whether final reports are grounded and complete (18 test questions
across market, finance, policy, science, recent events and false-premise questions). An
ablation with verification switched off shows what the verifier contributes.
Groundedness is judged by a **different model** (`MODEL_JUDGE`) from the verifier.

| Metric | Definition |
| --- | --- |
| Groundedness | share of final sentences whose cited passages support them, re-checked by the judge model |
| Uncited sentences | share of final sentences with no verified claim ID (target 0) |
| Coverage | share of hand-written key points per question that the report covers |
| Claim pass rate | share of drafted claims that survive verification |
| Bad-citation recall / precision | verifier on labelled pairs, positive class = unsupported or contradicted |

```bash
python -m evaluation.run_eval --set verifier
python -m evaluation.run_eval --set questions --limit 5 --max-usd 1.0
python -m evaluation.run_eval --set questions --limit 5 --max-usd 1.0 --ablation
python -m evaluation.run_benchmark            # 10-question regression benchmark, stops at $1.50
```

The benchmark (`evaluation/data/benchmark.jsonl`) has reference answers checked against
official sources, including two false-premise questions. For each key fact it reports the
stage where the fact was lost (search, extraction, drafting, verification or writing), whether
the cited passage really states it, any known-wrong claim that slipped through, and tokens and
cost per agent.

The question runner stops early at `--max-usd` or when the Mesh balance reaches the $1 floor, and records why.

### Results

<!-- EVAL:START -->
_Not run yet. Numbers will be written here by `python -m evaluation.run_eval`._
<!-- EVAL:END -->

## Key design decisions

See [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md). In short: verification is
claim-level and isolated; code (not the LLM) has the final word on quotes and citations;
thin evidence loops back instead of being padded; trust policy is a visible table, not a prompt.

## Project layout

```
app/            FastAPI app (Flask-style factory + routers), agents, graph, core logic, UI
evaluation/     test sets, metrics, runner, committed results
scripts/        cli, smoke_mesh, offline_demo, check_mesh_only
tests/          offline tests (fake Mesh, no network)
docs/           implementation plan, architecture, hackathon requirements, design decisions
```

Full architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
