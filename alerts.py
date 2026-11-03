"""
KPI alerting for the Retail & Supply Chain Control Tower.
Runs after every hourly ingest. Every breach is written to the `alerts` table (always).
If SLACK_WEBHOOK_URL and/or SMTP settings are provided, the alert is also sent there.
All thresholds can be changed with environment variables (see docker-compose.yml).
"""
import os
import json
import smtplib
import urllib.request
from email.message import EmailMessage

DEFAULT_THRESHOLDS = {
    "stockout_rate_24h_pct": 15.0,     # alert if above
    "on_time_delivery_7d_pct": 55.0,   # alert if below
    "avg_lead_time_7d_hours": 48.0,    # alert if above
    "critical_stock_items": 25,        # alert if more items than this have < 1 day of stock
    "demand_spikes_latest_hour": 1,    # alert if at least this many spikes in the latest hour
}

KPI_SQL = {
    "stockout_rate_24h_pct": """SELECT ROUND(100.0 * AVG(CASE WHEN is_stockout THEN 1 ELSE 0 END)::numeric, 2)
        FROM inventory_hourly WHERE ts > (SELECT MAX(ts) FROM inventory_hourly) - INTERVAL '24 hours'""",
    "on_time_delivery_7d_pct": """SELECT ROUND(100.0 * AVG(CASE WHEN on_time THEN 1 ELSE 0 END)::numeric, 2)
        FROM shipments WHERE delivered_ts > (SELECT MAX(ts) FROM inventory_hourly) - INTERVAL '7 days'""",
    "avg_lead_time_7d_hours": """SELECT ROUND(AVG(lead_time_hours)::numeric, 1)
        FROM shipments WHERE delivered_ts > (SELECT MAX(ts) FROM inventory_hourly) - INTERVAL '7 days'""",
    "critical_stock_items": """SELECT COUNT(*) FROM kpi_days_of_inventory WHERE days_of_inventory < 1""",
    "demand_spikes_latest_hour": """WITH latest AS (SELECT MAX(ts) AS ts FROM inventory_hourly),
        base AS (SELECT store_id, product_id, AVG(units_sold) AS avg_sold FROM inventory_hourly, latest
                 WHERE inventory_hourly.ts > latest.ts - INTERVAL '7 days' GROUP BY 1, 2)
        SELECT COUNT(*) FROM inventory_hourly i JOIN latest l ON i.ts = l.ts
        JOIN base b ON b.store_id = i.store_id AND b.product_id = i.product_id
        WHERE i.units_sold >= 5 AND i.units_sold > 5 * b.avg_sold""",
}

# direction: "above" fires when value > threshold, "below" fires when value < threshold
RULES = {
    "stockout_rate_24h_pct": ("above", "Stock-out rate (last 24h) is {value}% - threshold {threshold}%", "critical"),
    "on_time_delivery_7d_pct": ("below", "On-time delivery (last 7 days) is {value}% - threshold {threshold}%", "warning"),
    "avg_lead_time_7d_hours": ("above", "Average supplier lead time (last 7 days) is {value}h - threshold {threshold}h", "warning"),
    "critical_stock_items": ("above", "{value} store-products have under 1 day of stock - threshold {threshold}", "critical"),
    "demand_spikes_latest_hour": ("above_eq", "{value} demand spike(s) detected in the latest hour", "info"),
}


def get_thresholds():
    t = dict(DEFAULT_THRESHOLDS)
    for k in t:
        env = os.getenv("ALERT_" + k.upper())
        if env:
            t[k] = float(env)
    return t


def evaluate(kpis, thresholds):
    """Pure function: returns a list of alert dicts for every KPI that breaches its threshold."""
    alerts = []
    for name, value in kpis.items():
        if value is None:
            continue
        direction, template, severity = RULES[name]
        thr = thresholds[name]
        fired = (direction == "above" and value > thr) or \
                (direction == "below" and value < thr) or \
                (direction == "above_eq" and value >= thr)
        if fired:
            alerts.append({"alert_name": name, "severity": severity, "value": float(value),
                           "threshold": float(thr), "message": template.format(value=value, threshold=thr)})
    return alerts


def send_slack(alert):
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return False
    body = json.dumps({"text": f":rotating_light: [{alert['severity'].upper()}] {alert['message']}"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)
    return True


def send_email(alert):
    host, to = os.getenv("SMTP_HOST"), os.getenv("ALERT_EMAIL_TO")
    if not (host and to):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[{alert['severity'].upper()}] Supply chain alert: {alert['alert_name']}"
    msg["From"] = os.getenv("SMTP_USER", "alerts@localhost")
    msg["To"] = to
    msg.set_content(alert["message"])
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as s:
        s.starttls()
        if os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"):
            s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
        s.send_message(msg)
    return True


def run():
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("SC_DB_HOST", "host.docker.internal"), port=int(os.getenv("SC_DB_PORT", "5432")),
        user=os.getenv("SC_DB_USER", "postgres"), password=os.environ["SC_DB_PASSWORD"],
        dbname=os.getenv("SC_DB_NAME", "supply_chain"))
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id serial PRIMARY KEY, created_at timestamptz DEFAULT now(), data_ts timestamp,
        alert_name text, severity text, message text, value float8, threshold float8, notified boolean)""")
    cur.execute("SELECT MAX(ts) FROM inventory_hourly")
    data_ts = cur.fetchone()[0]
    kpis = {}
    for name, sql in KPI_SQL.items():
        cur.execute(sql)
        v = cur.fetchone()[0]
        kpis[name] = None if v is None else float(v)
    fired = evaluate(kpis, get_thresholds())
    for a in fired:
        # only notify Slack/email if the same alert was not already sent in the last 6 hours
        cur.execute("SELECT 1 FROM alerts WHERE alert_name = %s AND notified AND created_at > now() - INTERVAL '6 hours'",
                    (a["alert_name"],))
        already = cur.fetchone() is not None
        notified = False
        if not already:
            for sender in (send_slack, send_email):
                try:
                    notified = sender(a) or notified
                except Exception as exc:                      # a failed notification must not fail the pipeline
                    print(f"Notification failed ({sender.__name__}): {exc}")
        cur.execute("INSERT INTO alerts (data_ts, alert_name, severity, message, value, threshold, notified) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (data_ts, a["alert_name"], a["severity"], a["message"], a["value"], a["threshold"], notified))
        print(f"ALERT [{a['severity']}] {a['message']}")
    conn.commit()
    conn.close()
    print(f"KPIs: {kpis} | alerts fired: {len(fired)}")
    return kpis
