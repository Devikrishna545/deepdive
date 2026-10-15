# Key design decisions

Short notes on the choices that matter for trust, cost and the hackathon rules. Update this
file when a decision changes; the README links here.

| # | Decision | Why | Alternative rejected |
| --- | --- | --- | --- |
| 1 | **Claim-level verification**: the drafter emits atomic claims; the verifier checks each one against only the chunks it cites | A sentence-level or report-level check can't say which fact is wrong; atomic claims make rejection precise and explainable | Ask one LLM to "review the report" |
| 2 | **Verifier isolation + different model family** (`MODEL_VERIFIER` ≠ drafter family) | Prevents the verifier from being persuaded by the draft or by its own earlier reasoning | Same model self-critique |
| 3 | **Quote guard in code**: evidence quote must appear verbatim in the cited chunk | Stops the verifier itself from hallucinating support; cheap and deterministic | Trust the verifier's label |
| 4 | **Citation check in code** after synthesis | The synthesizer can still add a flourish; code deletes any sentence without a verified claim ID and logs it | Prompt-only instruction |
| 5 | **Coverage gate + bounded loop** (≥ 2 verified claims from ≥ 2 domains, `MAX_LOOPS`=1 by default to save credits) | Thin topics get more research instead of padding; the bound protects cost and latency | Unbounded "research until good" |
| 6 | **Gap queries from rejection reasons** | The loop learns from why claims failed (weak source, missing number) rather than repeating searches | Re-run the same queries |
| 7 | **Coordinator is code (LangGraph), agents are LLM calls** | Routing, fan-out, loop counting and citation checks are testable and deterministic | An LLM "manager" agent |
| 8 | **Mesh through the official OpenAI SDK in one module** (`app/llm/mesh_client.py`) + CI check | It is exactly the client the brief shows and the one its checks look for in `requirements.txt`; one choke point makes "every call goes through Mesh" provable by grep; we see every request's exact tokens (cost tracking, `max_tokens` caps, retry only on transient errors, never on 402); JSON-mode + Pydantic works on every model family behind the gateway, while LangChain's `with_structured_output` relies on tool/json-schema support that not every gateway model has, and its embeddings wrapper tokenises with tiktoken. LangGraph does not need LangChain models: nodes are plain functions. Swapping in `ChatOpenAI(base_url=Mesh)` later is a one-file change | LangChain chat models across the code |
| 9 | **JSON mode + Pydantic validation + one repair retry** | Works across model families on the gateway, including ones without strict structured outputs | Provider-specific function calling |
| 10 | **Source-quality weighting as a visible table** (`app/core/scoring.py`) | Judges can read the trust policy; easy to tune | Hidden prompt instruction |
| 11 | **SQLite for runs, trail and caches; numpy vector store for uploads** | Zero ops for a 6-day build; search/fetch cache makes eval reruns cheap and comparable | Postgres, Chroma (heavier install) |
| 12 | **Server-rendered HTML + Tailwind + vanilla JS UI** served by FastAPI | One process, no build step, full control of citation marks and the trail view | Streamlit (less control over the report layout) |
| 13 | **Ablation switch** `VERIFY_ENABLED=false` | Lets us measure what verification contributes with the same pipeline | Compare against a different system |
| 14 | **Independent judge model** for groundedness in the eval | The system shouldn't grade itself with the model it used to filter | Use the verifier's own pass rate as the score |
| 15 | **Credit guards from Mesh's own APIs**: balance from `GET /v1/balance` before every run (warn < $5, refuse < $1), live prices from `GET /v1/models` to price every call, `RUN_BUDGET_USD` per run, loop-back skipped after 60% of the run budget | Small balance; a run should finish with a report rather than be cut off, and spend must be visible per step | Discover the balance when calls start failing with 402 |
| 16 | **Cheap models for volume, the stronger model only for the verifier** | Claim accuracy is decided in the verifier; planning, extraction, drafting and writing from verified claims are well within `gpt-4o-mini`-class models, and code guards catch their mistakes | Strong model everywhere |
| 17 | **Token discipline**: compact output-shape hints (~80% shorter than JSON Schema), short prompts, `max_tokens` on every call, drafter sees findings not chunks, 8 chunks × 700 chars per sub-question, contradiction check only on numeric/date claims | Same accuracy contract at a fraction of the input/output tokens | Long prompts and full schemas |
| 18 | **Free verbatim fast path in the verifier**: a claim equal to a whole source sentence is accepted by code | Zero-cost and exact; whole-sentence equality (not substring) keeps it safe against negated contexts | LLM call for every claim |
