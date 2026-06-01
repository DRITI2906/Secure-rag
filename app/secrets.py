"""Secret retrieval. The Groq key is the one unavoidable secret (Groq supports only
API-key auth, not Managed Identity). In Azure it lives in Key Vault and is read at
runtime via Managed Identity (DefaultAzureCredential) — never in code, image, or env.
Locally, fall back to GROQ_API_KEY loaded from .env.

SECURITY NOTES
- DefaultAzureCredential resolves Managed Identity in Azure and your `az login` locally,
  so the same code works in both environments.
- Grant the app's identity only `Key Vault Secrets User` (read on this one secret),
  nothing broader.
- Cached in-memory after first fetch; do not log it.
"""

from __future__ import annotations

from app.config import settings

_cached_key: str | None = None


def get_groq_api_key() -> str:
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    if settings.key_vault_uri:
        # Deferred imports so local dev doesn't need the Azure SDKs installed.
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        client = SecretClient(
            vault_url=settings.key_vault_uri,
            credential=DefaultAzureCredential(),
        )
        secret = client.get_secret(settings.key_vault_secret_name)
        if not secret.value:
            raise RuntimeError(
                f"Key Vault secret '{settings.key_vault_secret_name}' is empty"
            )
        _cached_key = secret.value
        return _cached_key

    if settings.groq_api_key:
        _cached_key = settings.groq_api_key
        return _cached_key

    raise RuntimeError(
        "No Groq API key available: set KEY_VAULT_URI (Azure, recommended) or "
        "GROQ_API_KEY in .env (local dev only)."
    )
