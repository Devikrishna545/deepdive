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
- Sub-questions must not overlap; each must be answerable from public, citable sources.
- Include a premise-check sub-question when the question may rest on a false premise
  (the eval set has false-premise questions).
- `quick` depth = max 3 sub-questions. Never exceed `MAX_SUBQUESTIONS` (cost and latency).
- Gap queries must differ from queries already tried (code also filters duplicates). If no new
  query is produced, the node stops looping on that sub-question; do not force a retry.
- Pass the current date in the user message; do not hard-code years in the prompt.

## Failure modes to watch
- Vague sub-questions ("Overview of X") produce vague claims and low coverage. Prefer measurable angles.
- Queries that copy the sub-question verbatim search poorly. Keep them 3–8 words with names, years, units.

## Test
`tests/test_graph_offline.py` exercises plan and gap planning with `FakeMesh`. Add a case there
for any change to how sub-questions or gap queries are produced.
