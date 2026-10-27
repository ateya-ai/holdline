from uuid import uuid4

import pytest

from holdline.backup import backup, restore
from holdline.contracts import ReviewConflict
from holdline.evidence import rehearse
from holdline.ledger import connect, get_review, post_disposition, reserve_job


def test_backup_restore_preserves_audit_record(tmp_path, monkeypatch):
    conn = connect()
    result = rehearse("HL-2204")
    post_disposition(conn, result)
    conn.close()
    snapshot = tmp_path / "backup.sqlite"
    backup(snapshot)
    with pytest.raises(FileExistsError):
        backup(snapshot)
    with pytest.raises(FileExistsError):
        restore(snapshot)
    monkeypatch.setenv("HOLD_LINE_LEDGER", str(tmp_path / "restored.sqlite"))
    restore(snapshot)
    conn = connect()
    try:
        assert get_review(conn, result["review_id"])["payload"] == result
    finally:
        conn.close()


def test_job_and_sync_request_share_identity(ledger):
    review_id = str(uuid4())
    reserve_job(ledger, review_id, {"shipment_id": "HL-2201", "mode": "rehearsal"})
    with pytest.raises(ReviewConflict):
        post_disposition(ledger, rehearse("HL-2202", review_id))
    post_disposition(ledger, rehearse("HL-2201", review_id))
    with pytest.raises(ReviewConflict):
        reserve_job(ledger, review_id, {"shipment_id": "HL-2202", "mode": "rehearsal"})
