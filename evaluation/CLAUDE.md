# evaluation/ — self-evaluation (rewarded heavily by the judges)

- `data/questions.jsonl`: test questions with hand-written `must_cover` key points
  (categories: market, finance, policy, science-tech, recent-events, false-premise).
- `data/verifier_pairs.jsonl`: labelled `(claim, chunk, gold)` pairs. Seed set of 16; grow it
  to 40–60 from real runs (take kept claims as SUPPORTED, pair them with a different chunk for
  UNSUPPORTED, change a number or direction for CONTRADICTED). Hand-check every row you add.
- `data/benchmark.jsonl`: 10 regression questions, reference answers checked against official
  sources (2 false-premise). Each key fact has `anchors` (literal strings) so `benchmark.py` can
  trace it through every stage (retrieved -> extracted -> drafted -> verified -> reported) and say
  which agent lost it. Run: `python -m evaluation.run_benchmark` (quick depth, stops at $1.50).
  Re-score stored runs for free with `--rescore <json> --no-judge`. b08 depends on live EU
  legislation (2035 car CO2 target): recheck its status before each scored run.
- Benchmark history (files in `results/`): run 1 `113214Z` 69% strict facts after re-score; run 2
  `124603Z` 67%; run 3 `143510Z` 63%, 2/2 premises corrected, 0 must-not hits. Run 3's misses: 6
  lost at the writer (-> design decision 30; replay recovered the 2 b05 facts). Run 4 `171219Z`
  77% strict / 73% judge, but b08 regressed (no premise from the planner -> must-not hit). Run 5 `180904Z`
  (premise backstop, plan retry, figure check, new planner/writer prompts): 55% strict / 48% judge,
  worse plans ("2026" in IPCC queries, search losses 3 -> 7); code reverted to the run-4 state.
  Run 6 `20261017T043628Z`: planner gpt-5-nano (low effort; b01-b03 reused fallback plans from an
  interrupted run) -> 78% strict / 80% judge, 2/2 premises, 0 must-not hits, $0.209. Citation
  accuracy 97% after the scorer learned short month names ("02 Aug 2026"); the one real miss is a
  verified b09 claim that calls the block reward the "supply cap".
  Run 7 `20261018T083432Z`: all 10 plans made fresh by gpt-5-nano -> 50% strict / 51% judge. Nothing
  else changed: nano plans were weak (a premise check on "data centers use electricity", the word
  "TODAY" inside queries). Next: planner gpt-oss-120b + hybrid ranking (design decisions 34-35).
- `run_eval.py --ablation` runs the normal and the verification-off set in one call (one README
  block). After an interrupted run, add `--reuse-hours N` to re-judge finished runs (ids `eval_*`,
  ablation `evalab_*`) instead of paying for them again. A judge reply that stays invalid is counted
  as `judge_errors` and excluded from groundedness (shown under the README table), never dropped.
- `metrics.py`: pure metric functions. `run_eval.py`: runner. `results/`: committed outputs.

Rules:
1. Numbers in the README come only from `run_eval.py` (it rewrites the block between
   `<!-- EVAL:START -->` and `<!-- EVAL:END -->`). Never edit that block by hand.
2. Groundedness is judged by `MODEL_JUDGE`, which must differ from `MODEL_VERIFIER`.
3. Always run the ablation (`--ablation`) next to the normal run, with the same questions.
4. Report failures and low numbers honestly; failed runs are counted, not skipped.
5. Never use `scripts/offline_demo.py` or `FakeMesh` output as evaluation evidence.
