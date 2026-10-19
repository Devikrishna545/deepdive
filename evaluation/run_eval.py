"""Self-evaluation runner. Every number it prints is written to evaluation/results/ and the README.

Usage (needs MESH_API_KEY; every command spends credits, so start small):
    python -m evaluation.run_eval --set verifier                         # 16 short calls, cents
    python -m evaluation.run_eval --set questions --limit 3 --max-usd 0.5
    python -m evaluation.run_eval --set questions --limit 3 --ablation   # normal run AND verification off
    python -m evaluation.run_eval --set all --limit 5 --depth quick --max-usd 1.0
    python -m evaluation.run_eval --set all --limit 10 --ablation --reuse-hours 6   # resume: reuse finished runs

The question set stops early when --max-usd is spent or the Mesh balance falls below
MIN_BALANCE_STOP_USD; the stop reason is recorded in the results file.

Groundedness is judged by MODEL_JUDGE, a different model from the verifier, so the
system is not grading itself with the same model it used to filter claims.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from evaluation.metrics import (
    claim_pass_rate,
    loop_back_rate,
    report_sentences,
    safe_div,
    uncited_rate,
    verifier_confusion,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
README = ROOT.parent / "README.md"


class CoverageOut(BaseModel):
    covered: list[bool]


def _load(name: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / name).read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------ verifier on labelled pairs
def eval_verifier() -> dict:
    from app.agents.verifier.agent import VerifierAgent
    from app.core.schemas import Chunk, Claim, Source

    agent = VerifierAgent()
    rows, pairs = [], []
    for p in _load("verifier_pairs.jsonl"):
        chunk = Chunk(id="chk_eval", source_id="src_eval", sub_question_id="sq_eval", text=p["chunk"])
        claim = Claim(id=f"clm_{p['id']}", sub_question_id="sq_eval", text=p["claim"], cited_chunk_ids=[chunk.id])
        verdict = agent._judge(claim, {chunk.id: chunk}, {"src_eval": Source(id="src_eval", url="eval://pair")})
        pairs.append((p["gold"], verdict.label.value))
        rows.append({"id": p["id"], "gold": p["gold"], "pred": verdict.label.value, "reason": verdict.reason,
                     "guard_downgraded": verdict.guard_downgraded})
    return verifier_confusion(pairs) | {"rows": rows}


# ------------------------------------------------------------------ full runs on test questions
# The judge (gemini-2.5-flash) is a thinking model: hidden reasoning counts against max_tokens. A 100-250
# cap made it stop before answering, and 1500 still cut off a verdict mid-JSON on a live run. Only tokens
# actually used are billed, so a generous cap costs nothing extra. Low effort keeps the thinking short.
JUDGE_MAX_TOKENS = 4000


def _judge_groundedness(report: dict, snapshot: dict, judge_model: str) -> dict:
    from app.agents.base import chunk_block, load_prompt
    from app.core.guards import apply_quote_guard
    from app.core.schemas import Verdict, VerdictLabel, VerdictOut
    from app.llm.mesh_client import MeshError, get_mesh

    claims = {c["id"]: c for c in snapshot["claims"]}
    chunks = snapshot["chunks"]
    labels = []
    errors = 0
    for sentence in report_sentences(report):
        chunk_ids = {cid for claim_id in sentence["claim_ids"] for cid in claims.get(claim_id, {}).get("cited_chunk_ids", [])}
        texts = [chunks[c]["text"] for c in chunk_ids if c in chunks]
        if not texts:
            labels.append("UNSUPPORTED")
            continue
        try:
            out = get_mesh().chat_json(
                model=judge_model,
                system=load_prompt("verifier"),
                user=f"CLAIM: {sentence['text']}\n\nSOURCE:\n" + "\n\n".join(chunk_block(c, chunks[c]["text"]) for c in chunk_ids if c in chunks),
                schema=VerdictOut,
                max_tokens=JUDGE_MAX_TOKENS,
                reasoning_effort="low",
            )
        except MeshError as exc:  # a judge failure is counted and reported, never silently dropped
            if "402" in str(exc):
                raise
            errors += 1
            continue
        v = apply_quote_guard(Verdict(claim_id="eval", label=out.label, reason=out.reason, evidence_quote=out.evidence_quote), texts)
        labels.append(v.label.value)
    n = len(labels)
    return {
        "sentences": n + errors,
        "judge_errors": errors,  # sentences the judge could not grade (excluded from the rates below)
        "groundedness": safe_div(labels.count(VerdictLabel.SUPPORTED.value), n),
        "partial_rate": safe_div(labels.count(VerdictLabel.PARTIAL.value), n),
    }


def _judge_coverage(question: dict, markdown: str, judge_model: str) -> float | None:
    from app.llm.mesh_client import MeshError, get_mesh

    points = question["must_cover"]
    try:
        out = _coverage_call(points, markdown, judge_model, get_mesh())
    except MeshError as exc:
        if "402" in str(exc):
            raise
        return None  # reported as missing coverage for this question, not as zero
    return safe_div(sum(out.covered[: len(points)]), len(points))


def _coverage_call(points: list[str], markdown: str, judge_model: str, mesh):
    return mesh.chat_json(
        model=judge_model,
        system="For each KEY POINT, answer true if the REPORT clearly covers it, else false. "
        "Return `covered` as a list of booleans in the same order as the key points.",
        user="KEY POINTS:\n" + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(points)) + f"\n\nREPORT:\n{markdown[:12000]}",
        schema=CoverageOut,
        max_tokens=JUDGE_MAX_TOKENS,
        reasoning_effort="low",
    )


def eval_questions(limit: int | None, ablation: bool, depth: str, max_usd: float, reuse_hours: float = 0.0) -> dict:
    """Run test questions until `limit`, the Mesh balance floor, or `max_usd` spent, whichever comes first.

    reuse_hours > 0: a question that already has a finished eval run of the same kind (same depth,
    verification on/off by id prefix) from the last `reuse_hours` is judged again without paying for
    a new research run. Used to resume after an interrupted evaluation."""
    os.environ["VERIFY_ENABLED"] = "false" if ablation else "true"
    from app.config import get_settings

    get_settings.cache_clear()
    from app.core.utils import new_id
    from app.db import repository as repo
    from app.db.session import init_db
    from app.llm.billing import InsufficientBalance, require_balance
    from app.llm.usage import start_collecting, stop_collecting
    from app.services.run_service import execute_run

    init_db()
    judge = get_settings().model_judge
    prefix = "evalab" if ablation else "eval"  # ablation runs never get mixed up with normal ones
    since = datetime.now(timezone.utc) - timedelta(hours=reuse_hours)
    rows, spent, stopped = [], 0.0, None
    for q in _load("questions.jsonl")[:limit]:
        if spent >= max_usd:
            stopped = f"eval budget ${max_usd:.2f} reached after {len(rows)} question(s)"
            break
        try:
            require_balance()
        except InsufficientBalance as exc:
            stopped = str(exc)
            break
        started = time.perf_counter()
        previous = repo.latest_done_run(q["question"], depth, f"{prefix}_", since) if reuse_hours > 0 else None
        if previous:
            run_id, reused = previous.id, True
        else:
            run_id, reused = new_id(prefix), False
            repo.create_run(run_id, q["question"], depth, [])
            try:
                execute_run(run_id, q["question"], depth, [])
            except Exception as exc:  # record failures honestly instead of skipping them
                failed = repo.get_run(run_id)
                spent += failed.cost_usd if failed else 0.0
                rows.append({"id": q["id"], "category": q["category"], "error": str(exc)})
                continue
        run = repo.get_run(run_id)
        report, snapshot = json.loads(run.report_json), json.loads(run.snapshot_json)
        collector, token = start_collecting()  # judge calls are priced too
        try:
            judged = {"coverage": _judge_coverage(q, report["markdown"], judge),
                      **_judge_groundedness(report, snapshot, judge)}
        finally:
            stop_collecting(token)
        run_cost = run.cost_usd + collector.cost_usd  # the run's own cost, even when reused
        spent += collector.cost_usd if reused else run_cost  # only what this command actually paid
        print(f"  {q['id']}: ${run_cost:.4f}{' (reused run)' if reused else ''} (spent now ${spent:.4f})")
        rows.append(
            {
                "id": q["id"],
                "category": q["category"],
                "run_id": run_id,
                "reused_run": reused,
                "seconds": round(time.perf_counter() - started, 1),
                "tokens": run.tokens,
                "cost_usd": round(run_cost, 5),
                "uncited_rate": uncited_rate(report),
                "claim_pass_rate": claim_pass_rate(snapshot),
                "loop_back_rate": loop_back_rate(snapshot),
                "claims_removed": sum(1 for c in snapshot["claims"] if not c["kept"]),
                **judged,
            }
        )
    ok = [r for r in rows if "error" not in r]

    def mean(key):
        vals = [r[key] for r in ok if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {k: mean(k) for k in ("groundedness", "partial_rate", "uncited_rate", "coverage", "claim_pass_rate",
                                     "loop_back_rate", "seconds", "tokens", "cost_usd")}
    summary["judge_errors"] = sum(r.get("judge_errors", 0) for r in ok)
    return {"ablation": ablation, "judge_model": judge, "depth": depth, "runs": len(rows),
            "failed": len(rows) - len(ok), "total_cost_usd": round(spent, 4), "stopped_early": stopped,
            "summary": summary, "rows": rows}


# ------------------------------------------------------------------ write results
def _readme_table(results: dict) -> str:
    lines = [f"_Last run: {results['timestamp']}. Raw numbers: `{results['file']}`._", ""]
    if "verifier" in results:
        v = results["verifier"]
        lines += ["**Verifier on labelled pairs**", "", "| Pairs | Bad-citation recall | Bad-citation precision | Exact label accuracy |",
                  "| --- | --- | --- | --- |",
                  f"| {v['n']} | {v['bad_citation_recall']} | {v['bad_citation_precision']} | {v['exact_label_accuracy']} |", ""]
    for key, title in (("questions", "With verification"), ("ablation", "Ablation: verification off")):
        if key in results:
            s = results[key]["summary"]
            lines += [f"**Full runs: {title}** ({results[key]['runs']} questions, judge `{results[key]['judge_model']}`)", "",
                      "| Groundedness | Uncited sentences | Coverage | Claim pass rate | Loop-back rate | Avg seconds | Avg tokens | Avg cost (USD) |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- |",
                      f"| {s['groundedness']} | {s['uncited_rate']} | {s['coverage']} | {s['claim_pass_rate']} | "
                      f"{s['loop_back_rate']} | {s['seconds']} | {s['tokens']} | {s['cost_usd']} |", ""]
            if s.get("judge_errors"):
                lines += [f"_{s['judge_errors']} sentence(s) could not be graded by the judge and are excluded from groundedness._", ""]
    return "\n".join(lines)


def write_results(results: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS / f"eval_{stamp}.json"
    results |= {"timestamp": stamp, "file": str(path.relative_to(ROOT.parent))}
    path.write_text(json.dumps(results, indent=2, default=str))
    if README.exists():
        text = README.read_text()
        block = f"<!-- EVAL:START -->\n{_readme_table(results)}\n<!-- EVAL:END -->"
        README.write_text(re.sub(r"<!-- EVAL:START -->.*?<!-- EVAL:END -->", lambda _: block, text, flags=re.S))
    return path


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=["verifier", "questions", "all"], default="verifier")
    parser.add_argument("--limit", type=int, default=5, help="only the first N questions (default 5 to save credits)")
    parser.add_argument("--depth", choices=["quick", "standard"], default="quick")
    parser.add_argument("--max-usd", type=float, default=1.0, help="stop the question set after this much spend")
    parser.add_argument("--reuse-hours", type=float, default=0.0,
                        help="resume: reuse finished eval runs from the last N hours instead of paying for them again")
    parser.add_argument("--ablation", action="store_true",
                        help="questions: also run the same questions with verification off (both go in one README block)")
    args = parser.parse_args()

    results: dict = {}
    if args.set in ("verifier", "all"):
        results["verifier"] = eval_verifier()
        print("verifier:", {k: v for k, v in results["verifier"].items() if k != "rows"})
    if args.set in ("questions", "all"):
        # The ablation runs in the same call as the normal run: write_results replaces the README
        # block, so two separate calls would leave only the last one's table.
        for ablation in ([False, True] if args.ablation else [False]):
            key = "ablation" if ablation else "questions"
            results[key] = eval_questions(args.limit, ablation, args.depth, args.max_usd, args.reuse_hours)
            print(f"{key}:", results[key]["summary"])
    print("written to", write_results(results))


if __name__ == "__main__":
    main()
