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
- Disagreements are stated neutrally with both claims cited.
- No investment, legal or tax advice, even when the question asks "should I…".
- The citation check is code and has the final word: sentences it removes are logged in
  `dropped_sentences` and shown in the trail. Do not move this check into the prompt.

## Failure modes to watch
- Pretty but uncited transition sentences: they will be dropped; keep the prose plain.
- Merging two claims into a sentence that says more than either: cite both and say only what both say.

## Test
`FakeMesh` adds one uncited sentence; the offline test asserts it is removed and that every
remaining sentence has claim IDs.
