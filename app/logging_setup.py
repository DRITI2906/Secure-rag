"""Logging/telemetry. PRIVACY-CRITICAL: query/response logs are a PII surface, so we only
log a hashed query id, latency, guard decisions, and result status — NEVER raw queries,
answers, retrieved chunk text, or secrets. Treat the logger like an audit channel that
strangers can read.

In Azure (APPLICATIONINSIGHTS_CONNECTION_STRING set), the OpenTelemetry exporter for
Application Insights is attached and the same `logger` ships records to App Insights.
Locally, records go to stderr at settings.log_level.
"""

from __future__ import annotations

import hashlib
import logging
import sys

from app.config import settings

logger = logging.getLogger("rag")


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    logger.propagate = False

    if settings.applicationinsights_connection_string:
        # Deferred import — the Azure Monitor SDK is only needed in cloud.
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            logger_name="rag",
        )


def hash_query(text: str) -> str:
    """Stable, non-reversible 8-hex-char id for a query. Safe to log; cannot recover
    the original text. Use for correlating a single request across log lines."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=4).hexdigest()
