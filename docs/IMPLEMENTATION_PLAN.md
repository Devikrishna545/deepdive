# DeepDive — Implementation Plan (Agent Arena 2026, Track 01)

Owner: Devi · Build window: Oct 15 – Oct 20, 2026 · Living copy of the plan; architecture in
[`ARCHITECTURE.md`](ARCHITECTURE.md), brief checklist in [`HACKATHON_REQUIREMENTS.md`](HACKATHON_REQUIREMENTS.md).

> Stack update (Oct 15): UI is server-rendered HTML + Tailwind + vanilla JS served by FastAPI
> (not Streamlit); Flask-style app factory and routers; models are called with the `openai` SDK
> pointed at Mesh (not LangChain chat models, see design decision 8); uploads use a numpy vector
> store in SQLite (not Chroma). Models and limits re-tuned for a small credit balance.

## 1. Problem statement

DeepDive answers one research question with a structured report in which every sentence has
been checked against the passage it cites. The judged differentiator is trust, not search:
existing deep-research tools attach citations that often do not support the sentence beside them.

**What we build:** a LangGraph-orchestrated team of five agents (Planner, Researcher, Drafter,
Verifier, Synthesizer) that plans sub-questions, gathers web and document evidence, drafts atomic
claims, verifies each claim against its cited chunk, loops back when a sub-question is thin, and
writes a report using only verified claims. Every step is logged as an audit trail.

**Relation to Research Space:** same DNA (retrieve, cite, compare) but a single-run pipeline
with no workspaces, paper library or notes. The verification engine can later become a module
inside Research Space and the basis of a paper on claim-level groundedness.

**Constraints:** 6-day build; every LLM and embedding call through Mesh API
(`https://api.meshapi.ai/v1`, key prefix `rsk_`); public GitHub repo with README, design notes and
self-evaluation numbers; repo secrets `MESH_API_KEY` and `SUBMISSION_TOKEN`.

## 2. Use cases

| ID | Actor | Scenario | Outcome |
| --- | --- | --- | --- |
| UC1 | Analyst | Asks a question ("Main risks of investing in the EV battery market in 2026?") | Structured report; each sentence has a citation mark coloured by verification |
| UC2 | Analyst | Uploads PDFs (annual report, policy paper) plus a question | Evidence from web and documents; document citations show file and page |
| UC3 | Reviewer / judge | Opens the audit trail of a run | Sub-questions, queries, URLs, kept and rejected claims with reasons, loop-backs |
| UC4 | Analyst | Asks a follow-up | Reuses the evidence store; researches only the new gap (bonus) |
| UC5 | Analyst | Exports the report | Markdown file or printable page (save as PDF) with numbered references |
| UC6 | Developer | Runs the evaluation suite | Groundedness and coverage metrics written to the repo and README |

Demo questions: the EV battery question from the brief, and a domain one such as
"How is the UAE 9% corporate tax affecting free zone companies?"

## 3. Scope of work

**Must ship (judged):** LangGraph coordinator with five distinct agents; web search + fetch +
clean-text extraction with every chunk stored with its source; claim-level verification with
removal/flagging; bounded coverage loop; report from verified claims only with a deterministic
citation check; persisted audit trail visible in the UI; self-evaluation with numbers in the repo;
FastAPI backend + HTML UI; README with design decisions and results.

**Bonus, in order:** explicit LangGraph loop (done by design) → contradiction detection →
source-quality weighting → document upload → Markdown/printable export → conversational follow-up.

**Out of scope:** accounts and auth, multi-tenant workspaces, paper library and notes, scheduled
runs, fine-tuning, production-scale deployment.

## 4. Functional requirements

