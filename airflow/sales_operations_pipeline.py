"""Daily Sales & Operations pipeline: raw CSV -> clean -> validate -> PostgreSQL -> analysis -> Tableau exports.

Each task calls one step in src/pipeline.py, so the DAG and `python -m src.pipeline`
run exactly the same code.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator


def run_step(step_name: str) -> Any:
    # Imported at run time so the scheduler can parse this file without loading pandas.
    from src import pipeline

    return pipeline.STEPS[step_name]()


default_args = {
    "owner": "analytics",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(minutes=30),
}

with DAG(
    dag_id="sales_operations_pipeline",
    description="Olist sales & operations analytics pipeline",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["olist", "analytics"],
) as dag:

    def step(task_id: str, **kwargs: Any) -> PythonOperator:
        return PythonOperator(task_id=task_id, python_callable=run_step, op_args=[task_id], **kwargs)

    check_raw_data = step("check_raw_data")
    profile_data = step("profile_data")
    clean_data = step("clean_data")
    # A critical validation failure is a data problem, not a transient one: don't retry.
    validate_data = step("validate_data", retries=0)
    load_postgresql = step("load_postgresql")
    create_views = step("create_views")
    run_sales_analysis = step("run_sales_analysis")
    run_operations_analysis = step("run_operations_analysis")
    run_regional_analysis = step("run_regional_analysis")
    export_tableau_data = step("export_tableau_data")
    generate_summary = step("generate_summary")

    analysis = [run_sales_analysis, run_operations_analysis, run_regional_analysis]

    check_raw_data >> profile_data >> clean_data >> validate_data >> load_postgresql >> create_views
    create_views >> analysis >> export_tableau_data >> generate_summary
