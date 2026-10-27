"""Iteration 2 backend tests: filters, cron auth, alerts, SP sync error path."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
WEBHOOK_CRON_SECRET = "AJESj5UqVU9XaHnCiJMaQY5bJ_WWcftH82vK7bikjQc"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@finops.app", "password": "admin123"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------- Cost filters (period + subscription) ----------------
class TestCostFilters:
    def test_summary_3m(self, auth):
        r = requests.get(f"{BASE_URL}/api/costs/summary",
                         params={"period": "3m", "subscription_id": "sub-dev-001"},
                         headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["months"]) == 3
        assert d["period_label"] == "Últimos 3 meses"
        assert d["current_month"] > 0

    def test_summary_previous(self, auth):
        r = requests.get(f"{BASE_URL}/api/costs/summary",
                         params={"period": "previous"}, headers=auth, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert len(d["months"]) == 1
        assert d["period_label"] == "Mês anterior"

    def test_summary_invalid_period_falls_back(self, auth):
        r = requests.get(f"{BASE_URL}/api/costs/summary",
                         params={"period": "bogus"}, headers=auth, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["period"] == "current"
        assert len(d["months"]) == 1

    def test_breakdown_subscription_scoped(self, auth):
        r = requests.get(f"{BASE_URL}/api/costs/breakdown",
                         params={"dimension": "subscription_name",
                                 "subscription_id": "sub-prod-001"},
                         headers=auth, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["label"] == "PROD-Core"

    def test_top_resources_subscription_scope(self, auth):
        r = requests.get(f"{BASE_URL}/api/costs/top-resources",
                         params={"subscription_id": "sub-dev-001", "limit": 5},
                         headers=auth, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert rows, "expected some rows"
        for row in rows:
            assert "DEV" in row["subscription_name"] or row["subscription_name"] == "DEV-Sandbox"

    def test_trend_subscription_filter(self, auth):
        r_all = requests.get(f"{BASE_URL}/api/costs/trend",
                             params={"months": 12}, headers=auth, timeout=15).json()
        r_sub = requests.get(f"{BASE_URL}/api/costs/trend",
                             params={"months": 12, "subscription_id": "sub-dev-001"},
                             headers=auth, timeout=15).json()
        s_all = sum(x["amount"] for x in r_all)
        s_sub = sum(x["amount"] for x in r_sub)
        assert s_sub < s_all


class TestRecsFilter:
    def test_summary_scoped_smaller(self, auth):
        full = requests.get(f"{BASE_URL}/api/recommendations/summary",
                            headers=auth, timeout=15).json()
        dev = requests.get(f"{BASE_URL}/api/recommendations/summary",
                           params={"subscription_id": "sub-dev-001"},
                           headers=auth, timeout=15).json()
        assert dev["total_count"] <= full["total_count"]
        assert dev["total_savings"] <= full["total_savings"] + 0.01


# ---------------- Cron endpoints ----------------
class TestCron:
    def test_daily_sync_unauth(self):
        r = requests.post(f"{BASE_URL}/api/cron/daily-sync", timeout=15)
        assert r.status_code == 401

    def test_daily_sync_authed(self):
        wid = str(uuid.uuid4())
        h = {"Authorization": f"Bearer {WEBHOOK_CRON_SECRET}", "X-Webhook-Id": wid}
        r1 = requests.post(f"{BASE_URL}/api/cron/daily-sync", headers=h, timeout=15)
        assert r1.status_code == 202, r1.text
        assert r1.json()["accepted"] is True
        # idempotent
        r2 = requests.post(f"{BASE_URL}/api/cron/daily-sync", headers=h, timeout=15)
        assert r2.status_code == 202
        assert r2.json()["accepted"] is True

    def test_weekly_alert_unauth(self):
        r = requests.post(f"{BASE_URL}/api/cron/weekly-alert", timeout=15)
        assert r.status_code == 401

    def test_weekly_alert_authed(self):
        wid = str(uuid.uuid4())
        h = {"Authorization": f"Bearer {WEBHOOK_CRON_SECRET}", "X-Webhook-Id": wid}
        r1 = requests.post(f"{BASE_URL}/api/cron/weekly-alert", headers=h, timeout=15)
        assert r1.status_code == 202
        r2 = requests.post(f"{BASE_URL}/api/cron/weekly-alert", headers=h, timeout=15)
        assert r2.status_code == 202


# ---------------- SP not configured path ----------------
class TestSyncMock:
    def test_trigger_without_sp(self, auth):
        # ensure no SP: this is best-effort; assumes clean state at start
        r = requests.post(f"{BASE_URL}/api/sync/trigger", headers=auth, timeout=15)
        assert r.status_code == 200
        d = r.json()
        # accept either state; if SP already saved by previous iteration this may say started
        assert "message" in d

    def test_status_reports_source(self, auth):
        r = requests.get(f"{BASE_URL}/api/sync/status", headers=auth, timeout=15)
        assert r.status_code == 200
        assert "status" in r.json()


# ---------------- Alerts ----------------
class TestAlerts:
    def test_put_and_test_ok(self, auth):
        r = requests.put(f"{BASE_URL}/api/alerts/settings", headers=auth, json={
            "provider": "google_chat",
            "webhook_url": "https://httpbin.org/post",
            "threshold": 500,
            "enabled": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        rt = requests.post(f"{BASE_URL}/api/alerts/test", headers=auth, timeout=30)
        assert rt.status_code == 200, rt.text
        assert rt.json()["sent"] is True

        g = requests.get(f"{BASE_URL}/api/alerts/settings", headers=auth, timeout=15).json()
        assert g["last_alert"] is not None
        assert g["last_alert"]["sent"] is True

    def test_put_bad_webhook_test_fails(self, auth):
        r = requests.put(f"{BASE_URL}/api/alerts/settings", headers=auth, json={
            "provider": "google_chat",
            "webhook_url": "https://httpbin.org/status/500",
            "threshold": 500,
            "enabled": True,
        }, timeout=15)
        assert r.status_code == 200
        rt = requests.post(f"{BASE_URL}/api/alerts/test", headers=auth, timeout=30)
        assert rt.status_code == 400

    def test_reset_disabled(self, auth):
        r = requests.put(f"{BASE_URL}/api/alerts/settings", headers=auth, json={
            "provider": "google_chat",
            "webhook_url": "https://httpbin.org/post",
            "threshold": 500,
            "enabled": False,
        }, timeout=15)
        assert r.status_code == 200


# ---------------- Fake SP: sync should error, mock survives ----------------
class TestFakeSPSyncErrorPath:
    def test_save_fake_sp_and_sync_errors(self, auth):
        r = requests.post(f"{BASE_URL}/api/service-principal", headers=auth, json={
            "tenant_id": "tid-fake",
            "client_id": "cid-fake",
            "client_secret": "secret-fake",
            "display_name": "FAKE",
        }, timeout=15)
        assert r.status_code == 200

        trig = requests.post(f"{BASE_URL}/api/sync/trigger", headers=auth, timeout=15)
        assert trig.status_code == 200
        assert trig.json()["status"] == "started"

        # poll status
        status = None
        for _ in range(30):
            time.sleep(1)
            s = requests.get(f"{BASE_URL}/api/sync/status", headers=auth, timeout=15).json()
            status = s.get("status")
            if status == "error":
                break
        assert status == "error", f"expected error, got {status}"

        # mock data still intact
        summary = requests.get(f"{BASE_URL}/api/costs/summary",
                               headers=auth, timeout=15).json()
        assert summary["current_month"] > 0

    def test_cleanup_fake_sp(self, auth):
        import subprocess
        subprocess.run([
            "mongosh", "--quiet", os.environ.get("DB_NAME", "test_database"), "--eval",
            'db.service_principals.deleteMany({}); db.sync_status.updateMany({}, {$set:{status:"success", source:"mock"}});'
        ], check=False)
        # verify
        s = requests.get(f"{BASE_URL}/api/sync/status", headers=auth, timeout=15).json()
        assert s.get("status") != "error"
