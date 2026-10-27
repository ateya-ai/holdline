"""Validated messages between independently running services."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

Mode = Literal["rehearsal", "live"]
Disposition = Literal["READY_FOR_REVIEW", "BLOCKED", "INCOMPLETE"]


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyRules(Contract):
    window_days: StrictInt = Field(ge=0, le=3650)
    excluded_categories: list[str]
    block_if_documents_incomplete: StrictBool
    block_if_damaged: StrictBool
    block_if_already_received: StrictBool


class ShipmentRecord(Contract):
    shipment_id: str = Field(min_length=1, max_length=40)
    age_days: StrictInt = Field(ge=0, le=36500)
    category: str = Field(min_length=1)
    documents: Literal["complete", "missing", "incomplete"]
    damage: StrictBool
    already_received: StrictBool
    summary: str
    source: Literal["data/shipments.json"] = "data/shipments.json"


def expected_verdict(role: str, record: ShipmentRecord, rules: PolicyRules) -> str:
    if role == "policy":
        blocked = (
            record.age_days > rules.window_days or record.category in rules.excluded_categories
        )
    else:
        blocked = (
            (rules.block_if_already_received and record.already_received)
            or (rules.block_if_documents_incomplete and record.documents != "complete")
            or (rules.block_if_damaged and record.damage)
        )
    return "BLOCK" if blocked else "CLEAR"


class Finding(Contract):
    role: Literal["policy", "shipment"]
    shipment_id: str
    review_id: str
    verdict: Literal["CLEAR", "BLOCK", "ERROR"]
    sources: list[str] = Field(default_factory=list)
    facts: str = ""
    error: str | None = None
    policy_snapshot: PolicyRules | None = None
    shipment_snapshot: ShipmentRecord | None = None
    policy_hash: str | None = None
    shipment_hash: str | None = None

    @model_validator(mode="after")
    def evidence_agrees(self):
        UUID(self.review_id)
        if self.verdict == "ERROR":
            if not self.error:
                raise ValueError("error finding requires an error code")
            return self
        if (
            not self.policy_snapshot
            or not self.shipment_snapshot
            or not self.sources
            or not self.facts
        ):
            raise ValueError("completed finding requires evidence")
        if self.shipment_snapshot.shipment_id != self.shipment_id:
            raise ValueError("shipment snapshot identity mismatch")
        if self.policy_hash != digest(self.policy_snapshot.model_dump()):
            raise ValueError("policy digest mismatch")
        if self.shipment_hash != digest(self.shipment_snapshot.model_dump()):
            raise ValueError("shipment digest mismatch")
        if self.verdict != expected_verdict(
            self.role, self.shipment_snapshot, self.policy_snapshot
        ):
            raise ValueError("verdict conflicts with evidence")
        return self


class Review(Contract):
    review_id: str
    shipment_id: str = Field(min_length=1, max_length=40)
    disposition: Disposition
    release_executed: Literal[False] = False
    findings: dict[str, Finding]
    mode: Mode
    role: Literal["disposition"] = "disposition"
    explanation: str = Field(min_length=1, max_length=4000)
    explanation_source: Literal["rehearsal", "model", "fallback"] = "rehearsal"
    skill: Literal["hold-disposition"] = "hold-disposition"
    skill_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def findings_agree(self):
        from holdline.decide import judge

        UUID(self.review_id)
        if set(self.findings) != {"policy", "shipment"}:
            raise ValueError("exactly policy and shipment findings are required")
        for role, finding in self.findings.items():
            if (finding.role, finding.shipment_id, finding.review_id) != (
                role,
                self.shipment_id,
                self.review_id,
            ):
                raise ValueError("finding identity mismatch")
        completed = [f for f in self.findings.values() if f.verdict != "ERROR"]
        if len(completed) == 2 and (
            completed[0].policy_hash != completed[1].policy_hash
            or completed[0].shipment_hash != completed[1].shipment_hash
        ):
            raise ValueError("specialists reviewed different evidence snapshots")
        if self.disposition != judge({k: v.model_dump() for k, v in self.findings.items()}):
            raise ValueError("disposition conflicts with findings")
        return self


class CaseIn(Contract):
    shipment_id: str = Field(min_length=1, max_length=40)
    mode: Mode = "rehearsal"


def request_hash(shipment_id: str, mode: str) -> str:
    return digest({"shipment_id": shipment_id, "mode": mode})


class DependencyUnavailable(RuntimeError):
    """A retryable dependency failure with a safe public message."""


class ReviewConflict(RuntimeError):
    """An idempotency key was reused for a different request."""
