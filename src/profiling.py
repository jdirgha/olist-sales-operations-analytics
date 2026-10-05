"""Profile the raw datasets and write the initial-state data quality report.

Run: python -m src.profiling
Outputs:
  data/processed/raw_profile.json   machine-readable profile (used by the pipeline summary)
  docs/data_quality_report.md       human-readable report
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

import pandas as pd

from src.config import (
    PRIMARY_KEYS,
    PROCESSED_DATA_DIR,
    RAW_DATETIME_FORMAT,
    RAW_FILES,
    setup_logging,
)
from src.ingestion import check_raw_files, load_raw_datasets
from src.reporting import REPORT_PATH, frame_to_md, md_table, write_report_section

logger = setup_logging(__name__)

DATETIME_COLUMN_PATTERN = re.compile(r"(date|timestamp|_at)$")
# Numeric-looking codes that must stay text (leading zeros matter).
CODE_COLUMN_PATTERN = re.compile(r"zip_code_prefix$")

PROFILE_JSON_PATH = PROCESSED_DATA_DIR / "raw_profile.json"

ORDER_TIMESTAMP_COLUMNS = [
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
]


@dataclass
class ColumnProfile:
    name: str
    inferred_type: str
    non_null: int
    missing: int
    missing_pct: float
    unique: int
    unparseable: int = 0
    min_value: str | None = None
    max_value: str | None = None


@dataclass
class DatasetProfile:
    dataset: str
    file_name: str
    row_count: int
    column_count: int
    column_names: list[str]
    duplicate_rows: int
    primary_key: list[str]
    missing_key_rows: int
    duplicate_key_rows: int
    columns: list[ColumnProfile] = field(default_factory=list)


def _format_number(value: float) -> str:
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"


def profile_column(series: pd.Series) -> ColumnProfile:
    """Infer a column's type from its text values and compute summary statistics."""
    name = str(series.name)
    total = len(series)
    non_null_values = series.dropna()
    non_null = len(non_null_values)
    missing = total - non_null
    base = {
        "name": name,
        "non_null": non_null,
        "missing": missing,
        "missing_pct": round(100 * missing / total, 2) if total else 0.0,
        "unique": int(non_null_values.nunique()),
    }

    if DATETIME_COLUMN_PATTERN.search(name):
        parsed = pd.to_datetime(non_null_values, format=RAW_DATETIME_FORMAT, errors="coerce")
        valid = parsed.dropna()
        return ColumnProfile(
            **base,
            inferred_type="datetime",
            unparseable=non_null - len(valid),
            min_value=str(valid.min()) if len(valid) else None,
            max_value=str(valid.max()) if len(valid) else None,
        )

    if not CODE_COLUMN_PATTERN.search(name) and non_null:
        numeric = pd.to_numeric(non_null_values, errors="coerce")
        if numeric.notna().all():
            has_decimals = non_null_values.str.contains(".", regex=False).any()
            return ColumnProfile(
                **base,
                inferred_type="decimal" if has_decimals else "integer",
                min_value=_format_number(numeric.min()),
                max_value=_format_number(numeric.max()),
            )

    return ColumnProfile(**base, inferred_type="text")


def profile_dataset(dataset: str, df: pd.DataFrame) -> DatasetProfile:
    key = PRIMARY_KEYS[dataset]
    return DatasetProfile(
        dataset=dataset,
        file_name=RAW_FILES[dataset],
        row_count=len(df),
        column_count=df.shape[1],
        column_names=df.columns.tolist(),
        duplicate_rows=int(df.duplicated().sum()),
        primary_key=key,
        missing_key_rows=int(df[key].isna().any(axis=1).sum()),
        duplicate_key_rows=int(df.duplicated(subset=key).sum()),
        columns=[profile_column(df[column]) for column in df.columns],
    )


def order_status_distribution(orders: pd.DataFrame) -> pd.DataFrame:
    counts = orders["order_status"].value_counts(dropna=False)
    return pd.DataFrame(
        {
            "order_status": counts.index.astype(str),
            "orders": counts.values,
            "pct": (100 * counts.values / len(orders)).round(2),
        }
    )


