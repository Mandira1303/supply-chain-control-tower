FROM apache/airflow:2.10.5
COPY requirements-airflow.txt /requirements-airflow.txt
RUN pip install --no-cache-dir -r /requirements-airflow.txt \
    -c https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt
RUN mkdir -p /opt/airflow/db
