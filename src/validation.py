"""Automated data validation of the cleaned datasets.

Run: python -m src.validation

Every check counts the records that violate a rule:
- count == 0                  -> PASS
- count > 0, severity warning -> WARNING (known, documented issue; pipeline continues)
- count > 0, severity critical-> FAIL    (data would corrupt the database or the KPIs; pipeline stops)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass

import pandas as pd

from src.cleaning import load_clean_datasets
from src.config import PRIMARY_KEYS, PROCESSED_DATA_DIR, setup_logging
from src.reporting import REPORT_PATH, md_table, write_report_section

logger = setup_logging(__name__)

VALIDATION_REPORT_PATH = PROCESSED_DATA_DIR / "validation_report.json"

CRITICAL = "critical"
WARNING = "warning"

BRAZILIAN_STATES = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}  # fmt: skip
ORDER_STATUSES = {"created", "approved", "invoiced", "processing", "shipped", "delivered", "canceled", "unavailable"}
PAYMENT_TYPES = {"credit_card", "boleto", "voucher", "debit_card"}

REQUIRED_FIELDS = {
    "customers": ["customer_unique_id", "customer_state"],
    "orders": ["customer_id", "order_status", "order_purchase_timestamp", "order_estimated_delivery_date"],
    "order_items": ["product_id", "seller_id", "price", "freight_value"],
    "payments": ["payment_type", "payment_value"],
    "products": [],
}

# (child dataset, child column, parent dataset, parent column)
FOREIGN_KEYS = [
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("payments", "order_id", "orders", "order_id"),
]


class ValidationError(Exception):
    """Raised when at least one critical validation check fails."""


@dataclass
class CheckResult:
    check: str
    dataset: str
    severity: str
    record_count: int
    status: str


# ---------------------------------------------------------------- reusable check functions


def count_missing(df: pd.DataFrame, columns: list[str]) -> int:
    """Rows where any of the columns is NULL."""
    return int(df[columns].isna().any(axis=1).sum())


def count_duplicate_keys(df: pd.DataFrame, key: list[str]) -> int:
    """Rows whose key value already appeared in an earlier row."""
    return int(df.duplicated(subset=key).sum())


def count_invalid_foreign_keys(child: pd.DataFrame, child_col: str, parent: pd.DataFrame, parent_col: str) -> int:
    """Non-NULL child values with no matching parent row."""
    values = child[child_col].dropna()
    return int((~values.isin(parent[parent_col])).sum())


def count_unreferenced(parent: pd.DataFrame, parent_col: str, child: pd.DataFrame, child_col: str) -> int:
    """Parent rows that no child row refers to (e.g. orders without items)."""
    return int((~parent[parent_col].isin(child[child_col])).sum())


def count_negative(df: pd.DataFrame, column: str) -> int:
    return int((df[column] < 0).sum())


def count_equal(df: pd.DataFrame, column: str, value: object) -> int:
    return int((df[column] == value).sum())


def count_not_in(df: pd.DataFrame, column: str, allowed: set[str]) -> int:
    values = df[column].dropna()
    return int((~values.isin(allowed)).sum())


def count_date_before(df: pd.DataFrame, later: str, earlier: str) -> int:
    """Rows where `later` is recorded before `earlier` (NULLs are ignored)."""
    return int((df[later] < df[earlier]).sum())


def status_for(record_count: int, severity: str) -> str:
    if record_count == 0:
        return "PASS"
    return "FAIL" if severity == CRITICAL else "WARNING"


# ---------------------------------------------------------------- check registry


def build_checks(data: dict[str, pd.DataFrame]) -> list[tuple[str, str, str, Callable[[], int]]]:
    """Return (check name, dataset, severity, function) for every validation rule."""
    customers, orders = data["customers"], data["orders"]
    items, payments, products = data["order_items"], data["payments"], data["products"]
    checks: list[tuple[str, str, str, Callable[[], int]]] = []

    for dataset, key in PRIMARY_KEYS.items():
        if dataset not in data:
            continue
        df, key_name = data[dataset], ", ".join(key)
        checks.append((f"Primary key ({key_name}) is not NULL", dataset, CRITICAL, lambda df=df, k=key: count_missing(df, k)))
        checks.append((f"Primary key ({key_name}) is unique", dataset, CRITICAL,
                       lambda df=df, k=key: count_duplicate_keys(df, k)))

    for dataset, columns in REQUIRED_FIELDS.items():
        for column in columns:
            df = data[dataset]
            checks.append((f"Required field {column} is not NULL", dataset, CRITICAL,
                           lambda df=df, c=column: count_missing(df, [c])))

    for child, child_col, parent, parent_col in FOREIGN_KEYS:
        checks.append((
            f"{child}.{child_col} exists in {parent}.{parent_col}", child, CRITICAL,
            lambda c=data[child], cc=child_col, p=data[parent], pc=parent_col: count_invalid_foreign_keys(c, cc, p, pc),
        ))

    checks += [
        ("price is not negative", "order_items", CRITICAL, lambda: count_negative(items, "price")),
        ("freight_value is not negative", "order_items", CRITICAL, lambda: count_negative(items, "freight_value")),
        ("payment_value is not negative", "payments", CRITICAL, lambda: count_negative(payments, "payment_value")),
        ("Delivered to customer on/after purchase date", "orders", CRITICAL,
         lambda: count_date_before(orders, "order_delivered_customer_date", "order_purchase_timestamp")),
        ("Estimated delivery on/after purchase date", "orders", CRITICAL,
         lambda: count_date_before(orders, "order_estimated_delivery_date", "order_purchase_timestamp")),
        # Warnings: real, documented issues that analysis handles explicitly.
        ("Orders with inconsistent lifecycle dates (flagged has_invalid_dates)", "orders", WARNING,
         lambda: int(orders["has_invalid_dates"].sum())),
        ("Delivered orders missing delivery date", "orders", WARNING,
         lambda: int(((orders["order_status"] == "delivered") & orders["order_delivered_customer_date"].isna()).sum())),
        ("Orders without order items (orphan orders)", "orders", WARNING,
         lambda: count_unreferenced(orders, "order_id", items, "order_id")),
        ("Orders without payments", "orders", WARNING, lambda: count_unreferenced(orders, "order_id", payments, "order_id")),
        ("Customers without orders (orphan customers)", "customers", WARNING,
         lambda: count_unreferenced(customers, "customer_id", orders, "customer_id")),
        ("Products never ordered (orphan products)", "products", WARNING,
         lambda: count_unreferenced(products, "product_id", items, "product_id")),
        ("order_status is a known status", "orders", WARNING, lambda: count_not_in(orders, "order_status", ORDER_STATUSES)),
        ("customer_state is a valid Brazilian state", "customers", WARNING,
         lambda: count_not_in(customers, "customer_state", BRAZILIAN_STATES)),
        ("customer_zip_code_prefix has 5 digits", "customers", WARNING,
         lambda: int((~customers["customer_zip_code_prefix"].str.fullmatch(r"\d{5}", na=False)).sum())),
        ("payment_type is a known type", "payments", WARNING, lambda: count_not_in(payments, "payment_type", PAYMENT_TYPES)),
        ("price is greater than zero", "order_items", WARNING, lambda: count_equal(items, "price", 0)),
        ("payment_value is greater than zero", "payments", WARNING, lambda: count_equal(payments, "payment_value", 0)),
        ("Product has a category", "products", WARNING, lambda: count_missing(products, ["product_category_name"])),
    ]
    return checks


def validate(data: dict[str, pd.DataFrame]) -> list[CheckResult]:
    results = []
    for name, dataset, severity, check in build_checks(data):
        count = check()
        result = CheckResult(name, dataset, severity, count, status_for(count, severity))
        level = {"PASS": logging.INFO, "WARNING": logging.WARNING, "FAIL": logging.ERROR}[result.status]
        logger.log(level, "%-7s %s | %s | %s", result.status, dataset, name, f"{count:,}")
        results.append(result)
    return results


def render_validation_section(results: list[CheckResult]) -> str:
    counts = {status: sum(r.status == status for r in results) for status in ("PASS", "WARNING", "FAIL")}
    overall = "FAILED - pipeline stopped" if counts["FAIL"] else "PASSED"
    return "\n\n".join([
        "## 3. Data Validation",
        "_Generated by `src/validation.py` on the cleaned data._\n\n"
        "PASS = no violating records. WARNING = known issue, documented and handled in analysis; the pipeline "
        "continues. FAIL = critical rule broken; the pipeline stops before loading the database.",
        f"**Overall result: {overall}** - {counts['PASS']} passed, {counts['WARNING']} warnings, "
        f"{counts['FAIL']} failed ({len(results)} checks).",
        md_table(
            ["Check", "Dataset", "Status", "Record Count", "Severity"],
            [[r.check, r.dataset, r.status, r.record_count, r.severity] for r in results],
        ),
    ])


def run_validation(raise_on_failure: bool = True) -> list[CheckResult]:
    """Validate the cleaned data, write the reports and stop if any critical check fails."""
    results = validate(load_clean_datasets())

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_REPORT_PATH.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    write_report_section("validation", render_validation_section(results))
    logger.info("Updated data quality report section 3: %s", REPORT_PATH)

    failures = [r for r in results if r.status == "FAIL"]
    if failures:
        summary = "; ".join(f"{r.dataset}: {r.check} ({r.record_count:,})" for r in failures)
        logger.error("%s critical validation check(s) failed: %s", len(failures), summary)
        if raise_on_failure:
            raise ValidationError(f"{len(failures)} critical validation check(s) failed: {summary}")
    else:
        logger.info("Validation passed: no critical failures (%s warnings)", sum(r.status == "WARNING" for r in results))
    return results


if __name__ == "__main__":
    try:
        run_validation()
    except ValidationError:
        raise SystemExit(1)
