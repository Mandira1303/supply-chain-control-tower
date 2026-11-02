"""
Simulated hourly retail & supply chain data generator.
Creates 5 tables and loads them into PostgreSQL (database: supply_chain).

Usage:
    python generate_data.py              # generate + load into PostgreSQL
    python generate_data.py --csv-only   # only write CSV files to ./data (no database)

The script asks for your PostgreSQL password, creates the supply_chain database if needed, and loads the tables.
"""
import os
import sys
import numpy as np
import pandas as pd

DB_NAME = "supply_chain"
DAYS = 90                      # amount of history
END_TS = pd.Timestamp("2026-10-30 00:00:00")
SEED = 42
rng = np.random.default_rng(SEED)

# ---------- Dimension tables ----------
cities = ["Bhubaneswar", "Kolkata", "Delhi", "Mumbai", "Chennai",
          "Bengaluru", "Hyderabad", "Pune", "Jaipur", "Lucknow"]
stores = pd.DataFrame({
    "store_id": range(1, 11),
    "store_name": [f"Store {c}" for c in cities],
    "city": cities,
    "size_factor": rng.uniform(0.7, 1.4, 10).round(2),   # busier stores sell more
})

categories = ["Grocery", "Beverages", "Personal Care", "Household", "Snacks"]
products = pd.DataFrame({
    "product_id": range(1, 21),
    "product_name": [f"Product {i:02d}" for i in range(1, 21)],
    "category": [categories[i % 5] for i in range(20)],
    "unit_price": rng.uniform(20, 500, 20).round(2),
    "base_hourly_demand": rng.uniform(0.5, 4.0, 20).round(2),
    "reorder_point": rng.integers(40, 120, 20),
    "max_stock": rng.integers(300, 600, 20),
})

suppliers = pd.DataFrame({
    "supplier_id": range(1, 6),
    "supplier_name": ["Apex Foods", "BlueRiver Traders", "Crest Supply Co", "Delta Wholesale", "EverFresh Ltd"],
    "avg_lead_time_hours": [24, 36, 48, 30, 60],
    "reliability": [0.95, 0.88, 0.80, 0.92, 0.70],     # chance a shipment is on time
})
products["supplier_id"] = (products["product_id"] % 5) + 1

# ---------- Hourly fact: inventory + sales ----------
hours = pd.date_range(end=END_TS, periods=DAYS * 24, freq="h")
H = len(hours)
hod = hours.hour.values
dow = hours.dayofweek.values
# demand shape: peaks at lunch and evening, higher on weekends
hour_curve = np.array([0.2,0.1,0.1,0.1,0.2,0.4,0.7,1.0,1.2,1.3,1.4,1.6,
                       1.8,1.6,1.4,1.3,1.4,1.7,2.0,1.8,1.4,1.0,0.6,0.3])
day_curve = np.array([1.0, 0.95, 0.95, 1.0, 1.15, 1.4, 1.35])
season = hour_curve[hod] * day_curve[dow]

rows = []
shipments = []
shipment_id = 1
for _, s in stores.iterrows():
    for _, p in products.iterrows():
        lam = p.base_hourly_demand * s.size_factor * season
        demand = rng.poisson(lam).astype(float)
        # inject demand spikes (anomalies) ~0.1% of hours
        spikes = rng.random(H) < 0.001
        demand[spikes] *= rng.uniform(5, 10, spikes.sum())
        demand = demand.round()
        stock = float(p.max_stock)
        pending = []   # (arrival_hour_index, qty)
        sup = suppliers.loc[suppliers.supplier_id == p.supplier_id].iloc[0]
        for i in range(H):
            # receive arrivals
            arrived = [q for (a, q) in pending if a <= i]
            pending = [(a, q) for (a, q) in pending if a > i]
            stock += sum(arrived)
            sold = min(demand[i], stock)
            unmet = demand[i] - sold
            stock -= sold
            # reorder
            if stock <= p.reorder_point and not pending:
                qty = int(p.max_stock - stock)
                on_time = rng.random() < sup.reliability
                lead = sup.avg_lead_time_hours * (rng.uniform(0.85, 1.1) if on_time else rng.uniform(1.3, 2.2))
                lead = int(round(lead))
                promised = int(sup.avg_lead_time_hours)
                pending.append((i + lead, qty))
                if i + lead < H:
                    shipments.append((shipment_id, int(s.store_id), int(p.product_id), int(sup.supplier_id),
                                      hours[i], hours[i] + pd.Timedelta(hours=promised),
                                      hours[i + lead], qty))
                    shipment_id += 1
            rows.append((hours[i], int(s.store_id), int(p.product_id), sold, unmet, stock))

inventory = pd.DataFrame(rows, columns=["ts", "store_id", "product_id", "units_sold", "units_unmet", "stock_level"])
inventory["is_stockout"] = inventory["stock_level"] <= 0
ship = pd.DataFrame(shipments, columns=["shipment_id", "store_id", "product_id", "supplier_id",
                                        "ordered_ts", "promised_ts", "delivered_ts", "quantity"])
ship["lead_time_hours"] = (ship["delivered_ts"] - ship["ordered_ts"]).dt.total_seconds() / 3600
ship["on_time"] = ship["delivered_ts"] <= ship["promised_ts"]

tables = {"stores": stores, "products": products, "suppliers": suppliers,
          "inventory_hourly": inventory, "shipments": ship}

if "--csv-only" in sys.argv:
    os.makedirs("data", exist_ok=True)
    for name, df in tables.items():
        df.to_csv(f"data/{name}.csv", index=False)
        print(f"{name}: {len(df):,} rows -> data/{name}.csv")
else:
    from getpass import getpass
    from urllib.parse import quote_plus
    import psycopg2
    from sqlalchemy import create_engine
    password = os.getenv("PGPASSWORD") or getpass("Enter your PostgreSQL password (typing is hidden): ")
    # create the database if it does not exist yet
    admin = psycopg2.connect(host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), user="postgres", password=password, dbname="postgres")
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if not cur.fetchone():
        cur.execute(f"CREATE DATABASE {DB_NAME}")
        print(f"Created database {DB_NAME}")
    admin.close()
    engine = create_engine(f"postgresql+psycopg2://postgres:{quote_plus(password)}@{os.getenv('PGHOST', 'localhost')}:{os.getenv('PGPORT', '5432')}/{DB_NAME}")
    for name, df in tables.items():
        df.to_sql(name, engine, if_exists="replace", index=False, chunksize=20000, method="multi")
        print(f"{name}: {len(df):,} rows loaded")
    print("Done.")
