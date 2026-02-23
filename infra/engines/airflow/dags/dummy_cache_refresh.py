from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator

with DAG(
    dag_id="dummy_cache_refresh",
    start_date=datetime(2024, 1, 1),
    schedule="@hourly",
    catchup=False,
    tags=["autonoma", "dummy"],
) as dag:
    start = EmptyOperator(task_id="start")
    refresh = EmptyOperator(task_id="refresh")
    start >> refresh
