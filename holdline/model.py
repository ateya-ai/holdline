"""Optional model wording; decisions and release state remain program-owned."""

from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel, Field

from holdline.config import langsmith_api_key, live_configured, log_event, openai_model


def live_ready() -> bool:
    # Configuration only: this does not probe billing, credentials, or connectivity.
    return live_configured()


class Explanation(BaseModel):
    evidence_summary: str = Field(
        min_length=1,
        max_length=600,
        description="At most two sentences explaining only the supplied facts; do not describe stock release or change the disposition.",
    )


async def explain(instructions: str, user_input: str, mode: str, fallback: str) -> tuple[str, str]:
    if mode == "rehearsal":
        return fallback, "rehearsal"
    if mode != "live" or not live_ready():
        raise ValueError("live wording needs OPENAI_API_KEY and OPENAI_MODEL")
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        from langsmith import tracing_context

        tracing = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
        if tracing and not langsmith_api_key():
            raise ValueError("tracing enabled without a LangSmith key")
        llm = ChatOpenAI(model=openai_model(), max_completion_tokens=500, timeout=12, max_retries=0)
        async with asyncio.timeout(14):
            with tracing_context(enabled=tracing):
                result = await llm.with_structured_output(Explanation).ainvoke(
                    [
                        SystemMessage(content=instructions),
                        HumanMessage(content=user_input),
                    ]
                )
        text = result.evidence_summary.strip()
        # Release language always comes from the program, including on model failure.
        if any(word in text.lower() for word in ("release", "approved", "approval")):
            raise ValueError("model wording crossed the decision boundary")
        return text + " No stock was released; a person must review the hold line.", "model"
    except Exception as exc:
        log_event("explanation_fallback", error=type(exc).__name__)
        return fallback, "fallback"
