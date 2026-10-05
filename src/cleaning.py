"""Clean the raw datasets and write analysis-ready files to data/processed/clean/.

Run: python -m src.cleaning

Principles:
- Raw files are never modified; cleaned copies are written separately.
- NULLs are never replaced with zero. Each column's missing-value treatment is
  declared in MISSING_VALUE_POLICY and rendered into the data quality report.
- Records with suspicious but plausible values are kept and flagged, not deleted,
  so revenue and order counts stay complete.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import pandas as pd

from src.config import CLEAN_DATA_DIR, PRIMARY_KEYS, PROCESSED_DATA_DIR, RAW_DATETIME_FORMAT, setup_logging
from src.ingestion import check_raw_files, load_raw_datasets
from src.reporting import REPORT_PATH, md_table, write_report_section

logger = setup_logging(__name__)

CLEAN_DATASETS = ["customers", "orders", "order_items", "payments", "products"]
CLEANING_SUMMARY_PATH = PROCESSED_DATA_DIR / "cleaning_summary.json"

# Source column names with spelling errors, mapped to corrected names.
COLUMN_RENAMES = {
    "product_name_lenght": "product_name_length",
    "product_description_lenght": "product_description_length",
}

# Categories present in products but missing from the official translation file.
MANUAL_CATEGORY_TRANSLATIONS = {
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "portable_kitchen_food_preparers",
}
UNKNOWN_CATEGORY = "unknown"

PRODUCT_INTEGER_COLUMNS = [
    "product_name_length",
    "product_description_length",
    "product_photos_qty",
    "product_weight_g",
    "product_length_cm",
    "product_height_cm",
    "product_width_cm",
]

ORDER_DATETIME_COLUMNS = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]

# Lifecycle rules: (later event, earlier event). A violation means the later event
# is recorded before the earlier one.
ORDER_DATE_SEQUENCE_RULES = [
    ("order_approved_at", "order_purchase_timestamp"),
    ("order_delivered_carrier_date", "order_purchase_timestamp"),
    ("order_delivered_customer_date", "order_purchase_timestamp"),
    ("order_delivered_customer_date", "order_delivered_carrier_date"),
]

MISSING_VALUE_POLICY = [
    ("all", "primary key columns", "Remove row", "A record without its key cannot be linked to other tables."),
    ("orders", "order_approved_at", "Keep NULL",
     "Order was never approved (mostly canceled/created). Imputing would invent a timestamp."),
    ("orders", "order_delivered_carrier_date", "Keep NULL", "Order was not handed to a carrier yet."),
    ("orders", "order_delivered_customer_date", "Keep NULL",
     "Order was not delivered yet. Delivery metrics use delivered orders only."),
    ("products", "product_category_name", "Keep NULL",
     f"Original value is unknown. `product_category_name_english` shows '{UNKNOWN_CATEGORY}' "
     "so these products' revenue still appears in category reports."),
    ("products", "product_name_length, product_description_length, product_photos_qty", "Keep NULL",
     "Descriptive listing attributes; not used in any KPI."),
    ("products", "product_weight_g, product_length_cm, product_height_cm, product_width_cm", "Keep NULL",
     "Not used in any KPI. Zero weights are also set to NULL because a 0 g product is not physically possible."),
    ("payments", "payment_installments", "Replace 0 with NULL",
     "Every payment has at least one installment, so 0 is an invalid value, not a real count."),
]


@dataclass
class CleaningLog:
    """Tracks what cleaning did to one dataset."""

    dataset: str
    rows_before: int
    rows_after: int = 0
    actions: list[tuple[str, int]] = field(default_factory=list)
    _modified_index: set = field(default_factory=set, repr=False)
    _final_index: set = field(default_factory=set, repr=False)

    def removed(self, action: str, count: int) -> None:
        self._add(action, count)

    def modified(self, action: str, index: Iterable) -> None:
        index = list(index)
        self._modified_index.update(index)
        self._add(action, len(index))

    def note(self, action: str, count: int) -> None:
        """Record an action that does not change values (e.g. a flag or rename)."""
        self._add(action, count)

    def finish(self, df: pd.DataFrame) -> None:
        self.rows_after = len(df)
        self._final_index = set(df.index)

    @property
    def rows_removed(self) -> int:
        return self.rows_before - self.rows_after

    @property
    def rows_modified(self) -> int:
        """Rows still present whose values were changed by cleaning."""
        return len(self._modified_index & self._final_index)

    def _add(self, action: str, count: int) -> None:
        self.actions.append((action, int(count)))
        logger.info("[%s] %s: %s", self.dataset, action, f"{count:,}")

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "rows_removed": self.rows_removed,
            "rows_modified": self.rows_modified,
            "actions": [{"action": a, "rows": n} for a, n in self.actions],
        }


# ---------------------------------------------------------------- reusable steps


def standardize_column_name(name: str) -> str:
    """Convert a column name to snake_case: 'Order ID', 'orderId', 'ORDER_ID' -> 'order_id'."""
    name = name.strip().lstrip("\ufeff")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    return name.strip("_").lower()


def standardize_columns(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    new_names = {c: standardize_column_name(c) for c in df.columns}
    new_names = {old: COLUMN_RENAMES.get(new, new) for old, new in new_names.items()}
    changed = sum(old != new for old, new in new_names.items())
    if changed:
        log.note("Columns renamed (snake_case / spelling fixes)", changed)
    return df.rename(columns=new_names)


def remove_exact_duplicates(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    duplicates = df.duplicated()
    log.removed("Exact duplicate rows removed", duplicates.sum())
    return df[~duplicates]


def remove_missing_keys(df: pd.DataFrame, key: list[str], log: CleaningLog) -> pd.DataFrame:
    missing = df[key].isna().any(axis=1)
    log.removed(f"Rows with missing primary key ({', '.join(key)}) removed", missing.sum())
    return df[~missing]


def standardize_text(df: pd.DataFrame, columns: list[str], log: CleaningLog, case: str = "lower") -> pd.DataFrame:
    """Trim, collapse internal whitespace and normalise case. NULLs stay NULL."""
    df = df.copy()
    for column in columns:
        original = df[column]
        cleaned = original.str.strip().str.replace(r"\s+", " ", regex=True)
        cleaned = cleaned.str.upper() if case == "upper" else cleaned.str.lower()
        changed = original.notna() & (original != cleaned)
        log.modified(f"{column}: whitespace/case standardised", df.index[changed])
        df[column] = cleaned
    return df


def convert_datetimes(df: pd.DataFrame, columns: list[str], log: CleaningLog) -> pd.DataFrame:
    df = df.copy()
    for column in columns:
        parsed = pd.to_datetime(df[column], format=RAW_DATETIME_FORMAT, errors="coerce")
        unparseable = df[column].notna() & parsed.isna()
        log.modified(f"{column}: unparseable dates set to NULL", df.index[unparseable])
        df[column] = parsed
    return df


def convert_numeric(df: pd.DataFrame, columns: list[str], log: CleaningLog, integer: bool = False) -> pd.DataFrame:
    df = df.copy()
    for column in columns:
        parsed = pd.to_numeric(df[column], errors="coerce")
        unparseable = df[column].notna() & parsed.isna()
        log.modified(f"{column}: non-numeric values set to NULL", df.index[unparseable])
        df[column] = parsed.round().astype("Int64") if integer else parsed.astype(float)
    return df


def remove_negative_values(df: pd.DataFrame, columns: list[str], log: CleaningLog) -> pd.DataFrame:
    """Drop rows where a monetary amount is negative - the amount cannot be trusted."""
    invalid = (df[columns] < 0).any(axis=1)
    log.removed(f"Rows with negative {' / '.join(columns)} removed", invalid.sum())
    return df[~invalid]


def null_non_positive(df: pd.DataFrame, columns: list[str], log: CleaningLog) -> pd.DataFrame:
    """Set values <= 0 to NULL where zero is not a physically valid measurement."""
    df = df.copy()
    for column in columns:
        invalid = (df[column] <= 0).fillna(False).astype(bool)
        log.modified(f"{column}: values <= 0 set to NULL", df.index[invalid])
        df.loc[invalid, column] = pd.NA
    return df


def flag_invalid_order_dates(orders: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Add has_invalid_dates: True if any lifecycle event is recorded before the event it must follow.

    Flagged orders keep their revenue but are excluded from delivery-time metrics.
    """
    orders = orders.copy()
    invalid = pd.Series(False, index=orders.index)
    for later, earlier in ORDER_DATE_SEQUENCE_RULES:
        violation = orders[later] < orders[earlier]
        log.note(f"Flag: {later} before {earlier}", violation.sum())
        invalid |= violation
    orders["has_invalid_dates"] = invalid
    log.note("Orders flagged has_invalid_dates (any rule)", invalid.sum())
    return orders


