"""
Demand forecasting with Prophet for the Retail & Supply Chain Control Tower.

For every product (all stores combined) it:
  1. BACKTEST: trains on all data except the last 7 days, predicts those 7 days and measures the error.
  2. FORECAST: retrains on all data and predicts the NEXT 7 days (168 hours).

Writes two PostgreSQL tables:  demand_forecast  and  forecast_accuracy.

Usage:
    python forecast_demand.py              # read from PostgreSQL, write the tables
    python forecast_demand.py --csv data   # test mode: read CSVs from ./data, write CSVs, no database
"""
import os
import sys
import io
import logging
from getpass import getpass
import numpy as np
import pandas as pd
from prophet import Prophet

logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

HORIZON = 24 * 7          # forecast 7 days ahead, hourly


def load_from_db():
    import psycopg2
    password = os.getenv("PGPASSWORD") or getpass("Enter your PostgreSQL password (typing is hidden): ")
    conn = psycopg2.connect(host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), user="postgres",
                            password=password, dbname="supply_chain")
    cur = conn.cursor()
    cur.execute("SELECT ts, product_id, SUM(units_sold) AS units_sold "
                "FROM inventory_hourly GROUP BY ts, product_id ORDER BY product_id, ts")
    df = pd.DataFrame(cur.fetchall(), columns=["ts", "product_id", "units_sold"])
    df["units_sold"] = df["units_sold"].astype(float)
    df["ts"] = pd.to_datetime(df["ts"])
    return df, conn


def make_model():
    return Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=False,
                   interval_width=0.9, changepoint_prior_scale=0.05)


def future_frame(last_ts, periods):
    return pd.DataFrame({"ds": pd.date_range(last_ts + pd.Timedelta(hours=1), periods=periods, freq="h")})


def main():
    conn = None
    if "--csv" in sys.argv:
        folder = sys.argv[sys.argv.index("--csv") + 1]
        raw = pd.read_csv(f"{folder}/inventory_hourly.csv", parse_dates=["ts"])
        df = raw.groupby(["product_id", "ts"], as_index=False)["units_sold"].sum()
    else:
        df, conn = load_from_db()

    forecasts, accuracy = [], []
    products = sorted(df["product_id"].unique())
    for n, pid in enumerate(products, 1):
        s = df[df["product_id"] == pid].sort_values("ts")[["ts", "units_sold"]].rename(columns={"ts": "ds", "units_sold": "y"})
        # 1) backtest on the last 7 days
        train, test = s.iloc[:-HORIZON], s.iloc[-HORIZON:]
        m = make_model().fit(train)
        pred = m.predict(test[["ds"]])
        yhat = pred["yhat"].clip(lower=0).values
        mae = float(np.mean(np.abs(test["y"].values - yhat)))
        wape = float(np.sum(np.abs(test["y"].values - yhat)) / max(test["y"].sum(), 1) * 100)
        accuracy.append((int(pid), round(mae, 2), round(wape, 2)))
        # 2) real forecast for the next 7 days
        m = make_model().fit(s)
        fut = m.predict(future_frame(s["ds"].max(), HORIZON))
        out = fut[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
        for c in ["yhat", "yhat_lower", "yhat_upper"]:
            out[c] = out[c].clip(lower=0).round(2)
        out.insert(0, "product_id", int(pid))
        forecasts.append(out)
        print(f"[{n}/{len(products)}] product {pid}: backtest MAE={mae:.2f} units/hour, WAPE={wape:.1f}%")

    forecast_df = pd.concat(forecasts, ignore_index=True).rename(columns={"ds": "ts"})
    acc_df = pd.DataFrame(accuracy, columns=["product_id", "mae", "wape_pct"])
    print(f"\nAverage backtest WAPE across products: {acc_df['wape_pct'].mean():.1f}%")

    if conn is None:
        forecast_df.to_csv("demand_forecast.csv", index=False)
        acc_df.to_csv("forecast_accuracy.csv", index=False)
        print("Saved demand_forecast.csv and forecast_accuracy.csv (test mode)")
        return
    cur = conn.cursor()
    cur.execute("""DROP TABLE IF EXISTS demand_forecast;
                   DROP TABLE IF EXISTS forecast_accuracy;
                   CREATE TABLE demand_forecast (product_id bigint, ts timestamp,
                       yhat float8, yhat_lower float8, yhat_upper float8);
                   CREATE TABLE forecast_accuracy (product_id bigint, mae float8, wape_pct float8);""")
    for name, frame in [("demand_forecast", forecast_df), ("forecast_accuracy", acc_df)]:
        buf = io.StringIO()
        frame.to_csv(buf, index=False, header=False)
        buf.seek(0)
        cur.copy_expert(f"COPY {name} FROM STDIN WITH CSV", buf)
    conn.commit()
    print(f"Wrote {len(forecast_df):,} rows to demand_forecast and {len(acc_df)} rows to forecast_accuracy")
    conn.close()


if __name__ == "__main__":
    main()