| ID | Requirement | Priority | Acceptance check | Status |
| --- | --- | --- | --- | --- |
| FR-01 | Accept a question (10–500 chars) via API and UI, depth `quick`/`standard`, optional files | Must | `POST /api/runs` returns `run_id`; UI starts a run | Built |
| FR-02 | Planner returns 3–6 sub-questions with 2–3 queries each, as validated JSON | Must | `PlanOut` parses; trail shows sub-questions | Built |
| FR-03 | Researcher searches, fetches top pages, extracts text, chunks, stores each chunk with URL, title, domain, dates | Must | chunks with `source_id` for every sub-question | Built |
| FR-04 | Findings tied to chunk IDs | Must | no finding without a valid chunk ID | Built |
| FR-05 | Drafter emits atomic claims citing ≥ 1 chunk | Must | every claim has `cited_chunk_ids` | Built |
| FR-06 | Verifier labels each claim against its cited chunk only, with reason and evidence quote | Must | every claim has a verdict | Built |
| FR-07 | UNSUPPORTED/CONTRADICTED dropped; PARTIAL narrowed and re-checked | Must | a removed claim visible in the Claims tab | Built |
| FR-08 | Coverage gate: < 2 kept claims or < 2 domains → gap queries → loop back, `MAX_LOOPS` (default 1) | Must | loop-back event in trail | Built |
| FR-09 | Synthesizer: summary, section per sub-question, disagreements, limitations, references | Must | sections present | Built |
| FR-10 | Deterministic citation check: sentences without verified claim IDs removed and logged | Must | 0 uncited sentences | Built |
| FR-11 | Audit trail per node: summary, payload, model, tokens, latency | Must | `GET /api/runs/{id}/trail` | Built |
| FR-12 | Live progress per node in the UI | Must | SSE pipeline view | Built |
| FR-13 | Every LLM/embedding call through one Mesh wrapper | Must | `scripts/check_mesh_only.py` in CI | Built |
| FR-14 | Contradiction detection across sources | Should | "Where sources disagree" block | Built, untested live |
| FR-15 | Source-quality score ranks evidence; shown per reference | Should | score in references | Built |
| FR-16 | Upload PDF/DOCX/TXT; embedded and retrieved with web evidence | Should | citation shows file and page | Built, untested live |
| FR-17 | Export Markdown and printable page | Could | download links work | Built |
| FR-18 | Follow-up reusing the run's evidence | Could | fewer fetches on follow-up | Stub (501) |
| FR-19 | Eval CLI writes metrics JSON and the README table | Must | `python -m evaluation.run_eval` | Built |

## 5. Non-functional requirements

| ID | Category | Requirement | Target |
| --- | --- | --- | --- |
| NFR-01 | Compliance | All LLM/embedding calls via `app/llm/mesh_client.py` | 100%, CI check |
| NFR-02 | Groundedness | Final sentences re-verified SUPPORTED by an independent judge | ≥ 90% |
| NFR-03 | Groundedness | Uncited sentences in the final report | 0 |
| NFR-04 | Latency | End-to-end with parallel researchers | quick < 90 s; standard < 4 min |
| NFR-05 | Cost | USD cost per call/step/run from live Mesh prices; per-run cap; balance alert at $5, runs refused below $1 | `RUN_BUDGET_USD`, `LOW_BALANCE_ALERT_USD`, `MIN_BALANCE_STOP_USD` |
| NFR-06 | Reliability | Retries with backoff; failed page never fails a run; bounded loops | 3 retries (transient only), 10 s fetch timeout, ≤ `MAX_LOOPS` loops |
| NFR-07 | Reproducibility | Temperature 0 for planner/researcher/drafter/verifier; search/fetch cache | same cache → same verdicts |
| NFR-08 | Observability | Trail rows with run id, node, tokens, latency, models | every node |
| NFR-09 | Security | Keys only in `.env`/secrets; never logged; injection guard in every prompt; `textContent` in UI | gitleaks clean |
| NFR-10 | Explainability | Every non-SUPPORTED verdict has a reason (+ quote when present) | 100% |
| NFR-11 | Maintainability | Pydantic I/O, prompts in files, SKILL.md per agent, tests | CI green |
| NFR-12 | Usability | Live progress, verdict-coloured citation marks, click to see the passage | demo-ready |
| NFR-13 | Portability | Python 3.10+, `pip install -r requirements.txt`, `python run.py` | fresh clone works |

## 6. Architecture summary

LangGraph `StateGraph`: `plan → Send(research × N) → draft → verify → coverage_gate →
(gap_plan → Send(research × gaps) → …) → cross_check → synthesize → cite_check`. Agents are
plain classes with their own prompt, schema and tools; routing, loop counting and checks are
code. Details, diagrams, state, data model, API: [`ARCHITECTURE.md`](ARCHITECTURE.md).

| Agent | Model (check ids and live prices: `python -m scripts.mesh_account`) |
| --- | --- |
| Planner, Researcher, Drafter, Synthesizer | `openai/gpt-4o-mini` (cheap; high volume or guarded by code checks) |
| Verifier | `anthropic/claude-haiku-4.5` (accuracy-critical; different family from the drafter) |
| Eval judge | `google/gemini-2.5-flash` (different from the verifier) |
| Embeddings | `openai/text-embedding-3-small` |

**Credit plan (small balance):** low-balance banner at $5 and runs refused below $1 (`GET /v1/balance`);
every call priced with live Mesh prices; `RUN_BUDGET_USD=0.15` per run; loop-back skipped after 60% of
the run budget; dev work on `--depth quick`, offline tests and the offline demo; paid eval always with
`--limit` and `--max-usd`. Optional Mesh-side `balance.low` webhook via `scripts/setup_balance_alert.py`.

