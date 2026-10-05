"""Central configuration: project paths, source files, database settings and logging."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Variables already set in the environment (e.g. by Docker) take precedence over .env.
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
CLEAN_DATA_DIR = PROCESSED_DATA_DIR / "clean"
TABLEAU_EXPORT_DIR = PROCESSED_DATA_DIR / "tableau"
SQL_DIR = PROJECT_ROOT / "sql"
DOCS_DIR = PROJECT_ROOT / "docs"
LOG_DIR = PROJECT_ROOT / "logs"

# Logical dataset name -> raw CSV file name in data/raw/.
RAW_FILES: dict[str, str] = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "products": "olist_products_dataset.csv",
    # Maps Portuguese category names to English for stakeholder-facing reports.
    "category_translation": "product_category_name_translation.csv",
}

# Columns that uniquely identify a row in each dataset.
PRIMARY_KEYS: dict[str, list[str]] = {
    "customers": ["customer_id"],
    "orders": ["order_id"],
    "order_items": ["order_id", "order_item_id"],
    "payments": ["order_id", "payment_sequential"],
    "products": ["product_id"],
    "category_translation": ["product_category_name"],
}

# Every timestamp in the Olist source files uses this format.
RAW_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def raw_file_path(dataset: str) -> Path:
    """Return the path of a raw CSV by its logical dataset name."""
    try:
        return RAW_DATA_DIR / RAW_FILES[dataset]
    except KeyError as exc:
        raise KeyError(f"Unknown dataset '{dataset}'. Expected one of: {sorted(RAW_FILES)}") from exc


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL connection settings, read from environment variables."""

    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)

    REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        missing = [name for name in cls.REQUIRED_VARS if not os.getenv(name)]
        if missing:
            raise EnvironmentError(
                f"Missing database environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in the values."
            )
        return cls(
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ["POSTGRES_PORT"]),
            database=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )

    @property
    def url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        )


def setup_logging(name: str) -> logging.Logger:
    """Return a logger that writes to the console and logs/pipeline.log.

    Handlers are attached to the root logger once, so repeated calls are safe. When a host
    application (e.g. Airflow) has already configured logging, its console handling is kept:
    adding a second stderr handler there would feed Airflow's redirected stderr back into itself.
    """
    root = logging.getLogger()
    if not getattr(root, "_pipeline_configured", False):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(LOG_FORMAT)

        if not root.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)
            root.setLevel(LOG_LEVEL)

        file_handler = logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(LOG_LEVEL)
        root.addHandler(file_handler)
        root._pipeline_configured = True  # type: ignore[attr-defined]

    return logging.getLogger(name)
