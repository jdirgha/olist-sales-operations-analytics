"""Small hand-made datasets shaped like the raw Olist CSVs (all values text, blanks as NULL).

`valid_raw` is internally consistent and should pass every validation check.
The `messy_*` fixtures contain the specific problems each cleaning step must handle.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.cleaning import clean_all

NULL = None


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype=object)


@pytest.fixture
def translation() -> pd.DataFrame:
    return frame([
        {"product_category_name": "beleza_saude", "product_category_name_english": "health_beauty"},
        {"product_category_name": "informatica_acessorios", "product_category_name_english": "computers_accessories"},
    ])


def _product(product_id: str, category: str | None, weight: str = "500") -> dict:
    return {
        "product_id": product_id,
        "product_category_name": category,
        "product_name_lenght": "40",
        "product_description_lenght": "300",
        "product_photos_qty": "2",
        "product_weight_g": weight,
        "product_length_cm": "20",
        "product_height_cm": "10",
        "product_width_cm": "15",
    }


def _order(order_id: str, customer_id: str, status: str = "delivered", **dates: str | None) -> dict:
    row = {
        "order_id": order_id,
        "customer_id": customer_id,
        "order_status": status,
        "order_purchase_timestamp": "2018-01-10 10:00:00",
        "order_approved_at": "2018-01-10 11:00:00",
        "order_delivered_carrier_date": "2018-01-12 09:00:00",
        "order_delivered_customer_date": "2018-01-18 15:00:00",
        "order_estimated_delivery_date": "2018-01-25 00:00:00",
    }
    row.update(dates)
    return row


@pytest.fixture
def valid_raw(translation: pd.DataFrame) -> dict[str, pd.DataFrame]:
    customers = frame([
        {"customer_id": "c1", "customer_unique_id": "u1", "customer_zip_code_prefix": "01310",
         "customer_city": "sao paulo", "customer_state": "SP"},
        {"customer_id": "c2", "customer_unique_id": "u2", "customer_zip_code_prefix": "20040",
         "customer_city": "rio de janeiro", "customer_state": "RJ"},
    ])
    orders = frame([_order("o1", "c1"), _order("o2", "c2")])
    order_items = frame([
        {"order_id": "o1", "order_item_id": "1", "product_id": "p1", "seller_id": "s1",
         "shipping_limit_date": "2018-01-15 00:00:00", "price": "100.00", "freight_value": "15.50"},
        {"order_id": "o2", "order_item_id": "1", "product_id": "p2", "seller_id": "s2",
         "shipping_limit_date": "2018-01-15 00:00:00", "price": "50.00", "freight_value": "10.00"},
    ])
    payments = frame([
        {"order_id": "o1", "payment_sequential": "1", "payment_type": "credit_card",
         "payment_installments": "3", "payment_value": "115.50"},
        {"order_id": "o2", "payment_sequential": "1", "payment_type": "boleto",
         "payment_installments": "1", "payment_value": "60.00"},
    ])
    products = frame([_product("p1", "beleza_saude"), _product("p2", "informatica_acessorios")])
    return {
        "customers": customers,
        "orders": orders,
        "order_items": order_items,
        "payments": payments,
        "products": products,
        "category_translation": translation,
    }


@pytest.fixture
def valid_clean(valid_raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    cleaned, _ = clean_all(valid_raw)
    return cleaned


@pytest.fixture
def messy_customers() -> pd.DataFrame:
    return frame([
        {"customer_id": "c1", "customer_unique_id": "u1", "customer_zip_code_prefix": "1310",
         "customer_city": "  Sao   PAULO ", "customer_state": " sp"},
        # exact duplicate of the row above
        {"customer_id": "c1", "customer_unique_id": "u1", "customer_zip_code_prefix": "1310",
         "customer_city": "  Sao   PAULO ", "customer_state": " sp"},
        {"customer_id": NULL, "customer_unique_id": "u9", "customer_zip_code_prefix": "20040",
         "customer_city": "rio de janeiro", "customer_state": "RJ"},
        {"customer_id": "c2", "customer_unique_id": "u2", "customer_zip_code_prefix": "20040",
         "customer_city": "rio de janeiro", "customer_state": "RJ"},
    ])


@pytest.fixture
def messy_orders() -> pd.DataFrame:
    return frame([
        _order("o1", "c1", status=" DELIVERED "),
        # handed to carrier before it was purchased -> flagged, not removed
        _order("o2", "c2", order_delivered_carrier_date="2018-01-09 08:00:00"),
        # not delivered yet: missing timestamps must stay NULL
        _order("o3", "c3", status="shipped", order_delivered_customer_date=NULL),
        _order("o4", "c4", order_approved_at="not a date"),
    ])


@pytest.fixture
def messy_order_items() -> pd.DataFrame:
    base = {"product_id": "p1", "seller_id": "s1", "shipping_limit_date": "2018-01-15 00:00:00"}
    return frame([
        {**base, "order_id": "o1", "order_item_id": "1", "price": "100.00", "freight_value": "0"},
        {**base, "order_id": "o1", "order_item_id": "2", "price": "-5.00", "freight_value": "10.00"},
        {**base, "order_id": "o2", "order_item_id": "1", "price": "abc", "freight_value": "10.00"},
    ])


@pytest.fixture
def messy_payments() -> pd.DataFrame:
    return frame([
        {"order_id": "o1", "payment_sequential": "1", "payment_type": "Credit_Card",
         "payment_installments": "0", "payment_value": "50.00"},
        {"order_id": "o2", "payment_sequential": "1", "payment_type": "voucher",
         "payment_installments": "1", "payment_value": "0"},
        {"order_id": "o3", "payment_sequential": "1", "payment_type": "boleto",
         "payment_installments": "1", "payment_value": "-20.00"},
    ])


@pytest.fixture
def messy_products() -> pd.DataFrame:
    return frame([
        _product("p1", " Beleza_Saude "),
        _product("p2", "pc_gamer"),
        _product("p3", NULL),
        _product("p4", "categoria_nova"),
        _product("p5", "beleza_saude", weight="0"),
    ])
