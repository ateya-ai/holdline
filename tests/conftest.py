import os

# Tests must never inherit the author's .env or model credentials.
os.environ["HOLD_LINE_LOAD_DOTENV"] = "false"

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    for key in [
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOLD_LINE_TOKEN", "test-token")
    monkeypatch.setenv("HOLD_LINE_LEDGER", str(tmp_path / "ledger.sqlite"))
    monkeypatch.setenv("HOLD_LINE_ASYNC_ENABLED", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture
def ledger():
    from holdline.ledger import connect

    conn = connect()
    yield conn
    conn.close()
