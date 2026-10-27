"""Opt-in provider evaluation; never run as part of the free rehearsal checks."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true", required=True)
    parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    token = os.environ["HOLD_LINE_TOKEN"]
    model = os.environ["OPENAI_MODEL"]
    base = os.getenv("HOLD_LINE_API_URL", "http://127.0.0.1:8741")
    records = []
    with httpx.Client(timeout=65, trust_env=False) as client:
        for shipment in ["HL-2201", "HL-2202", "HL-2203", "HL-2204"]:
            response = client.post(
                base + "/cases",
                headers={
                    "Authorization": "Bearer " + token,
                    "Idempotency-Key": "evaluation-" + str(uuid4()),
                },
                json={"shipment_id": shipment, "mode": "live"},
            )
            response.raise_for_status()
            records.append(response.json())
    out = ROOT / ".run/evaluations"
    out.mkdir(parents=True, exist_ok=True)
    path = out / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(
        json.dumps(
            {
                "model": model,
                "reviews": records,
                "human_rubric_review": "required; see docs/evaluations.md",
            },
            indent=2,
        )
    )
    print("Evaluation saved:", path)


if __name__ == "__main__":
    main()
