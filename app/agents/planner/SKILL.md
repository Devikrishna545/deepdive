---
name: planner-agent
description: Contract and guardrails for the DeepDive Planner agent (question -> sub-questions and search queries; thin sub-question -> gap queries). Read before editing app/agents/planner/.
---

# Planner agent

## Job
1. `plan(question, depth)` -> 3..MAX_SUBQUESTIONS `SubQuestion`s, each with 2–3 search queries.
2. `gap_queries(question, sub_question, reasons)` -> 1–3 NEW queries for a thin sub-question,
   used by the loop-back (`gap_plan` node).

## Inputs / outputs
| In | Out (LLM schema) | Stored as |
| --- | --- | --- |
| question, depth, today's date | `PlanOut` | `list[SubQuestion]` (IDs by code: `sq_…`) |
| question, sub-question, tried queries, rejection reasons | `GapQueriesOut` | appended to `SubQuestion.queries` |

Prompts: `prompt.md` (plan), `gap_prompt.md` (loop-back). Model: `MODEL_PLANNER`, temperature 0.

## Guardrails
- The planner never answers the question and never states facts. It only writes sub-questions and queries.
- Sub-questions must not overlap; each must be answerable from public, citable sources. Cover every
  part the question asks for first; generic angles (stakeholders, risks) only when asked or slots remain.
- The `plan` node caches plans (`CACHE_PLANS`, key = question, depth, model, prompt text, month), so a
  prompt edit takes effect immediately but a repeated question reuses its plan.
- When the question presupposes an event or decision that may not have happened, return it as
  `premise` (+ `premise_queries`). Code then adds "Is it true that ...?" as the FIRST sub-question
  (`checks_premise=True`) and keeps the total within the limit. Leave `premise` empty otherwise:
  a needless check costs a sub-question slot.
- Model: `MODEL_PLANNER` (default `openai/gpt-oss-120b`, a reasoning model) with
  `MODEL_PLANNER_FALLBACK` (`openai/gpt-5-nano`) when the call errors or the plan stays invalid
  after one repair. Caps `PLAN_MAX_TOKENS=2500`, `GAP_MAX_TOKENS=1000`: hidden reasoning counts
  against them, and the planner asks for `PLANNER_REASONING_EFFORT=low` (at the default effort
  gpt-5-nano thought through all 2500 tokens and answered nothing). Reasoning models ignore temperature (the client drops it); the plan cache keeps
  reruns comparable. Changing the model changes the plan cache key.
- Queries name the subject with its field ("transformer neural network", not "transformer"): a bare
  ambiguous word pulls in the other meaning (a live run fetched power-grid transformer pages).
  Sub-questions are plain questions; never copy prompt wording into them (gpt-5-nano wrote
  "Figure: identify key figures and origin year." as a sub-question).
- `quick` depth = max 3 sub-questions. Never exceed `MAX_SUBQUESTIONS` (cost and latency).
- Gap queries must differ from queries already tried (code also filters duplicates). If no new
  query is produced, the node stops looping on that sub-question; do not force a retry.
- Pass the current date in the user message; do not hard-code years in the prompt.
- Use only years and places the question states or implies (benchmark 3: an invented "in 2020"
  sub-question made the drafter mis-date a true figure). No sub-question may assume the premise.
  For laws and rules, one query names the official law or regulation.

## Failure modes to watch
- Vague sub-questions ("Overview of X") produce vague claims and low coverage. Prefer measurable angles.
- Queries that copy the sub-question verbatim search poorly. Keep them 3–8 words with names, years, units.

## Test
`tests/test_graph_offline.py` exercises plan and gap planning with `FakeMesh`. Add a case there
for any change to how sub-questions or gap queries are produced.
