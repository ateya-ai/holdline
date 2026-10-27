from __future__ import annotations

import hmac
import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if os.getenv("HOLD_LINE_LOAD_DOTENV", "true").lower() == "true":
    load_dotenv(ROOT / ".env", override=False)

review_context = ContextVar("review_id", default=None)

HOST = os.getenv("HOLD_LINE_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORTS = {
    "api": 8741,
    "receiving": 8742,
    "policy": 8743,
    "shipment": 8744,
    "disposition": 8745,
    "mcp": 8746,
}


def url(role: str) -> str:
    """Base URL for a role. HOLD_LINE_<ROLE>_URL overrides it when the roles run on separate hosts."""
    override = os.getenv(f"HOLD_LINE_{role.upper()}_URL", "").strip().rstrip("/")
    if override:
        return override
    return f"http://127.0.0.1:{PORTS[role]}"


def token() -> str:
    value = os.getenv("HOLD_LINE_TOKEN", "").strip()
    if not value:
        raise RuntimeError("HOLD_LINE_TOKEN is not set")
    return value


def authorization_ok(header: str | None) -> bool:
    if not header:
        return False
    try:
        expected = f"Bearer {token()}"
    except RuntimeError:
        return False
    try:
        return hmac.compare_digest(header, expected)
    except TypeError:
        return False


def database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    host = os.getenv("HOLD_LINE_DB_HOST", "").strip()
    if host:
        password = quote(os.environ["HOLD_LINE_DB_PASSWORD"], safe="")
        ssl = os.getenv("HOLD_LINE_DB_SSLMODE", "verify-full")
        cert = os.getenv("HOLD_LINE_DB_SSLROOTCERT", "/app/certs/rds-global-bundle.pem")
        return f"postgresql://holdline:{password}@{host}:5432/holdline?sslmode={ssl}&sslrootcert={quote(cert, safe='/')}"
    return ""


def using_postgres() -> bool:
    value = database_url()
    if value and not value.startswith(("postgresql://", "postgres://")):
        raise ValueError("DATABASE_URL must be a PostgreSQL URL or unset for SQLite")
    return bool(value)


def ledger_path() -> Path:
    configured = os.getenv("HOLD_LINE_LEDGER", str(ROOT / ".run" / "ledger.sqlite"))
    path = Path(configured)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "").strip()


def langsmith_api_key() -> str:
    return os.getenv("LANGSMITH_API_KEY", "").strip() or os.getenv("LANGCHAIN_API_KEY", "").strip()


def live_configured() -> bool:
    return bool(openai_api_key() and openai_model())


def async_enabled() -> bool:
    return os.getenv("HOLD_LINE_ASYNC_ENABLED", "false").lower() == "true"


def redis_url() -> str:
    if os.getenv("HOLD_LINE_REDIS_HOST"):
        password = quote(os.environ["HOLD_LINE_REDIS_PASSWORD"], safe="")
        return f"rediss://:{password}@{os.environ['HOLD_LINE_REDIS_HOST']}:6379/0?ssl_cert_reqs=required"
    return os.getenv("REDIS_URL", "redis://127.0.0.1:63791/0")


def celery_broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL", redis_url())


def configure_logging() -> None:
    logger = logging.getLogger("holdline")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, **fields: object) -> None:
    configure_logging()
    logging.getLogger("holdline").info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event,
                "review_id": review_context.get(),
                **fields,
            },
            default=str,
        )
    )
