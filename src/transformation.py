"""Run SQL analysis files against PostgreSQL and export each query's result.

An analysis file contains several queries, each preceded by a marker line:
    -- name: <query_name>

Run: python -m src.transformation sql/sales_analysis.sql [more files ...]
     python -m src.transformation --views     (re)create analytical and data-quality views
     python -m src.transformation --export    export dashboard views to data/processed/tableau/
Results are written to data/processed/analysis/<file stem>/<query_name>.csv
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from src.config import PROCESSED_DATA_DIR, SQL_DIR, TABLEAU_EXPORT_DIR, setup_logging
from src.database import DatabaseError, check_connection, get_engine, query

logger = setup_logging(__name__)

ANALYSIS_OUTPUT_DIR = PROCESSED_DATA_DIR / "analysis"
QUERY_NAME_PATTERN = re.compile(r"^--\s*name:\s*(\w+)\s*$", re.MULTILINE)

SALES_ANALYSIS_FILE = SQL_DIR / "sales_analysis.sql"
OPERATIONS_ANALYSIS_FILE = SQL_DIR / "operations_analysis.sql"
REGIONAL_ANALYSIS_FILE = SQL_DIR / "regional_analysis.sql"
DATA_QUALITY_FILE = SQL_DIR / "data_quality.sql"
ANALYTICAL_VIEWS_FILE = SQL_DIR / "analytical_views.sql"

# Order matters: data_quality.sql uses state_reference from analytical_views.sql.
VIEW_FILES = [ANALYTICAL_VIEWS_FILE, DATA_QUALITY_FILE]
DASHBOARD_VIEWS = ["sales_dashboard", "operations_dashboard", "regional_dashboard", "data_quality_summary"]


def parse_named_queries(sql: str) -> dict[str, str]:
    """Split SQL text into {query_name: statement} using '-- name:' markers."""
    markers = list(QUERY_NAME_PATTERN.finditer(sql))
    if not markers:
        raise ValueError("No '-- name: <query_name>' markers found")

    queries: dict[str, str] = {}
    for position, marker in enumerate(markers):
        end = markers[position + 1].start() if position + 1 < len(markers) else len(sql)
        statement = sql[marker.end():end].strip().rstrip(";").strip()
        name = marker.group(1)
        if name in queries:
            raise ValueError(f"Duplicate query name: {name}")
        if not statement:
            raise ValueError(f"Query '{name}' is empty")
        queries[name] = statement
    return queries


def run_analysis_file(path: Path, export: bool = True) -> dict[str, pd.DataFrame]:
    """Execute every named query in a file; optionally export results to CSV."""
    queries = parse_named_queries(path.read_text(encoding="utf-8"))
    output_dir = ANALYSIS_OUTPUT_DIR / path.stem
    if export:
        output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, pd.DataFrame] = {}
    for name, statement in queries.items():
        try:
            result = query(statement)
        except DatabaseError as exc:
            raise DatabaseError(f"{path.name} -> query '{name}' failed: {exc}") from exc
        results[name] = result
        if export:
            result.to_csv(output_dir / f"{name}.csv", index=False)
        logger.info("%s: %s -> %s rows", path.name, name, len(result))
    return results


def ddl_section(sql: str) -> str:
    """Return the part of a SQL file before its first '-- name:' query (view definitions)."""
    first_marker = QUERY_NAME_PATTERN.search(sql)
    return sql[: first_marker.start()] if first_marker else sql


def create_views() -> list[str]:
    """(Re)create the analytical and data-quality views, then confirm each returns rows."""
    for path in VIEW_FILES:
        section = ddl_section(path.read_text(encoding="utf-8"))
        try:
            with get_engine().begin() as conn:
                conn.exec_driver_sql(section)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Failed to create views from {path.name}: {getattr(exc, 'orig', exc)}") from exc
        logger.info("Created views from %s", path.name)

    for view in DASHBOARD_VIEWS:
        rows = query(f"SELECT COUNT(*) AS n FROM {view}")["n"].iloc[0]
        if rows == 0:
            raise DatabaseError(f"View {view} returned no rows")
        logger.info("View %s: %s rows", view, f"{rows:,}")
    return DASHBOARD_VIEWS


INTEGER_TYPES = {"smallint", "integer", "bigint"}


def export_dashboard_views() -> dict[str, int]:
    """Export each dashboard view to data/processed/tableau/<view>.csv for Tableau Public.

    Boolean columns are written as 1/0 so Tableau can SUM them directly; integer columns
    stay integers even when they contain NULLs. NULL is written as an empty field.
    """
    TABLEAU_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    exported: dict[str, int] = {}
    for view in DASHBOARD_VIEWS:
        column_types = query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :view ORDER BY ordinal_position",
            {"view": view},
        )
        df = query(f"SELECT {', '.join(column_types['column_name'])} FROM {view}")
        for column, data_type in column_types.itertuples(index=False):
            if data_type == "boolean":
                df[column] = df[column].map({True: 1, False: 0}).astype("Int64")
            elif data_type in INTEGER_TYPES:
                df[column] = df[column].astype("Int64")

        path = TABLEAU_EXPORT_DIR / f"{view}.csv"
        df.to_csv(path, index=False, encoding="utf-8")
        exported[view] = len(df)
        logger.info("Exported %s: %s rows -> %s", view, f"{len(df):,}", path)
    return exported


def run_sales_analysis() -> dict[str, pd.DataFrame]:
    return run_analysis_file(SALES_ANALYSIS_FILE)


def run_operations_analysis() -> dict[str, pd.DataFrame]:
    return run_analysis_file(OPERATIONS_ANALYSIS_FILE)


def run_regional_analysis() -> dict[str, pd.DataFrame]:
    return run_analysis_file(REGIONAL_ANALYSIS_FILE)


def _print_results(results: dict[str, pd.DataFrame], max_rows: int = 25) -> None:
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        for name, df in results.items():
            print(f"\n=== {name} ({len(df)} rows) ===")
            print(df.head(max_rows).to_string(index=False))


if __name__ == "__main__":
    args = sys.argv[1:]
    flags = {"--views", "--export"}
    files = [Path(arg) for arg in args if arg not in flags]
    try:
        check_connection()
        if "--views" in args:
            create_views()
        if "--export" in args:
            export_dashboard_views()
        if not files and not flags & set(args):
            files = [SALES_ANALYSIS_FILE]
        for sql_file in files:
            _print_results(run_analysis_file(sql_file))
    except (DatabaseError, ValueError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        raise SystemExit(1)
