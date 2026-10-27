import json

from holdline import model
from holdline.evidence import rehearse


async def test_rehearsal_never_constructs_model(monkeypatch):
    import langchain_openai

    def forbidden(**kwargs):
        raise AssertionError("rehearsal constructed a paid client")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", forbidden)
    assert await model.explain("instructions", "{}", "rehearsal", "safe fallback") == (
        "safe fallback",
        "rehearsal",
    )


def test_tracing_is_optional(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    assert model.live_ready()


async def test_model_receives_evidence_and_release_statement_is_program_owned(monkeypatch):
    import langchain_openai

    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    seen = []

    class Fake:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, messages):
            seen.append(json.loads(messages[-1].content))
            return model.Explanation(
                evidence_summary="Damage was recorded and the documents are missing."
            )

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", Fake)
    from holdline.executors import HoldlineExecutor

    result = rehearse("HL-2204")
    result = await HoldlineExecutor("disposition")._disposition(
        {
            "review_id": result["review_id"],
            "shipment_id": "HL-2204",
            "findings": result["findings"],
        },
        "live",
    )
    assert seen[0]["findings"]["shipment"]["shipment_snapshot"]["damage"] is True
    assert result["disposition"] == "BLOCKED"
    assert result["release_executed"] is False
    assert result["explanation_source"] == "model"
    assert "No stock was released" in result["explanation"]


async def test_model_outage_uses_labelled_fallback(monkeypatch):
    import langchain_openai

    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    def failing(**kwargs):
        raise RuntimeError("provider failure")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", failing)
    assert await model.explain("instructions", "{}", "live", "safe fallback") == (
        "safe fallback",
        "fallback",
    )


async def test_model_cannot_claim_release(monkeypatch):
    import langchain_openai

    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    class Fake:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, messages):
            return model.Explanation(evidence_summary="Stock is released.")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", Fake)
    assert await model.explain("instructions", "{}", "live", "safe fallback") == (
        "safe fallback",
        "fallback",
    )
