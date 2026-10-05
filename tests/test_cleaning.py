from __future__ import annotations

import pandas as pd
import pytest

from src.cleaning import (
    UNKNOWN_CATEGORY,
    CleaningLog,
    clean_customers,
    clean_order_items,
    clean_orders,
    clean_payments,
    clean_products,
    null_non_positive,
    standardize_column_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("order_id", "order_id"),
        ("Order ID", "order_id"),
        ("orderId", "order_id"),
        ("ORDER_ID", "order_id"),
        ("  customer-state ", "customer_state"),
        ("\ufeffproduct_category_name", "product_category_name"),
    ],
)
def test_standardize_column_name(raw: str, expected: str) -> None:
    assert standardize_column_name(raw) == expected


class TestCustomers:
    def test_removes_duplicates_and_missing_keys(self, messy_customers: pd.DataFrame) -> None:
        cleaned, log = clean_customers(messy_customers)
        assert list(cleaned["customer_id"]) == ["c1", "c2"]
        assert log.rows_before == 4
        assert log.rows_removed == 2

    def test_standardizes_text_and_zip_codes(self, messy_customers: pd.DataFrame) -> None:
        cleaned, log = clean_customers(messy_customers)
        first = cleaned.iloc[0]
        assert first["customer_city"] == "sao paulo"
        assert first["customer_state"] == "SP"
        assert first["customer_zip_code_prefix"] == "01310"
        assert log.rows_modified == 1

    def test_does_not_modify_raw_input(self, messy_customers: pd.DataFrame) -> None:
        original = messy_customers.copy()
        clean_customers(messy_customers)
        pd.testing.assert_frame_equal(messy_customers, original)


class TestOrders:
    def test_converts_dates_and_status(self, messy_orders: pd.DataFrame) -> None:
        cleaned, _ = clean_orders(messy_orders)
        assert pd.api.types.is_datetime64_any_dtype(cleaned["order_purchase_timestamp"])
        assert cleaned.loc[0, "order_status"] == "delivered"

    def test_flags_impossible_date_sequence_without_removing(self, messy_orders: pd.DataFrame) -> None:
        cleaned, log = clean_orders(messy_orders)
        assert len(cleaned) == len(messy_orders)
        assert log.rows_removed == 0
        flagged = cleaned.set_index("order_id")["has_invalid_dates"]
        assert flagged.to_dict() == {"o1": False, "o2": True, "o3": False, "o4": False}

    def test_missing_and_unparseable_dates_become_null(self, messy_orders: pd.DataFrame) -> None:
        cleaned, _ = clean_orders(messy_orders)
        by_id = cleaned.set_index("order_id")
        assert pd.isna(by_id.loc["o3", "order_delivered_customer_date"])
        assert pd.isna(by_id.loc["o4", "order_approved_at"])


class TestOrderItems:
    def test_removes_negative_prices_and_keeps_free_freight(self, messy_order_items: pd.DataFrame) -> None:
        cleaned, log = clean_order_items(messy_order_items)
        assert (cleaned["price"].dropna() >= 0).all()
        assert log.rows_removed == 1
        assert cleaned.loc[0, "freight_value"] == 0

    def test_non_numeric_price_becomes_null_not_zero(self, messy_order_items: pd.DataFrame) -> None:
        cleaned, _ = clean_order_items(messy_order_items)
        bad = cleaned[cleaned["order_id"] == "o2"].iloc[0]
        assert pd.isna(bad["price"])

    def test_numeric_types(self, messy_order_items: pd.DataFrame) -> None:
        cleaned, _ = clean_order_items(messy_order_items)
        assert str(cleaned["order_item_id"].dtype) == "Int64"
        assert cleaned["price"].dtype == float


class TestPayments:
    def test_zero_installments_become_null(self, messy_payments: pd.DataFrame) -> None:
        cleaned, _ = clean_payments(messy_payments)
        assert pd.isna(cleaned.set_index("order_id").loc["o1", "payment_installments"])

    def test_zero_payment_kept_negative_removed(self, messy_payments: pd.DataFrame) -> None:
        cleaned, log = clean_payments(messy_payments)
        assert set(cleaned["order_id"]) == {"o1", "o2"}
        assert log.rows_removed == 1
        assert cleaned.set_index("order_id").loc["o2", "payment_value"] == 0

    def test_payment_type_lowercased(self, messy_payments: pd.DataFrame) -> None:
        cleaned, _ = clean_payments(messy_payments)
        assert cleaned.loc[0, "payment_type"] == "credit_card"


class TestProducts:
    def test_fixes_misspelled_columns(self, messy_products: pd.DataFrame, translation: pd.DataFrame) -> None:
        cleaned, _ = clean_products(messy_products, translation)
        assert "product_name_length" in cleaned.columns
        assert "product_name_lenght" not in cleaned.columns

    def test_category_translation(self, messy_products: pd.DataFrame, translation: pd.DataFrame) -> None:
        cleaned, _ = clean_products(messy_products, translation)
        english = cleaned.set_index("product_id")["product_category_name_english"].to_dict()
        assert english == {
            "p1": "health_beauty",  # trimmed and lowercased before lookup
            "p2": "pc_gamer",  # manual translation
            "p3": UNKNOWN_CATEGORY,  # missing category
            "p4": "categoria_nova",  # untranslated: Portuguese name kept
            "p5": "health_beauty",
        }

    def test_missing_category_stays_null_in_source_column(
        self, messy_products: pd.DataFrame, translation: pd.DataFrame
    ) -> None:
        cleaned, _ = clean_products(messy_products, translation)
        assert pd.isna(cleaned.set_index("product_id").loc["p3", "product_category_name"])

    def test_zero_weight_becomes_null(self, messy_products: pd.DataFrame, translation: pd.DataFrame) -> None:
        cleaned, log = clean_products(messy_products, translation)
        assert pd.isna(cleaned.set_index("product_id").loc["p5", "product_weight_g"])
        assert log.rows_removed == 0


def test_null_non_positive_leaves_nulls_and_positives_alone() -> None:
    df = pd.DataFrame({"weight": pd.array([0, None, 5, -1], dtype="Int64")})
    log = CleaningLog(dataset="test", rows_before=len(df))
    result = null_non_positive(df, ["weight"], log)
    assert result["weight"].isna().tolist() == [True, True, False, True]
    assert result.loc[2, "weight"] == 5
    assert df["weight"].isna().sum() == 1  # input not modified
