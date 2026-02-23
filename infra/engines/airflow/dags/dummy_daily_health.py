from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator

with DAG(
    dag_id="dummy_daily_health",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["autonoma", "dummy"],
) as dag:
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")
    start >> end
