"""Airflow DAG: hourly refresh of the Retail & Supply Chain Control Tower."""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import ingest_hour
import alerts

with DAG(
    dag_id="supply_chain_hourly",
    description="Ingest the next hour of retail data into PostgreSQL, then check KPI alerts",
    start_date=datetime(2026, 10, 30),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    tags=["supply-chain"],
) as dag:
    ingest_next_hour = PythonOperator(task_id="ingest_next_hour", python_callable=ingest_hour.run)
    check_alerts = PythonOperator(task_id="check_alerts", python_callable=alerts.run)
    ingest_next_hour >> check_alerts
