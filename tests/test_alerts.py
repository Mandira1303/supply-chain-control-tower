"""Unit tests for the alert rules. Run from the repo root:  python -m pytest tests -v"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "airflow", "dags"))
import alerts  # noqa: E402

T = dict(alerts.DEFAULT_THRESHOLDS)
HEALTHY = {"stockout_rate_24h_pct": 5.0, "on_time_delivery_7d_pct": 90.0, "avg_lead_time_7d_hours": 30.0,
           "critical_stock_items": 3, "demand_spikes_latest_hour": 0}


def names(fired):
    return {a["alert_name"] for a in fired}


def test_no_alerts_when_all_kpis_healthy():
    assert alerts.evaluate(HEALTHY, T) == []


def test_stockout_above_threshold_is_critical():
    fired = alerts.evaluate({**HEALTHY, "stockout_rate_24h_pct": 20.0}, T)
    assert names(fired) == {"stockout_rate_24h_pct"}
    assert fired[0]["severity"] == "critical"


def test_on_time_delivery_fires_when_below():
    assert names(alerts.evaluate({**HEALTHY, "on_time_delivery_7d_pct": 40.0}, T)) == {"on_time_delivery_7d_pct"}


def test_value_equal_to_threshold_does_not_fire_for_above_rules():
    assert alerts.evaluate({**HEALTHY, "stockout_rate_24h_pct": T["stockout_rate_24h_pct"]}, T) == []


def test_one_demand_spike_fires():
    assert names(alerts.evaluate({**HEALTHY, "demand_spikes_latest_hour": 1}, T)) == {"demand_spikes_latest_hour"}


def test_missing_kpi_is_ignored():
    assert alerts.evaluate({**HEALTHY, "avg_lead_time_7d_hours": None}, T) == []


def test_several_breaches_fire_together():
    kpis = {**HEALTHY, "stockout_rate_24h_pct": 30.0, "critical_stock_items": 52}
    assert names(alerts.evaluate(kpis, T)) == {"stockout_rate_24h_pct", "critical_stock_items"}


def test_message_contains_value_and_threshold():
    msg = alerts.evaluate({**HEALTHY, "critical_stock_items": 52}, T)[0]["message"]
    assert "52" in msg and "25" in msg


def test_threshold_can_be_changed_with_env(monkeypatch):
    monkeypatch.setenv("ALERT_STOCKOUT_RATE_24H_PCT", "25")
    assert alerts.get_thresholds()["stockout_rate_24h_pct"] == 25.0


def test_no_slack_or_email_sent_when_not_configured(monkeypatch):
    for k in ("SLACK_WEBHOOK_URL", "SMTP_HOST", "ALERT_EMAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    a = {"alert_name": "x", "severity": "info", "message": "m"}
    assert alerts.send_slack(a) is False and alerts.send_email(a) is False
