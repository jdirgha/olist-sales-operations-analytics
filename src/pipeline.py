"""End-to-end pipeline steps, shared by the Airflow DAG and the command line.

Run: python -m src.pipeline              run every step in order
     python -m src.pipeline clean_data   run selected steps only
Each step returns a small JSON-serializable summary, which Airflow stores as the task's XCom.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from src import transformation
from src.cleaning import run_cleaning
from src.config import PROCESSED_DATA_DIR, setup_logging
from src.database import get_row_counts, query, run_load
from src.ingestion import check_raw_files
from src.profiling import run_profiling
from src.validation import VALIDATION_REPORT_PATH, run_validation

logger = setup_logging(__name__)

PIPELINE_SUMMARY_PATH = PROCESSED_DATA_DIR / "pipeline_summary.json"

# Headline metrics for the run summary: (SQL file, query name).
SUMMARY_QUERIES = [
    (transformation.SALES_ANALYSIS_FILE, "total_revenue"),
    (transformation.SALES_ANALYSIS_FILE, "total_orders"),
    (transformation.SALES_ANALYSIS_FILE, "average_order_value"),
    (transformation.OPERATIONS_ANALYSIS_FILE, "operations_kpis"),
]


def check_raw_data() -> dict[str, int]:
    """Fail fast if any raw CSV is missing, empty or unreadable. Returns file sizes in bytes."""
    return check_raw_files()


def profile_data() -> dict[str, int]:
    return {p.dataset: p.row_count for p in run_profiling()}


def clean_data() -> dict[str, dict[str, int]]:
    return {
        log.dataset: {"rows_after": log.rows_after, "rows_removed": log.rows_removed, "rows_modified": log.rows_modified}
        for log in run_cleaning()
    }


def validate_data() -> dict[str, int]:
    """Raises ValidationError (failing the task) if any critical check fails."""
    return dict(Counter(result.status for result in run_validation()))


def load_postgresql() -> dict[str, int]:
    return run_load()


def create_views() -> list[str]:
    return transformation.create_views()


def run_sales_analysis() -> dict[str, int]:
    return {name: len(df) for name, df in transformation.run_sales_analysis().items()}


def run_operations_analysis() -> dict[str, int]:
    return {name: len(df) for name, df in transformation.run_operations_analysis().items()}


def run_regional_analysis() -> dict[str, int]:
    return {name: len(df) for name, df in transformation.run_regional_analysis().items()}


def export_tableau_data() -> dict[str, int]:
    return transformation.export_dashboard_views()


def _to_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value.item() if hasattr(value, "item") else value


def _headline_metrics() -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    queries_by_file: dict[Path, dict[str, str]] = {}
    for path, name in SUMMARY_QUERIES:
        if path not in queries_by_file:
            queries_by_file[path] = transformation.parse_named_queries(path.read_text(encoding="utf-8"))
        row = query(queries_by_file[path][name]).to_dict(orient="records")[0]
        metrics[name] = {column: _to_json_value(value) for column, value in row.items()}
    return metrics


def generate_summary() -> dict[str, Any]:
    """Write data/processed/pipeline_summary.json with row counts, validation results and headline KPIs."""
    validation = json.loads(VALIDATION_REPORT_PATH.read_text(encoding="utf-8"))
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "table_row_counts": get_row_counts(),
        "validation_status_counts": dict(Counter(check["status"] for check in validation)),
        "headline_metrics": _headline_metrics(),
    }
    PIPELINE_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    metrics = summary["headline_metrics"]
    logger.info(
        "Summary: revenue R$%s | orders %s | AOV R$%s | late deliveries %s%% | validation %s",
        f"{metrics['total_revenue']['total_revenue']:,.2f}",
        f"{metrics['total_orders']['total_orders']:,}",
        metrics["average_order_value"]["average_order_value"],
        metrics["operations_kpis"]["late_delivery_pct"],
        summary["validation_status_counts"],
    )
    logger.info("Wrote pipeline summary: %s", PIPELINE_SUMMARY_PATH)
    return summary


# Execution order for a full run; the DAG runs the three analysis steps in parallel.
STEPS: dict[str, Callable[[], Any]] = {
    "check_raw_data": check_raw_data,
    "profile_data": profile_data,
    "clean_data": clean_data,
    "validate_data": validate_data,
    "load_postgresql": load_postgresql,
    "create_views": create_views,
    "run_sales_analysis": run_sales_analysis,
    "run_operations_analysis": run_operations_analysis,
    "run_regional_analysis": run_regional_analysis,
    "export_tableau_data": export_tableau_data,
    "generate_summary": generate_summary,
}


def run(step_names: list[str] | None = None) -> None:
    names = step_names or list(STEPS)
    unknown = [name for name in names if name not in STEPS]
    if unknown:
        raise ValueError(f"Unknown step(s): {unknown}. Choose from: {list(STEPS)}")

    pipeline_start = time.perf_counter()
    for name in names:
        step_start = time.perf_counter()
        logger.info("=== %s: started", name)
        STEPS[name]()
        logger.info("=== %s: finished in %.1fs", name, time.perf_counter() - step_start)
    logger.info("Pipeline finished in %.1fs", time.perf_counter() - pipeline_start)


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except Exception:
        logger.exception("Pipeline failed")
        raise SystemExit(1)
