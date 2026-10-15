"""The five DeepDive agents. Each has its own folder, prompt, schema and SKILL.md."""

from app.agents.drafter.agent import DrafterAgent
from app.agents.planner.agent import PlannerAgent
from app.agents.researcher.agent import ResearcherAgent, ResearchResult
from app.agents.synthesizer.agent import SynthesizerAgent
from app.agents.verifier.agent import VerifierAgent

__all__ = [
    "PlannerAgent",
    "ResearcherAgent",
    "ResearchResult",
    "DrafterAgent",
    "VerifierAgent",
    "SynthesizerAgent",
]
