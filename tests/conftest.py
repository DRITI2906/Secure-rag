"""Shared pytest config.

- Registers the `integration` marker (tests that hit Groq).
- Auto-skips integration tests when GROQ_API_KEY / KEY_VAULT_URI is unset, so a reviewer
  who clones the repo without credentials still gets a green unit-test run.
"""

from __future__ import annotations

import pytest

from app.config import settings


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: tests that hit Groq (Prompt Guard / LLM). Need GROQ_API_KEY in .env "
        "or KEY_VAULT_URI for Azure.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if settings.groq_api_key or settings.key_vault_uri:
        return
    skip = pytest.mark.skip(reason="needs GROQ_API_KEY (.env) or KEY_VAULT_URI (Azure)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
