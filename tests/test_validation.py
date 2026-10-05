from __future__ import annotations

import pandas as pd
import pytest

from src import validation
from src.validation import (
    CRITICAL,
    WARNING,
    CheckResult,
    ValidationError,
    count_date_before,
    count_duplicate_keys,
    count_invalid_foreign_keys,
    count_missing,
    count_not_in,
    count_unreferenced,
    status_for,
    validate,
)


def result_for(results: list[CheckResult], check: str, dataset: str) -> CheckResult:
    matches = [r for r in results if r.check == check and r.dataset == dataset]
    assert len(matches) == 1, f"Expected exactly one check '{check}' on {dataset}"
    return matches[0]


@pytest.mark.parametrize(
    ("count", "severity", "expected"),
    [(0, CRITICAL, "PASS"), (0, WARNING, "PASS"), (3, CRITICAL, "FAIL"), (3, WARNING, "WARNING")],
)
def test_status_for(count: int, severity: str, expected: str) -> None:
    assert status_for(count, severity) == expected


class TestCheckFunctions:
    def test_count_missing(self) -> None:
        df = pd.DataFrame({"a": [1, None, 3], "b": [None, None, 1]})
        assert count_missing(df, ["a"]) == 1
        assert count_missing(df, ["a", "b"]) == 2

    def test_count_duplicate_keys_counts_repeats_only(self) -> None:
        df = pd.DataFrame({"k1": ["a", "a", "a", "b"], "k2": [1, 1, 2, 1]})
        assert count_duplicate_keys(df, ["k1"]) == 2
        assert count_duplicate_keys(df, ["k1", "k2"]) == 1

    def test_count_invalid_foreign_keys_ignores_nulls(self) -> None:
        child = pd.DataFrame({"parent_id": ["p1", "p2", None, "p9"]})
        parent = pd.DataFrame({"id": ["p1", "p2"]})
        assert count_invalid_foreign_keys(child, "parent_id", parent, "id") == 1

    def test_count_unreferenced(self) -> None:
        parent = pd.DataFrame({"id": ["p1", "p2", "p3"]})
        child = pd.DataFrame({"parent_id": ["p1", "p1"]})
        assert count_unreferenced(parent, "id", child, "parent_id") == 2

    def test_count_not_in_ignores_nulls(self) -> None:
        df = pd.DataFrame({"state": ["SP", "XX", None]})
        assert count_not_in(df, "state", {"SP"}) == 1

    def test_count_date_before_ignores_nulls(self) -> None:
        df = pd.DataFrame({
            "start": pd.to_datetime(["2018-01-10", "2018-01-10", "2018-01-10"]),
            "end": pd.to_datetime(["2018-01-12", "2018-01-09", None]),
        })
        assert count_date_before(df, "end", "start") == 1


class TestValidate:
    def test_consistent_data_passes_every_check(self, valid_clean: dict[str, pd.DataFrame]) -> None:
        results = validate(valid_clean)
        assert len(results) == 44
        assert {r.status for r in results} == {"PASS"}

    def test_duplicate_primary_key_fails(self, valid_clean: dict[str, pd.DataFrame]) -> None:
        orders = valid_clean["orders"]
        valid_clean["orders"] = pd.concat([orders, orders.iloc[[0]]], ignore_index=True)
        result = result_for(validate(valid_clean), "Primary key (order_id) is unique", "orders")
        assert (result.status, result.record_count) == ("FAIL", 1)

    def test_orphan_foreign_key_fails(self, valid_clean: dict[str, pd.DataFrame]) -> None:
        valid_clean["order_items"].loc[0, "order_id"] = "missing_order"
        result = result_for(validate(valid_clean), "order_items.order_id exists in orders.order_id", "order_items")
        assert result.status == "FAIL"

    def test_missing_required_field_fails(self, valid_clean: dict[str, pd.DataFrame]) -> None:
        valid_clean["order_items"].loc[0, "price"] = float("nan")
        result = result_for(validate(valid_clean), "Required field price is not NULL", "order_items")
        assert result.status == "FAIL"

    def test_delivery_before_purchase_fails(self, valid_clean: dict[str, pd.DataFrame]) -> None:
        valid_clean["orders"].loc[0, "order_delivered_customer_date"] = pd.Timestamp("2017-12-31")
        result = result_for(validate(valid_clean), "Delivered to customer on/after purchase date", "orders")
        assert result.status == "FAIL"

    def test_unknown_state_is_only_a_warning(self, valid_clean: dict[str, pd.DataFrame]) -> None:
        valid_clean["customers"].loc[0, "customer_state"] = "XX"
        results = validate(valid_clean)
        assert result_for(results, "customer_state is a valid Brazilian state", "customers").status == "WARNING"
        assert not [r for r in results if r.status == "FAIL"]

    def test_order_without_items_is_a_warning(self, valid_clean: dict[str, pd.DataFrame]) -> None:
        valid_clean["order_items"] = valid_clean["order_items"].iloc[:1]
        results = validate(valid_clean)
        assert result_for(results, "Orders without order items (orphan orders)", "orders").record_count == 1
        assert not [r for r in results if r.status == "FAIL"]


class TestRunValidation:
    @pytest.fixture(autouse=True)
    def _isolate_outputs(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setattr(validation, "VALIDATION_REPORT_PATH", tmp_path / "validation_report.json")
        monkeypatch.setattr(validation, "PROCESSED_DATA_DIR", tmp_path)
        monkeypatch.setattr(validation, "write_report_section", lambda key, content: None)

    def test_critical_failure_stops_pipeline(
        self, monkeypatch: pytest.MonkeyPatch, valid_clean: dict[str, pd.DataFrame]
    ) -> None:
        valid_clean["payments"].loc[0, "payment_value"] = -1.0
        monkeypatch.setattr(validation, "load_clean_datasets", lambda: valid_clean)
        with pytest.raises(ValidationError, match="payment_value is not negative"):
            validation.run_validation()

    def test_warnings_do_not_stop_pipeline(
        self, monkeypatch: pytest.MonkeyPatch, valid_clean: dict[str, pd.DataFrame], tmp_path
    ) -> None:
        valid_clean["payments"].loc[0, "payment_type"] = "not_defined"
        monkeypatch.setattr(validation, "load_clean_datasets", lambda: valid_clean)
        results = validation.run_validation()
        assert sum(r.status == "WARNING" for r in results) == 1
        assert (tmp_path / "validation_report.json").is_file()
