"""PostgreSQL access: connection, schema creation, loading and row-count checks.

Run: python -m src.database   (creates tables if needed and reloads the cleaned data)

Loading is a full refresh: all tables are truncated and re-filled with COPY inside
one transaction, so a failed load leaves the previous data untouched.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from src.cleaning import CLEAN_DATASETS, load_clean_datasets
from src.config import RAW_DATETIME_FORMAT, SQL_DIR, DatabaseSettings, setup_logging

logger = setup_logging(__name__)

SCHEMA_FILE = SQL_DIR / "schema.sql"

# Parents before children so foreign keys are satisfied during COPY.
LOAD_ORDER = ["customers", "products", "orders", "order_items", "payments"]


class DatabaseError(Exception):
    """Raised for connection, SQL execution or load failures."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create (once) a SQLAlchemy engine from environment variables."""
    settings = DatabaseSettings.from_env()
    return create_engine(settings.url, pool_pre_ping=True, future=True)


def check_connection() -> str:
    """Connect and return the server version, or raise DatabaseError with a clear message."""
    settings = DatabaseSettings.from_env()
    try:
        with get_engine().connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
    except SQLAlchemyError as exc:
        raise DatabaseError(
            f"Cannot connect to PostgreSQL at {settings.host}:{settings.port}/{settings.database} "
            f"as '{settings.user}'. Check the server is running and .env is correct. ({exc.__class__.__name__})"
        ) from exc
    logger.info("Connected to PostgreSQL %s at %s:%s/%s", version, settings.host, settings.port, settings.database)
    return version


def execute_sql_file(path: Path) -> None:
    """Execute every statement in a .sql file in one transaction."""
    sql = path.read_text(encoding="utf-8")
    try:
        with get_engine().begin() as conn:
            conn.exec_driver_sql(sql)
    except SQLAlchemyError as exc:
        raise DatabaseError(f"Failed to execute {path.name}: {exc.orig if hasattr(exc, 'orig') else exc}") from exc
    logger.info("Executed %s", path.name)


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a SELECT and return the result as a DataFrame."""
    try:
        with get_engine().connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params)
    except SQLAlchemyError as exc:
        raise DatabaseError(f"Query failed: {exc.orig if hasattr(exc, 'orig') else exc}") from exc


def create_tables() -> None:
    execute_sql_file(SCHEMA_FILE)


def get_table_columns(table: str) -> list[str]:
    result = query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :table ORDER BY ordinal_position",
        {"table": table},
    )
    return result["column_name"].tolist()


def _to_copy_buffer(df: pd.DataFrame) -> io.StringIO:
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, date_format=RAW_DATETIME_FORMAT)
    buffer.seek(0)
    return buffer


def load_datasets(data: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Replace the contents of every table with the given DataFrames, atomically."""
    missing = [table for table in LOAD_ORDER if table not in data]
    if missing:
        raise DatabaseError(f"Cannot load: missing datasets {missing}")

    for table in LOAD_ORDER:
        table_columns = get_table_columns(table)
        if set(table_columns) != set(data[table].columns):
            raise DatabaseError(
                f"Column mismatch for {table}: table has {sorted(set(table_columns) - set(data[table].columns))} "
                f"not in data; data has {sorted(set(data[table].columns) - set(table_columns))} not in table"
            )

    raw_conn = get_engine().raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(f"TRUNCATE {', '.join(LOAD_ORDER)} CASCADE")
            for table in LOAD_ORDER:
                df = data[table]
                columns = ", ".join(df.columns)
                cursor.copy_expert(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)", _to_copy_buffer(df))
                logger.info("Loaded %s: %s rows", table, f"{len(df):,}")
        raw_conn.commit()
    except Exception as exc:
        raw_conn.rollback()
        raise DatabaseError(f"Load failed and was rolled back: {exc}") from exc
    finally:
        raw_conn.close()
    return {table: len(data[table]) for table in LOAD_ORDER}


def get_row_counts(tables: list[str] = LOAD_ORDER) -> dict[str, int]:
    counts = {}
    with get_engine().connect() as conn:
        for table in tables:
            counts[table] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    return counts


def verify_row_counts(expected: dict[str, int]) -> dict[str, int]:
    """Compare database row counts with the loaded DataFrames; raise on any mismatch."""
    actual = get_row_counts(list(expected))
    mismatches = {t: (expected[t], actual[t]) for t in expected if expected[t] != actual[t]}
    if mismatches:
        raise DatabaseError(f"Row count mismatch (expected, actual): {mismatches}")
    for table, count in actual.items():
        logger.info("Row count OK: %s = %s", table, f"{count:,}")
    return actual


def run_load() -> dict[str, int]:
    """Create tables if needed, load the cleaned data and verify row counts."""
    check_connection()
    create_tables()
    data = load_clean_datasets(CLEAN_DATASETS)
    expected = load_datasets(data)
    return verify_row_counts(expected)


if __name__ == "__main__":
    try:
        run_load()
    except DatabaseError as exc:
        logger.error("%s", exc)
        raise SystemExit(1)
