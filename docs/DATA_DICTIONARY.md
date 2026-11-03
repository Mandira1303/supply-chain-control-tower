# Data Dictionary

Database: `supply_chain` (PostgreSQL 16). All data is simulated by `generate_data.py`; new hours are appended by the Airflow DAG.

## Base tables
### stores (10 rows)
| Column | Type | Description |
|---|---|---|
| store_id | int | Primary key, 1-10 |
| store_name | text | e.g. "Store Mumbai" |
| city | text | City of the store |
| size_factor | float | Demand multiplier (0.7-1.4); busier stores sell more |

### products (20 rows)
| Column | Type | Description |
|---|---|---|
| product_id | int | Primary key, 1-20 |
| product_name | text | e.g. "Product 04" |
| category | text | One of 5 product categories |
| unit_price | float | Selling price per unit |
| base_hourly_demand | float | Average units sold per hour before seasonality |
| reorder_point | int | Stock level that triggers a replenishment order |
| max_stock | int | Maximum stock level |
| supplier_id | int | Supplier of this product |

### suppliers (5 rows)
| Column | Type | Description |
|---|---|---|
| supplier_id | int | Primary key, 1-5 |
| supplier_name | text | Apex Foods, BlueRiver Traders, Crest Supply Co, Delta Wholesale, EverFresh Ltd |
| avg_lead_time_hours | float | Promised lead time (24-60 h) |
| reliability | float | Probability a shipment arrives on time (0.70-0.95) |

### inventory_hourly (grain: store x product x hour; 434,800 rows at last check, grows by 200 per hour)
| Column | Type | Description |
|---|---|---|
| ts | timestamp | Hour of the observation |
| store_id, product_id | int | Foreign keys |
| units_sold | float | Units sold in that hour |
| units_unmet | float | Demand that could not be served (stock ran out) |
| stock_level | float | Stock at end of hour |
| is_stockout | bool | True when stock_level <= 0 |

### shipments (2,787 rows)
| Column | Type | Description |
|---|---|---|
| shipment_id | int | Primary key |
| store_id, product_id, supplier_id | int | Foreign keys |
| ordered_ts, promised_ts, delivered_ts | timestamp | Order, promised and actual delivery times |
| quantity | int | Units shipped |
| lead_time_hours | float | delivered_ts - ordered_ts, in hours |
| on_time | bool | delivered_ts <= promised_ts |

### open_orders
Working table used by the Airflow ingest task to track orders that have not arrived yet (store_id, product_id, supplier_id, ordered_ts, promised_ts, arrival_ts, quantity).

## Output tables
### anomalies (1,614 rows)
| Column | Description |
|---|---|
| ts, store_id, product_id | Where and when the anomaly occurred |
| units_sold, units_unmet, stock_level | Values at that hour |
| method | `z_score` (318 rows) or `isolation_forest` (1,296 rows) |
| score | z-score value, or Isolation Forest anomaly score |

### demand_forecast (3,360 rows = 20 products x 168 hours)
| Column | Description |
|---|---|
| product_id | Product forecast |
| ts | Forecast hour (next 7 days) |
| yhat, yhat_lower, yhat_upper | Prophet forecast and its uncertainty interval (units per hour) |

### forecast_accuracy (20 rows)
| Column | Description |
|---|---|
| product_id | Product |
| mae | Mean absolute error on the backtest window |
| wape_pct | Weighted absolute percentage error (overall about 21.9%) |

### alerts
| Column | Description |
|---|---|
| id, created_at, data_ts | Alert id, when it was raised, data hour it refers to |
| alert_name | stockout_rate_24h_pct, on_time_delivery_7d_pct, avg_lead_time_7d_hours, critical_stock_items or demand_spikes_latest_hour |
| severity | critical, warning or info |
| message | Human-readable text |
| value, threshold | Measured value and the threshold it crossed |
| notified | True once sent to Slack or email |

## KPI views (`kpi_views.sql`)
| View | Definition |
|---|---|
| v_inventory_hourly | inventory_hourly joined with store and product names, plus revenue |
| kpi_stockout_rate_daily | % of store-product-hours with zero stock, per day and store |
| kpi_on_time_delivery_weekly | % of shipments on time, per week and supplier |
| kpi_supplier_lead_time_weekly | Average and maximum lead time per week and supplier, with the promised lead time |
| kpi_days_of_inventory | Latest stock divided by average daily sales of the last 7 days, per store and product |
| kpi_summary | One row with the four headline KPIs used on the dashboard |

## Entity relationships
`stores` and `products` link to `inventory_hourly` and `shipments` by store_id and product_id. `products` links to `suppliers` by supplier_id, and `shipments` links to `suppliers` too.
