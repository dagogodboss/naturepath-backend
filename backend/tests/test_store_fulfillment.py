"""Pickup collects no street address. Ship keeps tax on merchandise and adds staff shipping."""

import pytest
from pydantic import ValidationError

from application.store_fulfillment import merchandise_totals, shipping_amount
from presentation.api.store_routes import CreateStoreOrderIn


def _item():
    return {"product_id": "p1", "quantity": 1}


def _contact():
    return {
        "full_name": "Jane Moore",
        "phone": "3372561461",
        "email": "jane@example.com",
    }


def test_pickup_does_not_require_street_address():
    body = CreateStoreOrderIn(
        items=[_item()],
        address=_contact(),
        fulfillment_method="pickup",
    )
    assert body.fulfillment_method == "pickup"
    assert body.address.line1 == ""


def test_ship_requires_full_address():
    with pytest.raises(ValidationError):
        CreateStoreOrderIn(
            items=[_item()],
            address=_contact(),
            fulfillment_method="ship",
        )


def test_ship_accepts_full_address():
    body = CreateStoreOrderIn(
        items=[_item()],
        address={
            **_contact(),
            "line1": "117 Egret rd",
            "city": "Youngsville",
            "state": "La",
            "postal_code": "70592",
        },
        fulfillment_method="ship",
    )
    assert body.address.city == "Youngsville"


def test_pickup_shipping_is_zero_and_tax_ignores_shipping():
    assert shipping_amount("pickup", 12) == 0
    totals = merchandise_totals(39.98, 0.0925, shipping_amount("ship", 8))
    assert totals["tax"] == round(39.98 * 0.0925, 2)
    assert totals["shipping"] == 8
    assert totals["total"] == round(39.98 + totals["tax"] + 8, 2)


def test_ship_total_uses_staff_amount_not_free():
    totals = merchandise_totals(10, 0.0925, shipping_amount("ship", 4.5))
    assert totals["shipping"] == 4.5
    assert totals["total"] != totals["subtotal"] + totals["tax"]
