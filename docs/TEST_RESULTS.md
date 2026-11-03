# Test Results

Run on 3 Nov 2026 on a local Docker environment (PostgreSQL 16, Airflow 2.10.5, Superset 3.1.3).

| # | Test | Expected | Result |
|---|---|---|---|
| 1 | Data load | 10 stores, 20 products, 5 suppliers, 432,000 hourly rows, 2,787 shipments | Pass: counts match (hourly table now 434,800 after Airflow runs) |
| 2 | KPI views | `kpi_summary` returns one row with 4 values | Pass: stock-out 11.07%, on-time delivery 57.66%, lead time 41.3 h, days of inventory 3 |
| 3 | Anomaly detection | Both methods write to `anomalies` | Pass: 1,614 rows (318 z-score, 1,296 Isolation Forest) |
| 4 | Forecast | 7-day hourly forecast for each product | Pass: 3,360 rows = 20 products x 168 hours |
| 5 | Forecast accuracy | Backtest error recorded | Pass: overall WAPE about 21.9% (range 12.8% to 34.7% by product) |
| 6 | Ingest simulation | Simulation runs for many hours without errors | Pass: 168 simulated hours |
| 7 | Airflow DAG | `supply_chain_hourly` runs green | Pass: 13 successful runs, 0 failed |
| 8 | Alerts | Threshold breach is written to the `alerts` table | Pass: critical_stock_items alerts raised (52 and 53 against threshold 25) |
| 9 | Dashboard | All charts load and the scenario filter works | Pass: 11 charts rendered, Scenario filter has 5 options |
| 10 | What-if | At-risk items rise with demand and supplier delay | Pass: 54, 61, 80, 86, 102 at-risk items across the five scenarios on the test snapshot |

## Known limitations
- Slack and email notifications were not enabled during testing, so alerts show `notified = false`.
- Data is simulated; the forecast and anomaly results show the method works, not real business accuracy.
- Airflow uses SQLite and SequentialExecutor, which is suitable for a demo only.

Evidence screenshots are in `docs/`: `airflows_runs.png`, `dashboard_full.png`, `dashboard_full_filter.png`, `alerts_proof.png`.
