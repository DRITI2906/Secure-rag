"""Central config. Non-secret values from env; the Groq key comes from Key Vault
(see secrets.py) in Azure, or from .env locally. Never hard-code secrets here."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    groq_model: str = "llama-3.3-70b-versatile"
    groq_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"  # specialized injection classifier; returns p(injection)
    prompt_guard_threshold: float = 0.5  # p(injection) >= this => refuse; benign ~0.0004, clear injection ~0.9996
    groq_api_key: str = ""  # local dev only; in Azure leave blank and load from Key Vault

    # Embeddings (local)
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Retrieval
    top_k: int = 4
    min_relevance_score: float = 0.72  # tuned on arXiv corpus: on-topic 0.77+, off-topic 0.48-0.70

    # Guardrails / limits
    max_query_chars: int = 2000
    max_output_tokens: int = 512
    rate_limit_per_minute: int = 10

    # Auth (local fallback; prefer Easy Auth/Entra in Azure)
    api_key: str = ""

    # Azure
    key_vault_uri: str = ""
    key_vault_secret_name: str = "groq-api-key"
    blob_account_url: str = ""
    blob_container: str = "rag-index"
    applicationinsights_connection_string: str = ""

    # App
    corpus_description: str = "the provided document set"
    log_level: str = "INFO"


settings = Settings()
