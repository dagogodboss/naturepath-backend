from core.config import Settings
from infrastructure.external.revel_live_client import _merchant_base, _normalize_product, _resources_base


def test_revel_bases_accept_short_or_full_subdomain():
    short = Settings(revel_subdomain="thenaturalpathla")
    full = Settings(revel_subdomain="thenaturalpathla.revelup.com")
    full_url = Settings(revel_subdomain="https://thenaturalpathla.revelup.com/resources/")

    assert _merchant_base(short) == "https://thenaturalpathla.revelup.com/"
    assert _resources_base(short) == "https://thenaturalpathla.revelup.com/resources/"
    assert _merchant_base(full) == "https://thenaturalpathla.revelup.com/"
    assert _resources_base(full) == "https://thenaturalpathla.revelup.com/resources/"
    assert _merchant_base(full_url) == "https://thenaturalpathla.revelup.com/"
    assert _resources_base(full_url) == "https://thenaturalpathla.revelup.com/resources/"


def test_normalize_weborders_product_payload():
    product = _normalize_product(
        {
            "id": 12820,
            "id_category": 624,
            "name": "Umcka Cold Relief Lemon Hot Drink",
            "price": 12.99,
            "stock_amount": -26.0,
            "image": None,
            "barcode": "033674151464",
            "description": "Lemon hot drink",
        }
    )

    assert product["product_id"] == "12820"
    assert product["name"] == "Umcka Cold Relief Lemon Hot Drink"
    assert product["price"] == 12.99
    assert product["category"] == "624"
    assert product["stock_qty"] == -26
    assert product["sku"] == "033674151464"
    assert product["is_active"] is True
