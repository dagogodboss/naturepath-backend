from workers.reconciliation_worker import _payment_status_drifts


def test_payment_status_drift_when_revel_paid_but_local_pending():
    drifts = _payment_status_drifts("awaiting_payment", {"status": "paid"})
    assert drifts
    assert drifts[0]["drift_type"] == "payment_status_mismatch"


def test_payment_status_no_drift_when_revel_paid_and_local_captured():
    drifts = _payment_status_drifts("captured", {"status": "closed"})
    assert drifts == []


def test_payment_status_drift_when_revel_refunded_but_local_captured():
    drifts = _payment_status_drifts("captured", {"status": "refunded"})
    assert drifts
