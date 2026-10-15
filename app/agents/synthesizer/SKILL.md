---
name: synthesizer-agent
description: Contract and guardrails for the DeepDive Synthesizer agent (kept claims -> structured report whose every sentence lists claim IDs; followed by the deterministic citation check). Read before editing app/agents/synthesizer/ or app/core/citation_check.py.
---

# Synthesizer agent

## Job
`synthesize(question, sub_questions, kept_claims, contradictions, coverage)` -> `Report` with an
executive summary, one section per sub-question, disagreements and limitations. Every sentence
carries `claim_ids`. The `cite_check` node then removes sentences without a kept claim ID,
numbers the references and renders Markdown.

## Inputs / outputs
| In | Out (LLM schema) | Then |
| --- | --- | --- |
| KEPT claims grouped by sub-question, disagreements | `SynthesisOut` | `enforce_citations` -> `build_references` -> `render_markdown` |

Model: `MODEL_SYNTHESIZER`, temperature <= 0.3. Prompt: `prompt.md`.

## Guardrails
- It only ever receives kept (SUPPORTED) claims. Never pass rejected claims "for context".
- Every sentence must list claim IDs. No new facts, numbers, causes, forecasts or advice.
- A sub-question with no kept claims gets an empty section, not filler. Sections below the
  coverage bar are marked `limited_evidence` by code.
- Disagreements are stated neutrally with both claims cited. Each claim arrives as `[clm_x] (tier)`
  (official / academic / news / other, from `app/core/scoring.py::source_label`); on a conflict
  the official claim leads.
- Section headings are set by code from the sub-question text (`SectionOut` has no heading), so
  no heading can assert anything unverified.
- A sub-question marked `(PREMISE CHECK)` tests an assumption in the question; if its claims show
  the assumption is false, the first summary sentence says so.
- After the model writes, `app/core/key_claims.py::fill_key_claims` appends (max 2 per section) kept
  claims that are not cited anywhere, whose figure (not a year) another kept claim from a different
  passage also states, and whose figures are not already in the report. Each added sentence is the
  claim text cited to that claim.
- If the model's output stays invalid after one repair, `fallback_synthesis` builds the report
  from the kept claims in code (noted in Limitations) instead of failing the run.
- No investment, legal or tax advice, even when the question asks "should I…".
- The citation check is code and has the final word: sentences it removes are logged in
  `dropped_sentences` and shown in the trail. Do not move this check into the prompt.

## Failure modes to watch
- Pretty but uncited transition sentences: they will be dropped; keep the prose plain.
- Merging two claims into a sentence that says more than either: cite both and say only what both say.

## Test
`FakeMesh` adds one uncited sentence; the offline test asserts it is removed and that every
remaining sentence has claim IDs.