def missing_order_timestamps_by_status(orders: pd.DataFrame) -> pd.DataFrame:
    """Missing lifecycle timestamps per order status - shows whether NULLs are expected."""
    summary = orders.groupby("order_status")[ORDER_TIMESTAMP_COLUMNS].agg(lambda s: int(s.isna().sum()))
    summary.insert(0, "orders", orders["order_status"].value_counts())
    return summary.sort_values("orders", ascending=False).reset_index()


def untranslated_categories(products: pd.DataFrame, translation: pd.DataFrame) -> pd.DataFrame:
    """Product categories that have no English translation."""
    known = set(translation["product_category_name"].dropna())
    categorised = products.dropna(subset=["product_category_name"])
    unmatched = categorised[~categorised["product_category_name"].isin(known)]
    counts = unmatched["product_category_name"].value_counts()
    return pd.DataFrame({"product_category_name": counts.index, "products": counts.values})


def raw_value_checks(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Count records with suspicious values or broken relationships in the raw data.

    These are observations only; cleaning.py and validation.py decide how each is handled.
    """
    orders, items, payments = raw["orders"], raw["order_items"], raw["payments"]
    products, customers = raw["products"], raw["customers"]

    def ts(column: str) -> pd.Series:
        return pd.to_datetime(orders[column], format=RAW_DATETIME_FORMAT, errors="coerce")

    purchase = ts("order_purchase_timestamp")
    price = pd.to_numeric(items["price"])
    freight = pd.to_numeric(items["freight_value"])
    payment_value = pd.to_numeric(payments["payment_value"])
    shipping_limit = pd.to_datetime(items["shipping_limit_date"], format=RAW_DATETIME_FORMAT)
    order_ids = set(orders["order_id"])

    checks = [
        ("order_items", "price <= 0", int((price <= 0).sum())),
        ("order_items", "freight_value = 0", int((freight == 0).sum())),
        ("order_items", "freight_value < 0", int((freight < 0).sum())),
        ("order_items", "shipping_limit_date after latest purchase date", int((shipping_limit > purchase.max()).sum())),
        ("payments", "payment_value = 0", int((payment_value == 0).sum())),
        ("payments", "payment_installments = 0", int((pd.to_numeric(payments["payment_installments"]) == 0).sum())),
        ("payments", "payment_type = 'not_defined'", int((payments["payment_type"] == "not_defined").sum())),
        ("products", "product_weight_g = 0", int((pd.to_numeric(products["product_weight_g"]) == 0).sum())),
        ("orders", "approved before purchase", int((ts("order_approved_at") < purchase).sum())),
        ("orders", "handed to carrier before purchase", int((ts("order_delivered_carrier_date") < purchase).sum())),
        ("orders", "delivered to customer before purchase", int((ts("order_delivered_customer_date") < purchase).sum())),
        (
            "orders",
            "delivered to customer before handed to carrier",
            int((ts("order_delivered_customer_date") < ts("order_delivered_carrier_date")).sum()),
        ),
        ("orders", "orders with no order_items", len(order_ids - set(items["order_id"]))),
        ("orders", "orders with no payments", len(order_ids - set(payments["order_id"]))),
        ("order_items", "order_id not in orders", int((~items["order_id"].isin(order_ids)).sum())),
        ("order_items", "product_id not in products", int((~items["product_id"].isin(products["product_id"])).sum())),
        ("payments", "order_id not in orders", int((~payments["order_id"].isin(order_ids)).sum())),
        ("orders", "customer_id not in customers", int((~orders["customer_id"].isin(customers["customer_id"])).sum())),
        (
            "customers",
            "customer_unique_id linked to more than one customer_id",
            int((customers.groupby("customer_unique_id")["customer_id"].nunique() > 1).sum()),
        ),
    ]
    return pd.DataFrame(checks, columns=["dataset", "check", "records"])


# ---------------------------------------------------------------- report rendering


def render_report(profiles: list[DatasetProfile], raw: dict[str, pd.DataFrame]) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections: list[str] = [
        "## 1. Raw Data Profile (initial state)",
        f"_Generated by `src/profiling.py` on {generated_at}._\n\n"
        "Profile of the raw Olist CSV files exactly as downloaded, before any cleaning.\n\n"
        "Method:\n"
        "- Files are read as text, so no values are altered or coerced on load.\n"
        "- Only empty fields count as missing (strings such as `NA` are not treated as NULL).\n"
        "- Types are inferred from the text values: `datetime` columns are parsed with the "
        f"format `{RAW_DATETIME_FORMAT}`; columns whose every value is numeric are `integer`/`decimal`; "
        "zip code prefixes are kept as text because leading zeros are significant.\n"
        "- *Duplicate rows* are rows identical across every column. *Duplicate keys* are extra rows "
        "sharing the same primary key value.",
    ]

    sections.append("### 1.1 Dataset overview")
    sections.append(
        md_table(
            ["Dataset", "File", "Rows", "Columns", "Duplicate rows", "Primary key", "Missing keys", "Duplicate keys"],
            [
                [
                    p.dataset,
                    f"`{p.file_name}`",
                    p.row_count,
                    p.column_count,
                    p.duplicate_rows,
                    ", ".join(p.primary_key),
                    p.missing_key_rows,
                    p.duplicate_key_rows,
                ]
                for p in profiles
            ],
        )
    )

    sections.append("### 1.2 Date ranges")
    sections.append(
        md_table(
            ["Dataset", "Column", "Earliest", "Latest", "Missing", "Unparseable"],
            [
                [p.dataset, c.name, c.min_value, c.max_value, c.missing, c.unparseable]
                for p in profiles
                for c in p.columns
                if c.inferred_type == "datetime"
            ],
        )
    )

    sections.append("### 1.3 Columns with missing values")
    missing_rows = [
        [p.dataset, c.name, c.missing, f"{c.missing_pct:.2f}%"] for p in profiles for c in p.columns if c.missing
    ]
    sections.append(
        md_table(["Dataset", "Column", "Missing", "Missing %"], missing_rows)
        if missing_rows
        else "No missing values found."
    )

    sections.append("### 1.4 Column profiles")
    for p in profiles:
        sections.append(f"#### {p.dataset} (`{p.file_name}`)")
        sections.append(
            md_table(
                ["Column", "Inferred type", "Non-null", "Missing", "Missing %", "Unique", "Min", "Max"],
                [
                    [
                        f"`{c.name}`",
                        c.inferred_type,
                        c.non_null,
                        c.missing,
                        f"{c.missing_pct:.2f}%",
                        c.unique,
                        c.min_value,
                        c.max_value,
                    ]
                    for c in p.columns
                ],
            )
        )

    sections.append("### 1.5 Targeted observations")
    sections.append("#### Order status distribution")
    sections.append(frame_to_md(order_status_distribution(raw["orders"])))
    sections.append(
        "#### Missing order timestamps by status\n\n"
        "Number of orders missing each lifecycle timestamp, by order status. "
        "This shows which missing values are expected (e.g. an undelivered order has no delivery date)."
    )
    sections.append(frame_to_md(missing_order_timestamps_by_status(raw["orders"])))
    sections.append("#### Product categories without an English translation")
    untranslated = untranslated_categories(raw["products"], raw["category_translation"])
    sections.append(frame_to_md(untranslated) if len(untranslated) else "All categories have a translation.")

    sections.append(
        "#### Value and relationship checks\n\n"
        "Counts of suspicious values and broken links between tables in the raw data. "
        "How each is handled is decided and documented in the cleaning and validation steps."
    )
    sections.append(frame_to_md(raw_value_checks(raw)))

    return "\n\n".join(sections) + "\n"


def run_profiling() -> list[DatasetProfile]:
    """Profile all raw datasets and write the JSON profile and markdown report."""
    check_raw_files()
    raw = load_raw_datasets()
    profiles = [profile_dataset(name, df) for name, df in raw.items()]

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_JSON_PATH.write_text(json.dumps([asdict(p) for p in profiles], indent=2), encoding="utf-8")
    logger.info("Wrote profile JSON: %s", PROFILE_JSON_PATH)

    write_report_section("raw-profile", render_report(profiles, raw))
    logger.info("Updated data quality report section 1: %s", REPORT_PATH)

    for p in profiles:
        logger.info(
            "%s: %s rows, %s duplicate rows, %s duplicate keys",
            p.dataset,
            f"{p.row_count:,}",
            p.duplicate_rows,
            p.duplicate_key_rows,
        )
    return profiles


if __name__ == "__main__":
    run_profiling()
