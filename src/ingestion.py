"""Raw data ingestion: check and read the source CSV files without modifying them.

Raw files are read as text so nothing is silently converted on the way in
(e.g. zip code prefixes keep their leading zeros). Type conversion is an explicit
step in cleaning.py.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from src.config import RAW_FILES, raw_file_path, setup_logging

logger = setup_logging(__name__)

EXPECTED_COLUMNS: dict[str, list[str]] = {
    "customers": [
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ],
    "orders": [
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": [
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ],
    "payments": [
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    ],
    "products": [
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "category_translation": ["product_category_name", "product_category_name_english"],
}

# utf-8-sig strips the byte-order mark present in product_category_name_translation.csv.
CSV_ENCODING = "utf-8-sig"


class RawDataError(Exception):
    """Raised when raw source files are missing or structurally invalid."""


def _resolve(datasets: Iterable[str] | None) -> list[str]:
    return list(datasets) if datasets is not None else list(RAW_FILES)


def check_raw_files(datasets: Iterable[str] | None = None) -> dict[str, int]:
    """Check that each raw file exists, is non-empty and contains the expected columns.

    Returns the file size in bytes per dataset. Raises RawDataError listing every problem found.
    """
    problems: list[str] = []
    sizes: dict[str, int] = {}

    for dataset in _resolve(datasets):
        path = raw_file_path(dataset)
        if not path.is_file():
            problems.append(f"{dataset}: file not found at {path}")
            continue
        size = path.stat().st_size
        if size == 0:
            problems.append(f"{dataset}: file is empty ({path.name})")
            continue

        header = pd.read_csv(path, nrows=0, encoding=CSV_ENCODING).columns.tolist()
        missing_columns = sorted(set(EXPECTED_COLUMNS[dataset]) - set(header))
        if missing_columns:
            problems.append(f"{dataset}: missing expected columns {missing_columns}")
            continue

        sizes[dataset] = size
        logger.info("Raw file OK: %s (%s bytes)", path.name, f"{size:,}")

    if problems:
        for problem in problems:
            logger.error("Raw data check failed - %s", problem)
        raise RawDataError("Raw data check failed:\n" + "\n".join(problems))
    return sizes


def read_raw_dataset(dataset: str) -> pd.DataFrame:
    """Read one raw CSV as text. Only empty fields are treated as missing."""
    path = raw_file_path(dataset)
    df = pd.read_csv(
        path,
        dtype=str,
        encoding=CSV_ENCODING,
        keep_default_na=False,
        na_values=[""],
    )
    logger.info("Read %s: %s rows x %s columns", path.name, f"{len(df):,}", df.shape[1])
    return df


def load_raw_datasets(datasets: Iterable[str] | None = None) -> dict[str, pd.DataFrame]:
    """Read several raw datasets, keyed by logical dataset name."""
    return {dataset: read_raw_dataset(dataset) for dataset in _resolve(datasets)}
