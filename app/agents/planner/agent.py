"""Planner agent: question -> sub-questions with search queries; thin topic -> gap queries."""

from __future__ import annotations

from datetime import date

from app.agents.base import load_prompt
from app.config import get_settings
from app.core.schemas import GapQueriesOut, PlanOut, SubQuestion
from app.core.utils import new_id
from app.llm.mesh_client import get_mesh


class PlannerAgent:
    name = "planner"

    def plan(self, question: str, depth: str = "standard") -> list[SubQuestion]:
        s = get_settings()
        limit = 3 if depth == "quick" else s.max_subquestions
        out = get_mesh().chat_json(
            model=s.model_planner,
            system=load_prompt(self.name),
            user=f"TODAY: {date.today().isoformat()}\nQUESTION: {question}\nMAX_SUB_QUESTIONS: {limit}",
            schema=PlanOut,
            temperature=0.0,
            max_tokens=500,
        )
        return [
            SubQuestion(id=new_id("sq"), text=sq.text.strip(), queries=sq.queries[:3], rationale=sq.rationale)
            for sq in out.sub_questions[:limit]
        ]

    def gap_queries(self, question: str, sub_question: SubQuestion, reasons: list[str]) -> list[str]:
        s = get_settings()
        user = (
            f"MAIN QUESTION: {question}\n"
            f"THIN SUB-QUESTION: {sub_question.text}\n"
            f"QUERIES ALREADY TRIED: {sub_question.queries}\n"
            f"WHY CLAIMS WERE REJECTED:\n" + "\n".join(f"- {r[:160]}" for r in reasons[:5] or ["too few sources"])
        )
        out = get_mesh().chat_json(
            model=s.model_planner,
            system=load_prompt(self.name, "gap_prompt.md"),
            user=user,
            schema=GapQueriesOut,
            temperature=0.0,
            max_tokens=150,
        )
        tried = {q.lower() for q in sub_question.queries}
        return [q for q in out.queries if q.lower() not in tried][:3]
