-- KPI views for the Retail & Supply Chain Control Tower
-- Run with: python run_sql.py kpi_views.sql

-- 1) Hourly KPIs per store x product (base view for dashboards)
CREATE OR REPLACE VIEW v_inventory_hourly AS
SELECT i.ts, i.store_id, s.store_name, i.product_id, p.product_name, p.category,
       i.units_sold, i.units_unmet, i.stock_level, i.is_stockout,
       p.unit_price, i.units_sold * p.unit_price AS revenue
FROM inventory_hourly i
JOIN stores   s ON s.store_id   = i.store_id
JOIN products p ON p.product_id = i.product_id;

-- 2) Stock-out rate (% of store-product-hours with zero stock), daily by store
CREATE OR REPLACE VIEW kpi_stockout_rate_daily AS
SELECT date_trunc('day', ts)::date AS day, store_id, store_name,
       COUNT(*) AS observations,
       SUM(CASE WHEN is_stockout THEN 1 ELSE 0 END) AS stockout_observations,
       ROUND(100.0 * AVG(CASE WHEN is_stockout THEN 1 ELSE 0 END)::numeric, 2) AS stockout_rate_pct
FROM v_inventory_hourly
GROUP BY 1, 2, 3;

-- 3) On-time delivery rate by supplier, weekly
CREATE OR REPLACE VIEW kpi_on_time_delivery_weekly AS
SELECT date_trunc('week', sh.delivered_ts)::date AS week, sh.supplier_id, su.supplier_name,
       COUNT(*) AS shipments,
       SUM(CASE WHEN sh.on_time THEN 1 ELSE 0 END) AS on_time_shipments,
       ROUND(100.0 * AVG(CASE WHEN sh.on_time THEN 1 ELSE 0 END)::numeric, 2) AS on_time_pct
FROM shipments sh
JOIN suppliers su ON su.supplier_id = sh.supplier_id
GROUP BY 1, 2, 3;

-- 4) Supplier lead time (hours), weekly
CREATE OR REPLACE VIEW kpi_supplier_lead_time_weekly AS
SELECT date_trunc('week', sh.delivered_ts)::date AS week, sh.supplier_id, su.supplier_name,
       ROUND(AVG(sh.lead_time_hours)::numeric, 1) AS avg_lead_time_hours,
       ROUND(MAX(sh.lead_time_hours)::numeric, 1) AS max_lead_time_hours,
       su.avg_lead_time_hours AS promised_lead_time_hours
FROM shipments sh
JOIN suppliers su ON su.supplier_id = sh.supplier_id
GROUP BY 1, 2, 3, su.avg_lead_time_hours;

-- 5) Days of inventory (latest stock / average daily sales of the last 7 days), per store x product
CREATE OR REPLACE VIEW kpi_days_of_inventory AS
WITH latest AS (
    SELECT DISTINCT ON (store_id, product_id) store_id, product_id, ts, stock_level
    FROM inventory_hourly
    ORDER BY store_id, product_id, ts DESC
),
recent AS (
    SELECT i.store_id, i.product_id, SUM(i.units_sold) / 7.0 AS avg_daily_sales
    FROM inventory_hourly i
    WHERE i.ts > (SELECT MAX(ts) FROM inventory_hourly) - INTERVAL '7 days'
    GROUP BY 1, 2
)
SELECT l.store_id, s.store_name, l.product_id, p.product_name, l.ts AS as_of,
       l.stock_level, ROUND(r.avg_daily_sales::numeric, 2) AS avg_daily_sales,
       ROUND((l.stock_level / NULLIF(r.avg_daily_sales, 0))::numeric, 1) AS days_of_inventory
FROM latest l
JOIN recent   r ON r.store_id = l.store_id AND r.product_id = l.product_id
JOIN stores   s ON s.store_id = l.store_id
JOIN products p ON p.product_id = l.product_id;

-- 6) One-row summary of the headline KPIs (for the top of the dashboard)
CREATE OR REPLACE VIEW kpi_summary AS
SELECT
  (SELECT ROUND(100.0 * AVG(CASE WHEN is_stockout THEN 1 ELSE 0 END)::numeric, 2) FROM inventory_hourly)  AS stockout_rate_pct,
  (SELECT ROUND(100.0 * AVG(CASE WHEN on_time THEN 1 ELSE 0 END)::numeric, 2) FROM shipments)             AS on_time_delivery_pct,
  (SELECT ROUND(AVG(lead_time_hours)::numeric, 1) FROM shipments)                                         AS avg_supplier_lead_time_hours,
  (SELECT ROUND(AVG(days_of_inventory), 1) FROM kpi_days_of_inventory)                                    AS avg_days_of_inventory;
