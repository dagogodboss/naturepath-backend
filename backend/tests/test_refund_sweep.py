"""Sanity checks for store refund reconciliation sweep helpers."""
import hashlib


def _idempotency_key(ref_type: str, ref_id: str, action: str, attempt_no: int = 1) -> str:
    raw = f"{ref_type}:{ref_id}:{action}:{attempt_no}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_card_dedupe_id_matches_store_route_convention():
    from infrastructure.payment.store_refund_sweep import _card_dedupe_id

    order_id = "np_ord_test"
    hdr = "idem-header-xyz"
    expected = "rref:" + _idempotency_key("store_order", order_id, f"refund:hdr:{hdr}")[:24]
    assert _card_dedupe_id(order_id, hdr) == expected
