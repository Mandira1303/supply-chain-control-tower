"""Run a .sql file against the supply_chain database.  Usage: python run_sql.py kpi_views.sql"""
import sys, os
from getpass import getpass
import psycopg2

if len(sys.argv) < 2:
    sys.exit("Usage: python run_sql.py <file.sql>")
password = os.getenv("PGPASSWORD") or getpass("Enter your PostgreSQL password (typing is hidden): ")
conn = psycopg2.connect(host="localhost", port=5432, user="postgres", password=password, dbname="supply_chain")
with open(sys.argv[1], encoding="utf-8") as f:
    sql = f.read()
with conn, conn.cursor() as cur:
    cur.execute(sql)
    print(f"Ran {sys.argv[1]} successfully.")
    try:
        cur.execute("SELECT * FROM kpi_summary")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            print("kpi_summary:", dict(zip(cols, row)))
    except psycopg2.Error:
        pass
conn.close()
