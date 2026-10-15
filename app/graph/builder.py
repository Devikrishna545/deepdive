"""The coordinator: a LangGraph StateGraph with parallel research and a verification loop.

    START -> plan -> (Send x N) research -> draft -> verify -> coverage_gate
        coverage_gate --gaps--> gap_plan -> (Send x gaps) research -> draft -> verify -> ...
        coverage_gate --ok----> cross_check -> synthesize -> cite_check -> END

The coordinator is code, not an LLM: routing, fan-out, loop counting and the citation
check are deterministic and unit-testable.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.graph import nodes
from app.graph.state import ResearchState
from app.graph.tracing import traced

RECURSION_LIMIT = 60


def fan_out(state: ResearchState) -> list[Send]:
    """One parallel `research` task per sub-question (first pass)."""
    return [
        Send(
            "research",
            {
                "run_id": state["run_id"],
                "question": state["question"],
                "sub_question": sq,
                "queries": sq.queries,
                "round": 0,
                "file_ids": state.get("file_ids", []),
            },
        )
        for sq in state["sub_questions"]
    ]


def fan_out_gaps(state: ResearchState) -> list[Send] | str:
    """Loop back: research only the thin sub-questions, with their new gap queries."""
    gap_queries = state.get("gap_queries", {})
    sends = [
        Send(
            "research",
            {
                "run_id": state["run_id"],
                "question": state["question"],
                "sub_question": sq,
                "queries": gap_queries[sq.id],
                "round": state.get("round", 1),
                "file_ids": state.get("file_ids", []),
            },
        )
        for sq in state["sub_questions"]
        if sq.id in gap_queries
    ]
    return sends or "cross_check"


def build_graph():
    g = StateGraph(ResearchState)
    for name in ("plan", "research", "draft", "verify", "gap_plan", "cross_check", "synthesize", "cite_check"):
        g.add_node(name, traced(name)(getattr(nodes, name)))

    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["research"])
    g.add_edge("research", "draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", nodes.coverage_gate, {"gaps": "gap_plan", "ok": "cross_check"})
    g.add_conditional_edges("gap_plan", fan_out_gaps, ["research", "cross_check"])
    g.add_edge("cross_check", "synthesize")
    g.add_edge("synthesize", "cite_check")
    g.add_edge("cite_check", END)
    return g.compile()


@lru_cache
def get_graph():
    return build_graph()
