# evaluation/ — self-evaluation (rewarded heavily by the judges)

- `data/questions.jsonl`: test questions with hand-written `must_cover` key points
  (categories: market, finance, policy, science-tech, recent-events, false-premise).
- `data/verifier_pairs.jsonl`: labelled `(claim, chunk, gold)` pairs. Seed set of 16; grow it
  to 40–60 from real runs (take kept claims as SUPPORTED, pair them with a different chunk for
  UNSUPPORTED, change a number or direction for CONTRADICTED). Hand-check every row you add.
- `metrics.py`: pure metric functions. `run_eval.py`: runner. `results/`: committed outputs.

Rules:
1. Numbers in the README come only from `run_eval.py` (it rewrites the block between
   `<!-- EVAL:START -->` and `<!-- EVAL:END -->`). Never edit that block by hand.
2. Groundedness is judged by `MODEL_JUDGE`, which must differ from `MODEL_VERIFIER`.
3. Always run the ablation (`--ablation`) next to the normal run, with the same questions.
4. Report failures and low numbers honestly; failed runs are counted, not skipped.
5. Never use `scripts/offline_demo.py` or `FakeMesh` output as evaluation evidence.
