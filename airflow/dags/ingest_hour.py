"""
Simulates ONE new hour of retail operations and appends it to PostgreSQL.
Called by the Airflow DAG every hour. The simulated clock continues from the last hour
already in `inventory_hourly`, so each run adds exactly one new hour for every store x product.

The pure function `simulate_next_hour` has no database code, so it can be unit-tested.
"""
import os
from datetime import timedelta
import numpy as np

HOUR_CURVE = [0.2, 0.1, 0.1, 0.1, 0.2, 0.4, 0.7, 1.0, 1.2, 1.3, 1.4, 1.6,
              1.8, 1.6, 1.4, 1.3, 1.4, 1.7, 2.0, 1.8, 1.4, 1.0, 0.6, 0.3]
DAY_CURVE = [1.0, 0.95, 0.95, 1.0, 1.15, 1.4, 1.35]


def simulate_next_hour(next_ts, stock, products, stores, suppliers, open_orders, rng):
    """
    stock:       {(store_id, product_id): stock_level}
    products:    {product_id: {"base": float, "reorder": int, "max_stock": int, "supplier_id": int}}
    stores:      {store_id: size_factor}
    suppliers:   {supplier_id: {"lead": float, "reliability": float}}
    open_orders: list of dicts (store_id, product_id, supplier_id, ordered_ts, promised_ts, arrival_ts, quantity)
    Returns (inventory_rows, delivered_orders, open_orders_after).
    """
    stock = dict(stock)
    delivered, still_open = [], []
    for o in open_orders:
        if o["arrival_ts"] <= next_ts:
            stock[(o["store_id"], o["product_id"])] += o["quantity"]
            delivered.append(o)
        else:
            still_open.append(o)
    open_keys = {(o["store_id"], o["product_id"]) for o in still_open}
    season = HOUR_CURVE[next_ts.hour] * DAY_CURVE[next_ts.weekday()]

    inventory_rows, new_orders = [], []
    for (s, p) in sorted(stock):
        prod = products[p]
        demand = float(rng.poisson(prod["base"] * stores[s] * season))
        if rng.random() < 0.001:                         # occasional demand spike (anomaly)
            demand = round(demand * rng.uniform(5, 10))
        sold = min(demand, stock[(s, p)])
        unmet = demand - sold
        stock[(s, p)] -= sold
        level = float(stock[(s, p)])
        inventory_rows.append((next_ts, s, p, float(sold), float(unmet), level, level <= 0))
        if level <= prod["reorder"] and (s, p) not in open_keys:
            sup = suppliers[prod["supplier_id"]]
            on_time = rng.random() < sup["reliability"]
            lead = sup["lead"] * (rng.uniform(0.85, 1.1) if on_time else rng.uniform(1.3, 2.2))
            new_orders.append({
                "store_id": s, "product_id": p, "supplier_id": prod["supplier_id"],
                "ordered_ts": next_ts,
                "promised_ts": next_ts + timedelta(hours=int(sup["lead"])),
                "arrival_ts": next_ts + timedelta(hours=int(round(lead))),
                "quantity": int(prod["max_stock"] - level),
            })
    return inventory_rows, delivered, still_open + new_orders


def run():
    """Database wrapper: read state, simulate one hour, write results (one transaction)."""
    import psycopg2
    from psycopg2.extras import execute_values

    conn = psycopg2.connect(
        host=os.getenv("SC_DB_HOST", "host.docker.internal"),
        port=int(os.getenv("SC_DB_PORT", "5432")),
        user=os.getenv("SC_DB_USER", "postgres"),
        password=os.environ["SC_DB_PASSWORD"],
        dbname=os.getenv("SC_DB_NAME", "supply_chain"),
    )
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS open_orders (
        store_id bigint, product_id bigint, supplier_id bigint,
        ordered_ts timestamp, promised_ts timestamp, arrival_ts timestamp, quantity bigint)""")

    cur.execute("SELECT MAX(ts) FROM inventory_hourly")
    last_ts = cur.fetchone()[0]
    next_ts = last_ts + timedelta(hours=1)

    cur.execute("SELECT store_id, product_id, stock_level FROM inventory_hourly WHERE ts = %s", (last_ts,))
    stock = {(s, p): float(v) for s, p, v in cur.fetchall()}
    cur.execute("SELECT product_id, base_hourly_demand, reorder_point, max_stock, supplier_id FROM products")
    products = {p: {"base": float(b), "reorder": int(r), "max_stock": int(m), "supplier_id": int(sid)}
                for p, b, r, m, sid in cur.fetchall()}
    cur.execute("SELECT store_id, size_factor FROM stores")
    stores = {s: float(f) for s, f in cur.fetchall()}
    cur.execute("SELECT supplier_id, avg_lead_time_hours, reliability FROM suppliers")
    suppliers = {s: {"lead": float(l), "reliability": float(r)} for s, l, r in cur.fetchall()}
    cur.execute("SELECT store_id, product_id, supplier_id, ordered_ts, promised_ts, arrival_ts, quantity FROM open_orders")
    keys = ["store_id", "product_id", "supplier_id", "ordered_ts", "promised_ts", "arrival_ts", "quantity"]
    open_orders = [dict(zip(keys, row)) for row in cur.fetchall()]

    rng = np.random.default_rng()
    inv_rows, delivered, orders_after = simulate_next_hour(
        next_ts, stock, products, stores, suppliers, open_orders, rng)

    execute_values(cur, "INSERT INTO inventory_hourly (ts, store_id, product_id, units_sold, units_unmet, "
                        "stock_level, is_stockout) VALUES %s", inv_rows)
    if delivered:
        cur.execute("SELECT COALESCE(MAX(shipment_id), 0) FROM shipments")
        sid = cur.fetchone()[0]
        ship_rows = []
        for o in delivered:
            sid += 1
            lead = (o["arrival_ts"] - o["ordered_ts"]).total_seconds() / 3600
            ship_rows.append((sid, o["store_id"], o["product_id"], o["supplier_id"], o["ordered_ts"],
                              o["promised_ts"], o["arrival_ts"], o["quantity"], lead,
                              o["arrival_ts"] <= o["promised_ts"]))
        execute_values(cur, "INSERT INTO shipments (shipment_id, store_id, product_id, supplier_id, ordered_ts, "
                            "promised_ts, delivered_ts, quantity, lead_time_hours, on_time) VALUES %s", ship_rows)
    cur.execute("DELETE FROM open_orders")
    if orders_after:
        execute_values(cur, "INSERT INTO open_orders VALUES %s",
                       [tuple(o[k] for k in keys) for o in orders_after])
    conn.commit()
    conn.close()
    msg = (f"Ingested hour {next_ts}: {len(inv_rows)} inventory rows, "
           f"{len(delivered)} shipments delivered, {len(orders_after)} open orders")
    print(msg)
    return msg
