from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE))

    database_url: str
    anthropic_api_key: str
    groq_api_key: str
    llm_provider: str
    claude_model: str
    groq_model: str
    max_query_rows: int
    query_timeout_seconds: int
    max_self_correction_retries: int
    transport: str = "stdio"


settings: Settings = Settings()