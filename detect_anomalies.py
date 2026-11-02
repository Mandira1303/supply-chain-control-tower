"""
Anomaly detection for the Retail & Supply Chain Control Tower.

Two methods are applied to hourly sales per store x product:
  1. Seasonal z-score : compares each hour with the normal level for the same store, product, hour and weekday/weekend.
  2. Isolation Forest : multivariate model on sales, unmet demand, stock level and time features.

Results are written to the PostgreSQL table `anomalies`.

Usage:
    python detect_anomalies.py              # read from PostgreSQL, write table `anomalies`
    python detect_anomalies.py --csv data   # test mode: read CSVs from ./data, no database
"""
import os
import sys
import io
from getpass import getpass
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

Z_THRESHOLD = 4.0          # z-score above this is flagged (spikes in demand)
MIN_SALES = 5              # ignore tiny absolute values (avoids flagging 0 -> 2 units)
CONTAMINATION = 0.003      # expected share of anomalies for Isolation Forest


def load_from_db():
    import psycopg2
    password = os.getenv("PGPASSWORD") or getpass("Enter your PostgreSQL password (typing is hidden): ")
    conn = psycopg2.connect(host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), user="postgres",
                            password=password, dbname="supply_chain")
    cur = conn.cursor()
    cur.execute("SELECT ts, store_id, product_id, units_sold, units_unmet, stock_level "
                "FROM inventory_hourly ORDER BY store_id, product_id, ts")
    cols = [d[0] for d in cur.description]
    df = pd.DataFrame(cur.fetchall(), columns=cols)
    for c in ["units_sold", "units_unmet", "stock_level"]:
        df[c] = df[c].astype(float)
    return df, conn


def zscore_anomalies(df):
    """Z-score against the normal level for the SAME store, product, hour of day and weekday/weekend.
    This stops normal lunch/evening peaks and weekend rushes from being flagged."""
    out = df.copy()
    out["hour"] = out["ts"].dt.hour
    out["weekend"] = out["ts"].dt.dayofweek >= 5
    grp = out.groupby(["store_id", "product_id", "hour", "weekend"])["units_sold"]
    mean = grp.transform("mean")
    std = grp.transform("std").clip(lower=1.0)        # floor avoids huge z on very quiet hours
    out["z_score"] = (out["units_sold"] - mean) / std
    flagged = out[(out["z_score"] > Z_THRESHOLD) & (out["units_sold"] >= MIN_SALES)].copy()
    flagged["method"] = "z_score"
    flagged["score"] = flagged["z_score"].round(2)
    return flagged


def isolation_forest_anomalies(df):
    X = df[["units_sold", "units_unmet", "stock_level"]].copy()
    X["hour"] = df["ts"].dt.hour
    X["dow"] = df["ts"].dt.dayofweek
    # scale sales and stock per product so large products do not dominate
    for c in ["units_sold", "units_unmet", "stock_level"]:
        X[c] = X[c] / df.groupby("product_id")[c].transform("mean").replace(0, 1)
    model = IsolationForest(n_estimators=200, contamination=CONTAMINATION, random_state=42, n_jobs=-1)
    pred = model.fit_predict(X)
    scores = -model.score_samples(X)                     # higher = more anomalous
    out = df.copy()
    out["score"] = scores.round(3)
    flagged = out[pred == -1].copy()
    flagged["method"] = "isolation_forest"
    return flagged


def main():
    conn = None
    if "--csv" in sys.argv:
        folder = sys.argv[sys.argv.index("--csv") + 1]
        df = pd.read_csv(f"{folder}/inventory_hourly.csv", parse_dates=["ts"])
        df = df[["ts", "store_id", "product_id", "units_sold", "units_unmet", "stock_level"]]
        df = df.sort_values(["store_id", "product_id", "ts"]).reset_index(drop=True)
    else:
        df, conn = load_from_db()
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.reset_index(drop=True)
    print(f"Loaded {len(df):,} hourly rows")

    z = zscore_anomalies(df)
    iso = isolation_forest_anomalies(df)
    cols = ["ts", "store_id", "product_id", "units_sold", "units_unmet", "stock_level", "method", "score"]
    result = pd.concat([z[cols], iso[cols]]).sort_values("ts").reset_index(drop=True)
    print(f"Z-score anomalies:           {len(z):,}")
    print(f"Isolation Forest anomalies:  {len(iso):,}")
    both = z.merge(iso, on=["ts", "store_id", "product_id"])
    print(f"Flagged by BOTH methods:     {len(both):,}")
    print(result.tail(5).to_string(index=False))

    if conn is None:
        result.to_csv("anomalies.csv", index=False)
        print("Saved anomalies.csv (test mode, no database)")
        return
    cur = conn.cursor()
    cur.execute("""DROP TABLE IF EXISTS anomalies;
                   CREATE TABLE anomalies (ts timestamp, store_id bigint, product_id bigint,
                       units_sold float8, units_unmet float8, stock_level float8,
                       method text, score float8);""")
    buf = io.StringIO()
    result.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cur.copy_expert("COPY anomalies FROM STDIN WITH CSV", buf)
    conn.commit()
    print(f"Wrote {len(result):,} rows to table anomalies")
    conn.close()


if __name__ == "__main__":
    main()