def _start(dataset: str, df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    log = CleaningLog(dataset=dataset, rows_before=len(df))
    df = standardize_columns(df, log)
    df = remove_exact_duplicates(df, log)
    df = remove_missing_keys(df, PRIMARY_KEYS[dataset], log)
    return df, log


# ---------------------------------------------------------------- dataset cleaners


def clean_customers(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    df, log = _start("customers", raw)
    df = standardize_text(df, ["customer_city"], log, case="lower")
    df = standardize_text(df, ["customer_state"], log, case="upper")

    zip_code = df["customer_zip_code_prefix"].str.strip()
    padded = zip_code.where(~zip_code.str.fullmatch(r"\d{1,4}", na=False), zip_code.str.zfill(5))
    log.modified("customer_zip_code_prefix: left-padded to 5 digits", df.index[padded != df["customer_zip_code_prefix"]])
    df["customer_zip_code_prefix"] = padded

    log.finish(df)
    return df, log


def clean_orders(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    df, log = _start("orders", raw)
    df = standardize_text(df, ["order_status"], log)
    df = convert_datetimes(df, ORDER_DATETIME_COLUMNS, log)
    df = flag_invalid_order_dates(df, log)
    log.finish(df)
    return df, log


def clean_order_items(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    df, log = _start("order_items", raw)
    df = convert_numeric(df, ["order_item_id"], log, integer=True)
    df = convert_numeric(df, ["price", "freight_value"], log)
    df = convert_datetimes(df, ["shipping_limit_date"], log)
    df = remove_negative_values(df, ["price", "freight_value"], log)
    log.note("Info: freight_value = 0 kept (free shipping is plausible)", (df["freight_value"] == 0).sum())
    log.note(
        "Info: shipping_limit_date after 2018 kept (seller SLA date, not used in KPIs)",
        (df["shipping_limit_date"].dt.year > 2018).sum(),
    )
    log.finish(df)
    return df, log


def clean_payments(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    df, log = _start("payments", raw)
    df = standardize_text(df, ["payment_type"], log)
    df = convert_numeric(df, ["payment_sequential", "payment_installments"], log, integer=True)
    df = convert_numeric(df, ["payment_value"], log)
    df = remove_negative_values(df, ["payment_value"], log)
    df = null_non_positive(df, ["payment_installments"], log)
    log.note("Info: payment_value = 0 kept (e.g. fully voucher-paid)", (df["payment_value"] == 0).sum())
    log.note("Info: payment_type = 'not_defined' kept", (df["payment_type"] == "not_defined").sum())
    log.finish(df)
    return df, log


def clean_products(raw: pd.DataFrame, translation: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    df, log = _start("products", raw)
    df = standardize_text(df, ["product_category_name"], log)
    df = convert_numeric(df, PRODUCT_INTEGER_COLUMNS, log, integer=True)
    df = null_non_positive(df, ["product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"], log)

    translation = translation.rename(columns=standardize_column_name)
    lookup = dict(
        zip(
            translation["product_category_name"].str.strip().str.lower(),
            translation["product_category_name_english"].str.strip().str.lower(),
        )
    )
    manual = {k: v for k, v in MANUAL_CATEGORY_TRANSLATIONS.items() if k not in lookup}
    lookup.update(manual)

    english = df["product_category_name"].map(lookup)
    uses_manual = df["product_category_name"].isin(manual.keys())
    log.note("product_category_name_english: manual translation used", uses_manual.sum())

    still_untranslated = df["product_category_name"].notna() & english.isna()
    log.note("product_category_name_english: no translation, Portuguese name kept", still_untranslated.sum())
    english = english.where(~still_untranslated, df["product_category_name"])

    missing_category = df["product_category_name"].isna()
    log.note(f"product_category_name_english: '{UNKNOWN_CATEGORY}' for missing category", missing_category.sum())
    df["product_category_name_english"] = english.fillna(UNKNOWN_CATEGORY)

    log.finish(df)
    return df, log


# ---------------------------------------------------------------- orchestration


def clean_all(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], list[CleaningLog]]:
    results = {
        "customers": clean_customers(raw["customers"]),
        "orders": clean_orders(raw["orders"]),
        "order_items": clean_order_items(raw["order_items"]),
        "payments": clean_payments(raw["payments"]),
        "products": clean_products(raw["products"], raw["category_translation"]),
    }
    cleaned = {name: df.reset_index(drop=True) for name, (df, _) in results.items()}
    logs = [log for _, log in results.values()]
    return cleaned, logs


def write_clean_datasets(cleaned: dict[str, pd.DataFrame]) -> None:
    CLEAN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in cleaned.items():
        path = CLEAN_DATA_DIR / f"{name}.csv"
        df.to_csv(path, index=False, date_format=RAW_DATETIME_FORMAT)
        logger.info("Wrote %s (%s rows)", path, f"{len(df):,}")


# Column types of the cleaned files; everything not listed is text.
CLEAN_COLUMN_TYPES: dict[str, dict[str, list[str]]] = {
    "orders": {"datetime": ORDER_DATETIME_COLUMNS, "boolean": ["has_invalid_dates"]},
    "order_items": {
        "datetime": ["shipping_limit_date"],
        "integer": ["order_item_id"],
        "decimal": ["price", "freight_value"],
    },
    "payments": {"integer": ["payment_sequential", "payment_installments"], "decimal": ["payment_value"]},
    "products": {"integer": PRODUCT_INTEGER_COLUMNS},
}


def read_clean_dataset(dataset: str) -> pd.DataFrame:
    """Read a cleaned CSV back with its proper column types."""
    path = CLEAN_DATA_DIR / f"{dataset}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Cleaned file not found: {path}. Run: python -m src.cleaning")

    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    types = CLEAN_COLUMN_TYPES.get(dataset, {})
    for column in types.get("datetime", []):
        df[column] = pd.to_datetime(df[column], format=RAW_DATETIME_FORMAT)
    for column in types.get("integer", []):
        df[column] = pd.to_numeric(df[column]).astype("Int64")
    for column in types.get("decimal", []):
        df[column] = pd.to_numeric(df[column]).astype(float)
    for column in types.get("boolean", []):
        df[column] = df[column].map({"True": True, "False": False}).astype(bool)
    return df


def load_clean_datasets(datasets: Iterable[str] = CLEAN_DATASETS) -> dict[str, pd.DataFrame]:
    return {dataset: read_clean_dataset(dataset) for dataset in datasets}


def render_cleaning_section(logs: list[CleaningLog], cleaned: dict[str, pd.DataFrame]) -> str:
    parts = [
        "## 2. Data Cleaning",
        "_Generated by `src/cleaning.py`._\n\n"
        "*Removed* = rows dropped. *Modified* = remaining rows with at least one value changed "
        "(type conversion alone does not count). Flags add a column without changing values.",
        "### 2.1 Cleaning summary",
        md_table(
            ["Dataset", "Rows Before", "Rows After", "Removed", "Modified"],
            [[log.dataset, log.rows_before, log.rows_after, log.rows_removed, log.rows_modified] for log in logs],
        ),
        "### 2.2 Cleaning actions",
        md_table(
            ["Dataset", "Action", "Rows affected"],
            [[log.dataset, action, count] for log in logs for action, count in log.actions],
        ),
        "### 2.3 Missing value decisions",
        "NULLs are never replaced with zero: a zero is a real measurement (e.g. free freight), "
        "while NULL means unknown or not applicable.",
    ]

    policy_rows = []
    for dataset, columns, decision, reason in MISSING_VALUE_POLICY:
        if dataset in cleaned:
            names = [c.strip() for c in columns.split(",")]
            remaining = ", ".join(f"{int(cleaned[dataset][c].isna().sum()):,}" for c in names)
        else:
            remaining = "0"
        policy_rows.append([dataset, columns, decision, reason, remaining])
    parts.append(md_table(["Dataset", "Column(s)", "Decision", "Reason", "NULLs after cleaning"], policy_rows))
    return "\n\n".join(parts)


def run_cleaning() -> list[CleaningLog]:
    check_raw_files()
    raw = load_raw_datasets()
    cleaned, logs = clean_all(raw)
    write_clean_datasets(cleaned)

    CLEANING_SUMMARY_PATH.write_text(json.dumps([log.to_dict() for log in logs], indent=2), encoding="utf-8")
    write_report_section("cleaning", render_cleaning_section(logs, cleaned))
    logger.info("Updated data quality report section 2: %s", REPORT_PATH)
    return logs


if __name__ == "__main__":
    run_cleaning()
