from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE))

    # In multi-tenant mode, database_url is resolved per-request from the
    # tenant registry.  It is still required for single-tenant / local mode.
    database_url: Optional[str] = None

    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    llm_provider: str = "anthropic"
    claude_model: str = "claude-sonnet-4-6"
    groq_model: str = "llama-3.3-70b-versatile"
    max_query_rows: int = 100
    query_timeout_seconds: int = 30
    max_self_correction_retries: int = 3
    transport: str = "stdio"

    # Multi-tenant settings
    multi_tenant: bool = False
    engine_pool_max_size: int = 50
    engine_pool_idle_seconds: int = 3600


settings: Settings = Settings()
