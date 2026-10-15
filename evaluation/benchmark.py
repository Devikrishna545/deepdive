"""Benchmark scoring: pure functions over a stored run, so they are free to rerun and easy to test.

Every benchmark question has hand-checked `key_facts`. Each fact has `anchors`: groups of
literal strings (any one per group) that must ALL appear in the same piece of text for the
fact to count as present there. Matching runs at every stage of the pipeline, which turns
"fact missing from the report" into "fact lost at stage X":

    retrieved (chunks) -> extracted (findings) -> drafted (claims) -> verified (kept claims) -> reported (sentences)

A fact that is in the report must also be CITED correctly: the cited chunks of the sentence
that states it must contain the anchors too (`citation_ok`).

Anchors are a cheap, strict check; paraphrases ("one in five cars") can be missed. The optional
judge model (`judge_facts`) reads the report semantically and also checks the must-not-claim
list and, for false-premise questions, whether the premise was corrected.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from evaluation.metrics import report_sentences, safe_div

STAGES = ["retrieved", "extracted", "drafted", "verified", "reported"]


# ------------------------------------------------------------------ anchor matching
def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[‐-―−]", "-", text)  # unicode dashes
    text = text.replace(" ", " ").replace(" ", " ")
    text = re.sub(r"(?<=\d) (?=\d{3}\b)", ",", text)  # "375 000" -> "375,000"
    text = re.sub(r"(?<=\d) ?(%|per ?cent\b|percent\b)", "%", text)  # "9 %", "9 per cent" -> "9%"
    text = re.sub(r"(?<![\w.])0(\d)(?=\s+[a-z])", r"\1", text)  # "02 august 2026" -> "2 august 2026"
    return re.sub(r"\s+", " ", text)


def _has(anchor: str, text: str) -> bool:
    # left boundary only: "9%" must not match "19%" or "0.9%"; "alumin" may match "aluminium"
    return re.search(r"(?<![\w.])" + re.escape(norm(anchor)), text) is not None


def fact_in(anchors: list[list[str]], text: str) -> bool:
    t = norm(text)
    return all(any(_has(a, t) for a in group) for group in anchors)


def first_match(anchors: list[list[str]], items: list[tuple[str, str]]) -> str | None:
    """items: (id, text). Returns the id of the first item that contains the fact."""
    return next((i for i, text in items if fact_in(anchors, text)), None)


# ------------------------------------------------------------------ per-question scoring
def _sentences(report: dict) -> list[dict]:
    return report_sentences(report) if report else []


def trace_facts(question: dict, report: dict, snapshot: dict) -> list[dict]:
    """For every key fact: the furthest stage it reached, where it was lost, and citation check."""
    chunks = snapshot.get("chunks", {})
    claims = snapshot.get("claims", [])
    verdicts = {v["claim_id"]: v for v in snapshot.get("verdicts", [])}
    stage_items = {
        "retrieved": [(cid, c["text"]) for cid, c in chunks.items()],
        "extracted": [(str(i), f["text"]) for i, f in enumerate(snapshot.get("findings", []))],
        "drafted": [(c["id"], c["text"]) for c in claims],
        "verified": [(c["id"], c["text"]) for c in claims if c["kept"]],
        "reported": [(str(i), s["text"]) for i, s in enumerate(_sentences(report))],
    }
    sentences = _sentences(report)
    claim_by_id = {c["id"]: c for c in claims}
    out = []
    for fact in question["key_facts"]:
        hits = {stage: first_match(fact["anchors"], items) for stage, items in stage_items.items()}
        reached = [s for s in STAGES if hits[s] is not None]
        lost_at = next((s for s in STAGES if hits[s] is None), None)
        row = {"fact": fact["fact"], "stages": {s: hits[s] is not None for s in STAGES}, "lost_at": lost_at,
               "furthest": reached[-1] if reached else None, "citation_ok": None, "rejections": []}
        # claims that stated the fact but the verifier removed: the reasons say why
        for c in claims:
            if not c["kept"] and fact_in(fact["anchors"], c["text"]) and c["id"] in verdicts:
                v = verdicts[c["id"]]
                row["rejections"].append({"claim": c["text"], "label": v["label"], "reason": v["reason"],
                                          "guard_downgraded": v.get("guard_downgraded", False)})
        if hits["reported"] is not None:
            s = sentences[int(hits["reported"])]
            cited = [chunks[cid]["text"] for clm in s["claim_ids"] for cid in claim_by_id.get(clm, {}).get("cited_chunk_ids", [])
                     if cid in chunks]
            row["citation_ok"] = any(fact_in(fact["anchors"], t) for t in cited)
        out.append(row)
    return out


def score_question(question: dict, report: dict | None, snapshot: dict | None, judged: dict | None = None) -> dict:
    report, snapshot = report or {}, snapshot or {}
    facts = trace_facts(question, report, snapshot)
    n = len(facts)
    reported = [f for f in facts if f["stages"]["reported"]]
    row = {
        "facts": facts,
        "fact_coverage": safe_div(len(reported), n),  # strict, anchor-based
        "citation_accuracy": safe_div(sum(1 for f in reported if f["citation_ok"]), len(reported)),
        "lost_at": {s: sum(1 for f in facts if f["lost_at"] == s) for s in STAGES},
        "sentences": len(_sentences(report)),
        "uncited_sentences": sum(1 for s in _sentences(report) if not s["claim_ids"]),
        "claims_drafted": len(snapshot.get("claims", [])),
        "claims_kept": sum(1 for c in snapshot.get("claims", []) if c["kept"]),
        "sources": len(snapshot.get("sources", {})),
        "domains": sorted({s.get("domain", "") for s in snapshot.get("sources", {}).values()}),
    }
    if judged:
        covered = judged["covered"]
        row["judge_fact_coverage"] = safe_div(sum(covered), n)
        row["must_not_claim_hits"] = [m for m, hit in zip(question["must_not_claim"], judged["must_not"], strict=False) if hit]
        if question.get("false_premise"):
            row["premise_corrected"] = judged["premise_corrected"]
        for f, c in zip(facts, covered, strict=False):
            f["judge_covered"] = c
    return row


# ------------------------------------------------------------------ judge (one cheap call per question)
# The judge (gemini-2.5-flash) is a "thinking" model: hidden reasoning counts against max_tokens.
# The reply itself is ~40 tokens; the rest is room to think. A live run failed at 120.
JUDGE_MAX_TOKENS = 1500


class BenchJudgeOut(BaseModel):
    covered: list[bool]
    must_not: list[bool]
    premise_corrected: bool | None = None


JUDGE_SYSTEM = (
    "You grade a research report against a reference. Read only the REPORT. "
    "covered[i]=true if the report clearly states KEY FACT i (paraphrase is fine, numbers must match). "
    "must_not[i]=true if the report asserts FALSE CLAIM i as true (mentioning it only to deny it is false). "
    "premise_corrected=true ONLY if the report explicitly says the question's PREMISE did not happen or is false; "
    "discussing related facts or a different date is not enough. null if no premise is given."
)


def judge_prompt(question: dict, report: dict) -> str:
    facts = "\n".join(f"{i + 1}. {f['fact']}" for i, f in enumerate(question["key_facts"]))
    wrong = "\n".join(f"{i + 1}. {m}" for i, m in enumerate(question["must_not_claim"]))
    premise = question.get("premise") if question.get("false_premise") else "none"
    body = "\n".join(s["text"] for s in _sentences(report))[:8000]
    return f"QUESTION: {question['question']}\nPREMISE: {premise}\n\nKEY FACTS:\n{facts}\n\nFALSE CLAIMS:\n{wrong}\n\nREPORT:\n{body}"


def judge_facts(question: dict, report: dict, model: str) -> dict:
    from app.llm.mesh_client import get_mesh

    out = get_mesh().chat_json(model=model, system=JUDGE_SYSTEM, user=judge_prompt(question, report),
                               schema=BenchJudgeOut, max_tokens=JUDGE_MAX_TOKENS)
    n_f, n_m = len(question["key_facts"]), len(question["must_not_claim"])
    pad = lambda xs, n: (list(xs) + [False] * n)[:n]  # noqa: E731 - tolerate short lists
    return {"covered": pad(out.covered, n_f), "must_not": pad(out.must_not, n_m),
            "premise_corrected": out.premise_corrected}


# ------------------------------------------------------------------ aggregate
def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]

    def mean(key):
        vals = [r[key] for r in ok if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    facts = [f for r in ok for f in r["facts"]]
    premise = [r["premise_corrected"] for r in ok if "premise_corrected" in r]
    agents: dict[str, dict] = {}
    for r in ok:
        for a in r.get("usage", {}).get("agents", []):
            t = agents.setdefault(a["agent"], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
            for k in t:
                t[k] += a[k]
    for t in agents.values():
        t["cost_usd"] = round(t["cost_usd"], 5)
    return {
        "questions": len(rows),
        "failed": len(rows) - len(ok),
        "facts_total": len(facts),
        "fact_coverage": mean("fact_coverage"),
        "judge_fact_coverage": mean("judge_fact_coverage"),
        "citation_accuracy": mean("citation_accuracy"),
        "facts_lost_at": {s: sum(1 for f in facts if f["lost_at"] == s) for s in STAGES},
        "must_not_claim_hits": sum(len(r.get("must_not_claim_hits", [])) for r in ok),
        "premise_corrected": f"{sum(1 for p in premise if p)}/{len(premise)}" if premise else None,
        "uncited_sentences": sum(r["uncited_sentences"] for r in ok),
        "claim_pass_rate": safe_div(sum(r["claims_kept"] for r in ok), sum(r["claims_drafted"] for r in ok)),
        "avg_seconds": mean("seconds"),
        "avg_cost_usd": mean("cost_usd"),
        "total_cost_usd": round(sum(r.get("cost_usd", 0.0) for r in rows), 4),
        "tokens_by_agent": agents,
    }
