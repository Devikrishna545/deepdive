"""Benchmark runner: 10 fact-checked questions, scored stage by stage. Regression check, not the README eval.

Usage (needs MESH_API_KEY and internet; spends credits, so the caps are on by default):
    python -m evaluation.run_benchmark                       # all 10, quick depth, stops at $1.50
    python -m evaluation.run_benchmark --ids b01,b08 --max-usd 0.4
    python -m evaluation.run_benchmark --reuse                # skip questions that already have a finished run
    python -m evaluation.run_benchmark --no-judge            # skip the judge call (anchor scores only)
    python -m evaluation.run_benchmark --rescore evaluation/results/benchmark_<stamp>.json
                                                             # re-score stored runs: no new runs

Writes evaluation/results/benchmark_<stamp>.json (everything) and .md (readable summary).
The judge model (MODEL_JUDGE) must differ from the verifier model.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from evaluation.benchmark import STAGES, judge_facts, score_question, summarize

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "benchmark.jsonl"
RESULTS = ROOT / "results"


def load_benchmark(ids: list[str] | None = None) -> list[dict]:
    rows = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    return [r for r in rows if not ids or r["id"] in ids]


def _score_stored(q: dict, run_id: str, judge: str | None) -> dict:
    """Score one finished run from the DB. Only the optional judge call costs credits."""
    from app.db import repository as repo
    from app.llm.usage import start_collecting, stop_collecting
    from app.services.usage_service import run_usage_breakdown

    run = repo.get_run(run_id)
    if run is None or run.status != "done":
        return {"id": q["id"], "run_id": run_id, "error": f"run status: {run.status if run else 'missing'}",
                "cost_usd": run.cost_usd if run else 0.0}
    report, snapshot = json.loads(run.report_json or "{}"), json.loads(run.snapshot_json or "{}")
    judged, judge_cost = None, 0.0
    if judge:
        collector, token = start_collecting()
        try:
            judged = judge_facts(q, report, judge)
        except Exception as exc:  # a judge failure must not hide the anchor scores
            judged = None
            print(f"  {q['id']}: judge failed: {exc}")
        finally:
            stop_collecting(token)
        judge_cost = collector.cost_usd
    return {"id": q["id"], "category": q["category"], "question": q["question"], "run_id": run_id,
            "cost_usd": round(run.cost_usd + judge_cost, 5), "judge_cost_usd": round(judge_cost, 5),
            "tokens": run.tokens, "usage": run_usage_breakdown(run_id),
            **score_question(q, report, snapshot, judged)}


def latest_done_run(question: str, depth: str) -> str | None:
    """Most recent finished benchmark run for this exact question and depth (for --reuse)."""
    from app.db import repository as repo

    for run in repo.list_runs(500):
        if run.id.startswith("bench_") and run.status == "done" and run.question == question and run.depth == depth:
            return run.id
    return None


def run_benchmark(questions: list[dict], depth: str, max_usd: float, judge: str | None,
                  reuse: bool = False) -> tuple[list[dict], str | None]:
    from app.core.utils import new_id
    from app.db import repository as repo
    from app.llm.billing import InsufficientBalance, require_balance
    from app.services.run_service import execute_run
    from app.tools.search import NoEvidence

    rows, spent, stopped = [], 0.0, None
    for q in questions:
        if spent >= max_usd:
            stopped = f"benchmark budget ${max_usd:.2f} reached after {len(rows)} question(s)"
            break
        try:
            require_balance()
        except InsufficientBalance as exc:
            stopped = str(exc)
            break
        previous = latest_done_run(q["question"], depth) if reuse else None
        if previous:  # score the stored run again: only the judge call costs anything
            print(f"{q['id']}: reusing finished run {previous}")
            row = _score_stored(q, previous, judge) | {"reused": True}
            spent += row.get("judge_cost_usd", 0.0)
            rows.append(row)
            continue
        run_id = new_id("bench")
        repo.create_run(run_id, q["question"], depth, [])
        started = time.perf_counter()
        print(f"{q['id']}: {q['question']}")
        try:
            execute_run(run_id, q["question"], depth, [])
        except Exception as exc:  # failed runs are counted, never skipped
            run = repo.get_run(run_id)
            cost = run.cost_usd if run else 0.0
            spent += cost
            rows.append({"id": q["id"], "category": q["category"], "question": q["question"], "run_id": run_id,
                         "error": f"{type(exc).__name__}: {exc}", "cost_usd": cost,
                         "seconds": round(time.perf_counter() - started, 1)})
            print(f"  FAILED: {exc}")
            if isinstance(exc, NoEvidence):  # search is down: later questions would fail the same way
                stopped = f"stopped at {q['id']}: web search returned nothing"
                break
            continue
        row = _score_stored(q, run_id, judge)
        row["seconds"] = round(time.perf_counter() - started, 1)
        spent += row.get("cost_usd", 0.0)
        rows.append(row)
        print(f"  facts {row.get('fact_coverage')} | judge {row.get('judge_fact_coverage')} | "
              f"cites {row.get('citation_accuracy')} | ${row.get('cost_usd', 0):.4f} (total ${spent:.4f})")
    return rows, stopped


# ------------------------------------------------------------------ readable summary
def _pct(x) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def to_markdown(result: dict) -> str:
    s = result["summary"]
    lines = [f"# Benchmark {result['timestamp']}", "",
             f"Depth `{result['depth']}`, judge `{result['judge_model'] or 'off'}`, "
             f"{s['questions']} questions ({s['failed']} failed), total ${s['total_cost_usd']}."
             + (f" Stopped early: {result['stopped_early']}." if result.get("stopped_early") else ""), "",
             "| Metric | Value |", "| --- | --- |",
             f"| Key facts in report (strict anchors) | {_pct(s['fact_coverage'])} |",
             f"| Key facts in report (judge) | {_pct(s['judge_fact_coverage'])} |",
             f"| Reported facts whose cited passage states them | {_pct(s['citation_accuracy'])} |",
             f"| Must-not-claim hits | {s['must_not_claim_hits']} |",
             f"| False premises corrected | {s['premise_corrected']} |",
             f"| Uncited sentences in reports | {s['uncited_sentences']} |",
             f"| Claim pass rate (kept / drafted) | {_pct(s['claim_pass_rate'])} |",
             f"| Avg seconds / cost per question | {s['avg_seconds']} s / ${s['avg_cost_usd']} |", "",
             "## Where missing facts were lost", "",
             "| " + " | ".join(STAGES) + " |", "|" + " --- |" * len(STAGES),
             "| " + " | ".join(str(s["facts_lost_at"][st]) for st in STAGES) + " |", "",
             "_retrieved = never in a fetched chunk (search); extracted = in a chunk but not in findings (researcher); "
             "drafted = in findings but no claim (drafter); verified = drafted but removed (verifier); "
             "reported = verified but not in the report (synthesizer)._", "",
             "## Per question", "",
             "| Q | Facts (anchor / judge) | Cites ok | Lost at | Must-not hits | Premise | Kept/drafted | Cost |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in result["rows"]:
        if "error" in r:
            lines.append(f"| {r['id']} | failed: {r['error'][:80]} | | | | | | ${r.get('cost_usd', 0):.4f} |")
            continue
        lost = ", ".join(f"{k}:{v}" for k, v in r["lost_at"].items() if v) or "–"
        lines.append(f"| {r['id']} | {_pct(r['fact_coverage'])} / {_pct(r.get('judge_fact_coverage'))} | "
                     f"{_pct(r['citation_accuracy'])} | {lost} | {len(r.get('must_not_claim_hits', []))} | "
                     f"{r.get('premise_corrected', '–')} | {r['claims_kept']}/{r['claims_drafted']} | ${r['cost_usd']:.4f} |")
    lines += ["", "## Tokens by agent (all questions)", "", "| Agent | Calls | Input | Output | Cost |", "| --- | --- | --- | --- | --- |"]
    for name, a in s["tokens_by_agent"].items():
        lines.append(f"| {name} | {a['calls']} | {a['prompt_tokens']} | {a['completion_tokens']} | ${a['cost_usd']} |")
    lines += ["", "## Facts not in the report", ""]
    for r in result["rows"]:
        for f in r.get("facts", []):
            if not f["stages"]["reported"]:
                why = "; ".join(f"{x['label']}: {x['reason']}" for x in f["rejections"][:2])
                lines.append(f"- **{r['id']}** {f['fact']} — lost at *{f['lost_at']}*" + (f" ({why})" if why else ""))
    return "\n".join(lines) + "\n"


def write(result: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = result["timestamp"]
    path = RESULTS / f"benchmark_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, default=str))
    path.with_suffix(".md").write_text(to_markdown(result))
    return path


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ids", help="comma-separated ids, e.g. b01,b08 (default: all)")
    p.add_argument("--depth", choices=["quick", "standard"], default="quick")
    p.add_argument("--max-usd", type=float, default=1.5, help="stop starting new questions after this spend")
    p.add_argument("--no-judge", action="store_true", help="anchor scores only (no judge call)")
    p.add_argument("--reuse", action="store_true",
                   help="score the latest finished run of a question instead of running it again (saves credits)")
    p.add_argument("--rescore", help="re-score the runs listed in an earlier benchmark JSON (no new runs)")
    args = p.parse_args()

    from app.config import get_settings
    from app.db.session import init_db

    init_db()
    s = get_settings()
    judge = None if args.no_judge else s.model_judge
    if judge and judge == s.model_verifier:
        raise SystemExit("MODEL_JUDGE must differ from MODEL_VERIFIER")

    if not args.rescore:
        from scripts.check_search import check

        if check() != 0:  # free: no point paying for runs that will find no sources
            raise SystemExit("Stopped before any paid call: web search is not working.")

    if args.rescore:
        old = json.loads(Path(args.rescore).read_text())
        qs = {q["id"]: q for q in load_benchmark()}
        rows = [_score_stored(qs[r["id"]], r["run_id"], judge) | {"seconds": r.get("seconds")} for r in old["rows"]]
        stopped, depth = old.get("stopped_early"), old["depth"]
    else:
        ids = args.ids.split(",") if args.ids else None
        rows, stopped = run_benchmark(load_benchmark(ids), args.depth, args.max_usd, judge, reuse=args.reuse)
        depth = args.depth

    result = {"timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "depth": depth,
              "judge_model": judge, "models": {k: getattr(s, f"model_{k}") for k in
                                               ("planner", "researcher", "drafter", "verifier", "synthesizer")},
              "stopped_early": stopped, "summary": summarize(rows), "rows": rows}
    path = write(result)
    print(json.dumps({k: v for k, v in result["summary"].items() if k != "tokens_by_agent"}, indent=2))
    print("written to", path, "and", path.with_suffix(".md"))


if __name__ == "__main__":
    main()
