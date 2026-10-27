from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from holdline.config import ROOT
from holdline.contracts import (
    Finding,
    PolicyRules,
    Review,
    ShipmentRecord,
    digest,
    expected_verdict,
)
from holdline.decide import judge

_DATA = ROOT / "data"
_POLICIES = _DATA / "policies"


def shipments() -> dict:
    rows = json.loads((_DATA / "shipments.json").read_text(encoding="utf-8"))
    for shipment_id, row in rows.items():
        ShipmentRecord.model_validate({**row, "shipment_id": shipment_id})
    return rows


def known_shipment(shipment_id: str) -> bool:
    return shipment_id in shipments()


def shipment_record(shipment_id: str) -> dict:
    rows = shipments()
    if shipment_id not in rows:
        raise KeyError(shipment_id)
    return ShipmentRecord.model_validate(
        {**rows[shipment_id], "shipment_id": shipment_id}
    ).model_dump()


def corpus_rules() -> dict:
    """All five settings are mandatory; typos and duplicates stop the review."""
    values, sources = {}, []
    allowed = set(PolicyRules.model_fields)
    for path in sorted(_POLICIES.glob("*.md")):
        sources.append(f"data/policies/{path.name}")
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            if key not in allowed or key in values:
                raise ValueError(f"unknown or duplicate policy setting in {path.name}:{number}")
            if key == "window_days":
                if not value.isdecimal():
                    raise ValueError("window_days must be a non-negative integer")
                values[key] = int(value)
            elif key == "excluded_categories":
                values[key] = [item.strip() for item in value.split(",") if item.strip()]
            else:
                if value not in {"true", "false"}:
                    raise ValueError(f"{key} must be true or false")
                values[key] = value == "true"
    rules = PolicyRules.model_validate(values).model_dump()
    return {**rules, "sources": sources}


def _finding(role: str, record: dict, review_id: str | None = None) -> dict:
    shipment = ShipmentRecord.model_validate(record)
    raw = corpus_rules()
    rules = PolicyRules.model_validate({k: v for k, v in raw.items() if k != "sources"})
    if role == "policy":
        facts = (
            f"Age {shipment.age_days} days; hold window {rules.window_days} days. "
            f"Category {shipment.category}; excluded categories: {', '.join(rules.excluded_categories) or 'none'}."
        )
    else:
        facts = (
            f"Documents: {shipment.documents}. Damage recorded: {shipment.damage}. "
            f"Already received: {shipment.already_received}."
        )
    return Finding(
        role=role,
        shipment_id=shipment.shipment_id,
        review_id=review_id or str(uuid4()),
        verdict=expected_verdict(role, shipment, rules),
        sources=[shipment.source, *raw["sources"]],
        facts=facts,
        policy_snapshot=rules,
        shipment_snapshot=shipment,
        policy_hash=digest(rules.model_dump()),
        shipment_hash=digest(shipment.model_dump()),
    ).model_dump()


def policy_finding(record: dict, review_id: str | None = None) -> dict:
    return _finding("policy", record, review_id)


def shipment_finding(record: dict, review_id: str | None = None) -> dict:
    return _finding("shipment", record, review_id)


def skill() -> dict:
    text = (ROOT / "skills/hold-disposition/SKILL.md").read_text(encoding="utf-8")
    return {
        "name": "hold-disposition",
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "prompt": text,
    }


def fallback_explanation(disposition: str, findings: dict) -> str:
    facts = " ".join(f.get("facts", "Evidence unavailable.") for f in findings.values())
    return f"{disposition}: {facts} No stock was released; a person must review the hold line."


def rehearse(shipment_id: str, review_id: str | None = None) -> dict:
    review_id = review_id or str(uuid4())
    record = shipment_record(shipment_id)
    findings = {
        "policy": policy_finding(record, review_id),
        "shipment": shipment_finding(record, review_id),
    }
    disposition = judge(findings)
    return Review(
        review_id=review_id,
        shipment_id=shipment_id,
        disposition=disposition,
        findings=findings,
        mode="rehearsal",
        skill_hash=skill()["sha256"],
        explanation=fallback_explanation(disposition, findings),
    ).model_dump()
