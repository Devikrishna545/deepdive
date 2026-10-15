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
    model_planner: str = "openai/gpt-4o-mini"  # 1-3 short calls per run
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

    # Pipeline knobs (each one trades tokens for coverage)
    max_subquestions: int = 4
    max_loops: int = 1
    min_supported_claims: int = 2
    min_distinct_domains: int = 2
    results_per_query: int = 4
    max_pages_per_subquestion: int = 4
    chunks_per_subquestion: int = 8
    max_concurrency: int = 4
    fetch_timeout_s: float = 10.0
    verify_enabled: bool = True
    contradiction_similarity: float = 0.85

    # Developer views (per-agent token usage). Set DEV_MODE=false for the demo / judges.
    dev_mode: bool = True

    # Storage
    database_url: str = "sqlite:///data/deepdive.db"
    upload_dir: str = "data/uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
