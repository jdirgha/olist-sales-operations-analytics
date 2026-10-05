"""SQL file structure tests, plus database reconciliation tests that run when PostgreSQL is reachable."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src import pipeline
from src.config import SQL_DIR
from src.transformation import (
    ANALYTICAL_VIEWS_FILE,
    DATA_QUALITY_FILE,
    OPERATIONS_ANALYSIS_FILE,
    REGIONAL_ANALYSIS_FILE,
    SALES_ANALYSIS_FILE,
    ddl_section,
    parse_named_queries,
)

ANALYSIS_FILES = [SALES_ANALYSIS_FILE, OPERATIONS_ANALYSIS_FILE, REGIONAL_ANALYSIS_FILE, DATA_QUALITY_FILE]
SELECT_STAR = re.compile(r"\bSELECT\s+(DISTINCT\s+)?\*|\b\w+\.\*", re.IGNORECASE)


def strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


class TestParseNamedQueries:
    def test_splits_on_markers(self) -> None:
        sql = "-- header comment\n-- name: first\nSELECT 1;\n\n-- name: second\nSELECT 2\n;"
        assert parse_named_queries(sql) == {"first": "SELECT 1", "second": "SELECT 2"}

    def test_marker_must_be_on_its_own_line(self) -> None:
        sql = '-- Each query is preceded by "-- name: <query_name>"\n-- name: only\nSELECT 1;'
        assert list(parse_named_queries(sql)) == ["only"]

    @pytest.mark.parametrize(
        ("sql", "message"),
        [
            ("SELECT 1;", "No '-- name"),
            ("-- name: a\nSELECT 1;\n-- name: a\nSELECT 2;", "Duplicate query name"),
            ("-- name: a\n;\n-- name: b\nSELECT 2;", "is empty"),
        ],
    )
    def test_rejects_invalid_files(self, sql: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_named_queries(sql)


def test_ddl_section_stops_at_first_query() -> None:
    sql = "CREATE VIEW v AS SELECT 1;\n-- name: q\nSELECT 2;"
    assert ddl_section(sql).strip() == "CREATE VIEW v AS SELECT 1;"


@pytest.mark.parametrize(
    ("path", "expected_queries"),
    [(SALES_ANALYSIS_FILE, 15), (OPERATIONS_ANALYSIS_FILE, 13), (REGIONAL_ANALYSIS_FILE, 4), (DATA_QUALITY_FILE, 2)],
    ids=lambda value: value.name if isinstance(value, Path) else str(value),
)
def test_analysis_files_parse(path: Path, expected_queries: int) -> None:
    assert len(parse_named_queries(path.read_text(encoding="utf-8"))) == expected_queries


@pytest.mark.parametrize("path", sorted(SQL_DIR.glob("*.sql")), ids=lambda p: p.name)
def test_no_select_star(path: Path) -> None:
    sql = strip_comments(path.read_text(encoding="utf-8"))
    sql = re.sub(r"COUNT\(\*\)", "", sql, flags=re.IGNORECASE)
    assert not SELECT_STAR.search(sql), f"SELECT * found in {path.name}"


def test_views_are_created_before_queries() -> None:
    assert "CREATE" in ddl_section(ANALYTICAL_VIEWS_FILE.read_text(encoding="utf-8")).upper()
    assert "CREATE" in ddl_section(DATA_QUALITY_FILE.read_text(encoding="utf-8")).upper()


def test_pipeline_rejects_unknown_step() -> None:
    with pytest.raises(ValueError, match="Unknown step"):
        pipeline.run(["not_a_step"])


def test_dag_runs_every_pipeline_step() -> None:
    dag_source = (Path(pipeline.__file__).parent.parent / "airflow" / "sales_operations_pipeline.py").read_text()
    task_ids = set(re.findall(r'step\("(\w+)"', dag_source))
    assert task_ids == set(pipeline.STEPS)


# ---------------------------------------------------------------- database reconciliation


@pytest.fixture(scope="module")
def db():
    from src.database import check_connection, query

    try:
        check_connection()
    except Exception as exc:  # no .env, server down, wrong password ...
        pytest.skip(f"PostgreSQL not available: {exc}")
    return query


def named(path: Path, name: str) -> str:
    return parse_named_queries(path.read_text(encoding="utf-8"))[name]


@pytest.mark.database
class TestViewsReconcileWithAnalysis:
    def test_sales_view_revenue_matches_kpi(self, db) -> None:
        kpi = db(named(SALES_ANALYSIS_FILE, "total_revenue"))["total_revenue"].iloc[0]
        view = db("SELECT SUM(revenue) AS revenue FROM sales_dashboard")["revenue"].iloc[0]
        assert float(view) == pytest.approx(float(kpi), abs=0.01)

    def test_sales_view_keeps_every_order(self, db) -> None:
        orders = db("SELECT COUNT(*) AS n FROM orders")["n"].iloc[0]
        view = db("SELECT COUNT(DISTINCT order_id) AS n FROM sales_dashboard")["n"].iloc[0]
        assert view == orders

    def test_operations_view_late_rate_matches_kpi(self, db) -> None:
        kpi = db(named(OPERATIONS_ANALYSIS_FILE, "late_delivery_rate"))
        view = db(
            "SELECT COUNT(*) FILTER (WHERE is_late) AS late, COUNT(*) AS delivered "
            "FROM operations_dashboard WHERE is_measurable_delivery"
        )
        assert view["delivered"].iloc[0] == kpi["delivered_orders"].iloc[0]
        assert view["late"].iloc[0] == kpi["late_orders"].iloc[0]

    def test_regional_view_covers_all_revenue(self, db) -> None:
        total = db("SELECT SUM(revenue) AS revenue FROM sales_dashboard")["revenue"].iloc[0]
        regional = db("SELECT SUM(revenue) AS revenue, SUM(revenue_share_pct) AS share FROM regional_dashboard")
        assert float(regional["revenue"].iloc[0]) == pytest.approx(float(total), abs=0.01)
        assert float(regional["share"].iloc[0]) == pytest.approx(100, abs=0.1)

    def test_no_failed_data_quality_checks(self, db) -> None:
        failed = db("SELECT COUNT(*) AS n FROM data_quality_summary WHERE status = 'FAIL'")["n"].iloc[0]
        assert failed == 0
