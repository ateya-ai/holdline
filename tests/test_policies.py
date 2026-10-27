import pytest
from pydantic import ValidationError

from holdline import evidence
from holdline.contracts import Review, digest


@pytest.mark.parametrize(
    "settings",
    [
        "window_days: 14",
        "window_days: -1",
        "window_days: 14\nblock_if_damaged: treu",
        "window_days: 14\nwindow_days: 15",
        "window_days: 14\nblock_if_damged: true",
    ],
)
def test_bad_policy_fails_closed(tmp_path, monkeypatch, settings):
    (tmp_path / "policy.md").write_text(settings)
    monkeypatch.setattr(evidence, "_POLICIES", tmp_path)
    with pytest.raises((ValueError, ValidationError)):
        evidence.rehearse("HL-2204")


def test_missing_policy_directory_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "_POLICIES", tmp_path)
    with pytest.raises(ValidationError):
        evidence.corpus_rules()


@pytest.mark.parametrize("age,expected", [(0, "CLEAR"), (14, "CLEAR"), (15, "BLOCK")])
def test_window_boundary(age, expected):
    record = {**evidence.shipment_record("HL-2201"), "age_days": age}
    assert evidence.policy_finding(record)["verdict"] == expected


def test_snapshot_tampering_rejected():
    result = evidence.rehearse("HL-2201")
    result["findings"]["shipment"]["shipment_snapshot"]["damage"] = True
    with pytest.raises(ValidationError):
        Review.model_validate(result)


def test_forged_verdict_rejected_even_with_valid_hash():
    result = evidence.rehearse("HL-2204")
    result["findings"]["policy"]["verdict"] = "CLEAR"
    with pytest.raises(ValidationError):
        Review.model_validate(result)


def test_different_valid_policy_snapshots_rejected():
    result = evidence.rehearse("HL-2201")
    finding = result["findings"]["shipment"]
    finding["policy_snapshot"]["window_days"] = 15
    finding["policy_hash"] = digest(finding["policy_snapshot"])
    with pytest.raises(ValidationError):
        Review.model_validate(result)
