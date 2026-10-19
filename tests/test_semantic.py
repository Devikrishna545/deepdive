"""Hybrid ranking: meaning (embeddings) + keywords. The transformer case from a live run:
an AI question must not pull in pages about power-grid transformers."""

from __future__ import annotations

from app.agents.researcher import agent as researcher_module
from app.agents.researcher.agent import ResearcherAgent, ResearchResult
from app.llm import mesh_client
from app.tools.search import SearchHit
from app.tools.semantic import hybrid_scores, keep_on_topic, similarities

AI = ["neural", "attention", "language", "model", "ai", "artificial", "intelligence", "deep", "learning"]
GRID = ["power", "grid", "voltage", "electric", "substation", "utility"]


class TopicMesh:
    """Embeds by topic words, like a real model would separate the two meanings of 'transformer'."""

    def embed(self, texts, model=None):
        return [[sum(w in t.lower() for w in AI) + 0.1, sum(w in t.lower() for w in GRID) + 0.1] for t in texts]


class BrokenMesh:
    def embed(self, texts, model=None):
        raise RuntimeError("embedding endpoint down")


def test_off_topic_results_are_dropped_and_floor_keeps_two():
    assert keep_on_topic([0.9, 0.85, 0.2], 3) == [True, True, False]
    assert keep_on_topic([0.9, 0.1, 0.05], 3) == [True, True, False]  # never fewer than two
    assert keep_on_topic(None, 2) == [True, True]  # embeddings unavailable: keep all


def test_hybrid_scores_and_keyword_fallback():
    assert hybrid_scores([1.0, 0.5], None) == [1.0, 0.5]
    mixed = hybrid_scores([1.0, 1.0], [0.2, 0.8])  # same keywords, different meaning
    assert mixed[1] > mixed[0]


def test_embedding_failure_never_fails_ranking():
    mesh_client.set_mesh(BrokenMesh())
    assert similarities("q", ["a", "b"]) is None


def test_researcher_skips_grid_transformer_page(monkeypatch):
    hits = [
        SearchHit(url="https://arxiv.org/abs/1706.03762", title="Attention Is All You Need",
                  snippet="The Transformer, a neural network model based on attention, for language AI."),
        SearchHit(url="https://example.edu/llm", title="Transformers in deep learning",
                  snippet="Large language models use the transformer architecture for artificial intelligence."),
        SearchHit(url="https://energy.gov/transformers", title="Large Power Transformer Resilience",
                  snippet="Power transformers step voltage on the electric grid at a utility substation."),
    ]
    monkeypatch.setattr(researcher_module, "web_search", lambda q: hits)
    mesh_client.set_mesh(TopicMesh())
    result = ResearchResult()
    kept = ResearcherAgent()._collect_hits(["transformers breakthrough"], "Are transformers the breakthrough in AI?", result)
    assert {h.url for h in kept} == {"https://arxiv.org/abs/1706.03762", "https://example.edu/llm"}
    assert result.urls_skipped == ["https://energy.gov/transformers"]
