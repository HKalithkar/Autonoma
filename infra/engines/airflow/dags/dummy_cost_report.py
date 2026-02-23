from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator

with DAG(
    dag_id="dummy_cost_report",
    start_date=datetime(2024, 1, 1),
    schedule="@weekly",
    catchup=False,
    tags=["autonoma", "dummy"],
) as dag:
    start = EmptyOperator(task_id="start")
    report = EmptyOperator(task_id="report")
    start >> report
