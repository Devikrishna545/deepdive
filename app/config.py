"""Central settings. Every tunable lives here and is read from the environment / .env.

Defaults are tuned for a SMALL credit balance: cheap models where volume is high, one
stronger model only where accuracy is decided (the verifier), and hard spend guards.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

MESH_BASE_URL = "https://api.meshapi.ai/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Mesh API: the only gateway for LLM and embedding calls
    mesh_api_key: str = ""
    mesh_base_url: str = MESH_BASE_URL

    # Models per agent. Run `python -m scripts.mesh_account` to see live prices and
    # confirm every id exists on your account before changing these.
    # Reasoning model: plans decide every search, so the planner is where thinking pays off most
    # (benchmark runs 1-5 swung up to 22 points on plan quality). 1-3 short calls per run.
    model_planner: str = "openai/gpt-oss-120b"
    model_planner_fallback: str = "openai/gpt-5-nano"  # used if the planner call fails or plans nothing
    # Reasoning effort for the planner models. gpt-5-nano at its default ("medium") effort spent all
    # 2500 tokens thinking and returned nothing; "low" leaves room for the answer.
    planner_reasoning_effort: str = "low"
    model_researcher: str = "openai/gpt-4o-mini"  # highest input volume: must be cheap
    model_drafter: str = "openai/gpt-4o-mini"
    model_verifier: str = "anthropic/claude-haiku-4.5"  # accuracy-critical; different family from drafter
    model_synthesizer: str = "openai/gpt-4o-mini"  # sees only short verified claims; citation check guards it
    model_judge: str = "google/gemini-2.5-flash"  # eval only; must differ from the verifier
    embedding_model: str = "openai/text-embedding-3-small"

    # Credit protection (USD). Balance is read from Mesh GET /v1/balance.
    low_balance_alert_usd: float = 5.0  # warn in UI, logs, /api/health and the run trail
    min_balance_stop_usd: float = 1.0  # refuse to start new runs below this
    run_budget_usd: float = 0.15  # stop a single run that costs more than this (live prices)
    run_token_budget: int = 250_000  # fallback guard when prices are unavailable

    # Web search (not an LLM call)
    tavily_api_key: str = ""
    tavily_search_depth: str = "basic"  # "basic" = 1 Tavily credit per search, "advanced" = 2

    # Pipeline knobs (each one trades tokens for coverage)
    max_subquestions: int = 4
    max_loops: int = 1
    min_supported_claims: int = 2
    min_distinct_domains: int = 2
    results_per_query: int = 4
    max_pages_per_subquestion: int = 4
    chunks_per_subquestion: int = 10
    max_concurrency: int = 4
    fetch_timeout_s: float = 10.0
    verify_enabled: bool = True
    cache_plans: bool = True  # reuse the plan for a repeated question (same model, prompt, month)
    contradiction_similarity: float = 0.85

    # Developer views (per-agent token usage). Set DEV_MODE=false for the demo / judges.
    dev_mode: bool = False  # True shows the developer token views; keep off for demos and judging
    # Public hosting: starting research or uploading spends Mesh credit, so a hosted demo can ask
    # for an access code (empty = open, for local use) and cap runs per 24 hours (0 = no cap).
    # Reading finished reports is always open.
    run_access_code: str = ""
    max_runs_per_day: int = 0

    # Storage
    database_url: str = "sqlite:///data/deepdive.db"
    upload_dir: str = "data/uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