## 7. Verification design

1. **Atomize** (Drafter): one fact per claim, typed fact/number/date/opinion.
2. **Precheck** (code): numbers in the claim missing from the cited text → hint.
3. **Judge** (Verifier, temp 0): label + reason + exact quote + narrowed claim.
4. **Quote guard** (code): quote not in cited chunk → UNSUPPORTED.
5. **Act**: keep SUPPORTED; narrow and re-check PARTIAL once; drop the rest.
6. **Coverage gate**: ≥ 2 kept claims from ≥ 2 domains per sub-question, else loop (`MAX_LOOPS`, default 1),
   then mark "limited evidence".
7. **Contradictions**: embed kept claims, pair similar ones from different sources (cos ≥ 0.85),
   ask the verifier model agree/disagree/unrelated; disagreements reported with both citations.
8. **Citation check** (code): drop any report sentence without a kept claim ID.

Source quality = tier weight (gov/filings 1.0, academic 0.9, major news 0.8, other 0.6,
blog/forum 0.3; uploads 0.9) × recency (< 12 months 1.0, < 36 months 0.8, older 0.6, unknown 0.8).

## 8. Self-evaluation plan

- `evaluation/data/questions.jsonl`: 18 questions (market, finance, policy, science-tech,
  recent events, false premise) with hand-written `must_cover` points.
- `evaluation/data/verifier_pairs.jsonl`: 16 seed labelled pairs; grow to 40–60 from real runs.
- Metrics: groundedness (independent judge), uncited rate, coverage, claim pass rate,
  loop-back rate, bad-citation recall/precision, tokens, seconds.
- Ablation: `--ablation` runs the same questions with `VERIFY_ENABLED=false`.
- Output: `evaluation/results/eval_<timestamp>.json` + README block, both committed.

## 9. Day-by-day plan

**Thu Oct 15 — foundations**
- [x] Project scaffold, CLAUDE.md guardrails, SKILL.md per agent, docs
- [x] Mesh client (JSON mode + Pydantic + repair), schemas, DB, graph, agents, UI, offline tests
- [ ] Create the public GitHub repo, push, add secrets `MESH_API_KEY` and `SUBMISSION_TOKEN`
- [ ] `.env` with your key; `python -m scripts.smoke_mesh` until every model line says ok
- [ ] Optional: Tavily key

**Fri Oct 16 — plan and research, live**
- [ ] `python -m scripts.cli "<EV question>" --depth quick`; read the trail
- [ ] Tune planner prompt and researcher limits on 2–3 questions
- [ ] Check search quality (Tavily vs DuckDuckGo) and fetch failure rate

**Sat Oct 17 — the core loop, live**
- [ ] Verify drafter/verifier behaviour on real pages; confirm at least one removed claim
- [ ] Confirm a loop-back happens on a thin topic; tune coverage thresholds if needed
- [ ] Milestone: full standard run of the EV question from the UI

**Sun Oct 18 — product and evidence**
- [ ] UI polish from real runs; contradiction detection on real data
- [ ] Grow `verifier_pairs.jsonl` to 40+ from real runs (hand-checked)
- [ ] Document upload test with a real PDF

**Mon Oct 19 — measure and tune**
- [ ] `python -m evaluation.run_eval --set all` and `--set questions --ablation`
- [ ] Tune verifier prompt against labelled pairs; rerun; commit results

**Tue Oct 20 — polish and submit**
- [ ] Feature freeze at midday; README results and design notes final
- [ ] 3-minute demo video (ask → progress → removed claim → trail → numbers); optional deploy
- [ ] Fresh-clone test from README; submit

## 10. Risks

| Risk | Mitigation |
| --- | --- |
| Some Mesh models reject `response_format` | client retries without it and remembers; Pydantic + one repair retry |
| Verifier too strict → thin reports | PARTIAL narrowing; tune on labelled pairs; "limited evidence" instead of padding |
| Verifier too lenient → inflated numbers | quote guard; synthetic negatives; independent judge |
| Synthesizer adds unverified text | sentence-level claim IDs + deterministic removal |
| Paywalls / JS pages | Tavily content first; several hits per query; failures logged and skipped |
| Rate limits / cost | concurrency cap 4; SQLite cache; cheap extraction models; token budget |
| Time overrun | scaffold done day 1; bonus order fixed; Tuesday midday freeze |
| Secret leak | `.env` gitignored; gitleaks in CI; keys never logged |
