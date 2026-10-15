"""Metric definitions. Pure functions over stored run data so they are easy to test and explain."""

from __future__ import annotations

from collections.abc import Iterable

REJECT = {"UNSUPPORTED", "CONTRADICTED"}


def safe_div(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def report_sentences(report: dict) -> list[dict]:
    return report["executive_summary"] + [s for sec in report["sections"] for s in sec["sentences"]]


def uncited_rate(report: dict) -> float | None:
    sentences = report_sentences(report)
    return safe_div(sum(1 for s in sentences if not s["claim_ids"]), len(sentences))


def claim_pass_rate(snapshot: dict) -> float | None:
    """Share of drafted (non-narrowed) claims that ended up kept."""
    drafted = [c for c in snapshot["claims"] if not c.get("parent_claim_id")]
    kept_parent_ids = {c["parent_claim_id"] for c in snapshot["claims"] if c.get("parent_claim_id") and c["kept"]}
    passed = sum(1 for c in drafted if c["kept"] or c["id"] in kept_parent_ids)
    return safe_div(passed, len(drafted))


def loop_back_rate(snapshot: dict) -> float | None:
    loops = snapshot.get("loops", {})
    return safe_div(sum(1 for n in loops.values() if n > 0), len(loops))


def verifier_confusion(pairs: Iterable[tuple[str, str]]) -> dict:
    """pairs: (gold_label, predicted_label). Positive class = 'bad citation' (UNSUPPORTED/CONTRADICTED)."""
    tp = fp = fn = tn = exact = n = 0
    for gold, pred in pairs:
        n += 1
        exact += gold == pred
        gold_bad, pred_bad = gold in REJECT, pred in REJECT
        tp += gold_bad and pred_bad
        fp += (not gold_bad) and pred_bad
        fn += gold_bad and not pred_bad
        tn += (not gold_bad) and not pred_bad
    return {
        "n": n,
        "exact_label_accuracy": safe_div(exact, n),
        "bad_citation_recall": safe_div(tp, tp + fn),
        "bad_citation_precision": safe_div(tp, tp + fp),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }
