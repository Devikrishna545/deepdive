---
name: drafter-agent
description: Contract and guardrails for the DeepDive Drafter agent (findings -> atomic claims, each citing the chunk it comes from). Read before editing app/agents/drafter/.
---

# Drafter agent

## Job
`draft(sub_question, findings, chunks, round)` -> atomic `Claim`s: one checkable fact each,
citing at least one chunk ID that the findings came from.

## Inputs / outputs
| In | Out (LLM schema) | Stored as |
| --- | --- | --- |
| sub-question, findings of THIS round (with chunk ids, no chunk text) | `ClaimsOut` | `list[Claim]` (IDs by code: `clm_…`) |

Model: `MODEL_DRAFTER` (cheap), temperature 0. Prompt: `prompt.md`.

## Guardrails
- Token rule: the drafter never receives chunk text (findings are already close to the source, and
  the verifier checks every claim against the full chunk). Don't add chunks back "for context".
- One fact per claim. Split compound statements so each part can be verified alone.
- Keep numbers, units, periods and hedges exactly as the chunk states them. No rounding,
  no combining figures, no added causes or predictions.
- Claims must be self-contained (name the subject and period; no "it", "this year").
- Years, places and numbers come only from the finding, never from the sub-question wording.
- Citations are filtered by code to chunks the drafter was given; a claim left with no
  citation is dropped before verification.
- On a loop-back round, draft only the new round's findings (the node does this); never
  re-draft already verified claims.
- The drafter does not judge truth; that is the verifier's job. Don't add self-checks that
  silently drop claims, because the trail must show what the verifier rejected and why.

## Failure modes to watch
- Over-generalising ("the market is booming") turns supported findings into unsupported claims.
- Copying a forecast as a fact: keep "expected", "forecast", "estimated".

## Test
`FakeMesh` drafts one fabricated claim per batch; the offline test asserts it is rejected.
Keep that behaviour if you change the fake.
