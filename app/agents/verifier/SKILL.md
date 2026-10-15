---
name: verifier-agent
description: Contract and guardrails for the DeepDive Verifier agent (one claim vs. its cited chunk text -> SUPPORTED / PARTIAL / UNSUPPORTED / CONTRADICTED, with quote guard and narrowing). The core of the track. Read before editing app/agents/verifier/, app/core/guards.py or app/core/contradictions.py.
---

# Verifier agent (the core of Track 01)

## Job
`verify(claim, chunks, sources)` -> `[(claim, verdict)]`, plus `(narrowed_child, child_verdict)`
when the verdict is PARTIAL with a `narrowed_claim`.

Per claim:
0. **Verbatim fast path (code, free):** if the claim equals a WHOLE sentence of a cited chunk, it is
   SUPPORTED without an LLM call (`model="code:verbatim"`). Whole-sentence equality, never substring,
   so a fragment of a denial ("…deny that prices will rise") cannot pass.
1. **Precheck (code):** numbers in the claim missing from the cited text -> `precheck_hints`.
2. **LLM judgement:** `VerdictOut` = label, reason, exact evidence quote, narrowed claim. Precheck
   hints are passed as one `CHECK:` line to make the model stricter. `max_tokens=250`.
3. **Quote guard (code):** if the quote is not literally in the cited chunk text
   (whitespace/quote-normalised, >= 12 chars), SUPPORTED/PARTIAL becomes UNSUPPORTED and
   `guard_downgraded=True`.
4. **Narrowing:** a PARTIAL claim's narrowed version is verified once; only SUPPORTED claims are kept.

| Label | Action | Shown in report |
| --- | --- | --- |
| SUPPORTED | keep | green citation mark |
| PARTIAL | verify narrowed child once; parent never kept | amber mark if the child passes |
| UNSUPPORTED | drop; counts toward coverage gap; reason feeds gap queries | trail + Claims tab |
| CONTRADICTED | drop | trail + Claims tab |

Model: `MODEL_VERIFIER`, temperature 0. **Must be a different model family from the Drafter**
so the system is not checking itself. Prompt: `prompt.md`.

## Guardrails (do not weaken)
- **Isolation:** the verifier sees ONE claim and ONLY the text of the chunks it cites. Never pass
  the question, the draft, other claims, or the source's other chunks.
- Own knowledge never counts. "True but not in the source" is UNSUPPORTED.
- Never remove or loosen the quote guard to raise numbers. If good claims are being rejected,
  fix the prompt or retrieval and measure on `evaluation/data/verifier_pairs.jsonl`.
- Ablation (`VERIFY_ENABLED=false`) uses `passthrough()`; it exists only for the eval comparison.
- Every non-SUPPORTED verdict must carry a reason (shown to judges in the trail).
- Contradiction detection (`app/core/contradictions.py`) reuses this model to judge pairs of
  kept claims from different sources; disagreements are reported, never silently resolved.

## Cost
The verifier is the biggest cost line (one call per non-verbatim claim on the strongest model).
Lower it by drafting fewer, better claims, not by weakening checks. If credits run very low,
`MODEL_VERIFIER` can move to a cheaper model of a different family from the drafter (and then
`MODEL_JUDGE` must change too); measure on `verifier_pairs.jsonl` before and after.

## Tuning loop
1. `python -m evaluation.run_eval --set verifier`
2. Look at rows where gold != pred. Adjust `prompt.md` wording, not the guard.
3. Target: bad-citation recall >= 0.85, precision >= 0.80. Report honest numbers either way.

## Test
`tests/test_core.py` (quote guard, precheck) and `tests/test_graph_offline.py` (fabricated claim
rejected end to end). Both must keep passing.
