from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator

with DAG(
    dag_id="dummy_index_rebuild",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["autonoma", "dummy"],
) as dag:
    start = EmptyOperator(task_id="start")
    rebuild = EmptyOperator(task_id="rebuild")
    start >> rebuild
