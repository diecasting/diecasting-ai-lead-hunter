"""Tests for CRM API endpoints (pipeline, status update, high-value)."""


class TestCRMPipeline:
    """GET /crm/pipeline."""

    def test_pipeline_empty(self, client):
        resp = client.get("/crm/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "new" in data
        assert "contacted" in data
        assert "customer" in data

    def test_pipeline_groups_by_status(self, client):
        # Create a lead and set its status
        resp = client.post(
            "/leads",
            json={
                "name": "CRMPipe Co",
                "website": "https://crmpipe.example.com",
                "industry": "automotive",
                "lead_status": "qualified",
            },
        )
        lead_id = resp.json()["id"]

        resp = client.get("/crm/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        qualified_ids = [l["id"] for l in data.get("qualified", [])]
        assert lead_id in qualified_ids

    def test_pipeline_filtered_status(self, client):
        resp = client.post(
            "/leads",
            json={
                "name": "CRMFilter Co",
                "website": "https://crmfilter.example.com",
                "industry": "ev",
                "lead_status": "contacted",
            },
        )
        resp = client.get("/crm/pipeline?statuses=contacted,customer")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"contacted", "customer"}


class TestLeadStatusUpdate:
    """PATCH /leads/{id}/status."""

    def test_update_status_valid(self, client):
        resp = client.post(
            "/leads",
            json={"name": "StatusUpd Co", "website": "https://statusupd.example.com"},
        )
        lead_id = resp.json()["id"]

        resp = client.patch(
            f"/leads/{lead_id}/status", json={"lead_status": "qualified"}
        )
        assert resp.status_code == 200
        assert resp.json()["lead_status"] == "qualified"
        assert resp.json()["last_activity_time"] is not None

    def test_update_status_invalid(self, client):
        resp = client.post(
            "/leads",
            json={"name": "StatusInv Co", "website": "https://statusinv.example.com"},
        )
        lead_id = resp.json()["id"]

        # new -> contacted is invalid (must go through qualified/email_generated/approved)
        resp = client.patch(
            f"/leads/{lead_id}/status", json={"lead_status": "contacted"}
        )
        assert resp.status_code == 400

    def test_update_nonexistent_lead(self, client):
        resp = client.patch("/leads/99999/status", json={"lead_status": "qualified"})
        assert resp.status_code == 404

    def test_update_with_next_followup(self, client):
        from datetime import datetime, timezone

        resp = client.post(
            "/leads",
            json={
                "name": "NextFU Co",
                "website": "https://nextfu.example.com",
                "lead_status": "contacted",
            },
        )
        lead_id = resp.json()["id"]

        # contacted -> replied is valid
        fu_date = (datetime.now(timezone.utc) + __import__("datetime").timedelta(days=10)).isoformat()
        resp = client.patch(
            f"/leads/{lead_id}/status",
            json={"lead_status": "replied", "next_followup_date": fu_date},
        )
        assert resp.status_code == 200
        assert resp.json()["lead_status"] == "replied"
        assert resp.json()["next_followup_date"] is not None


class TestHighValue:
    """GET /crm/high-value."""

    def test_high_value_returns_high_not_contacted(self, client):
        # Create HIGH priority, not contacted
        resp = client.post(
            "/leads",
            json={
                "name": "HV1 Co",
                "website": "https://hv1.example.com",
                "industry": "automotive",
                "sales_priority": "HIGH",
                "lead_status": "new",
            },
        )
        # Create HIGH priority but already contacted
        resp2 = client.post(
            "/leads",
            json={
                "name": "HV2 Co",
                "website": "https://hv2.example.com",
                "industry": "ev",
                "sales_priority": "HIGH",
                "lead_status": "contacted",
            },
        )
        # Create MEDIUM priority
        resp3 = client.post(
            "/leads",
            json={
                "name": "HV3 Co",
                "website": "https://hv3.example.com",
                "industry": "cnc machining",
                "sales_priority": "MEDIUM",
                "lead_status": "new",
            },
        )

        resp = client.get("/crm/high-value")
        assert resp.status_code == 200
        data = resp.json()
        names = [l["name"] for l in data]
        assert "HV1 Co" in names
        assert "HV2 Co" not in names  # already contacted
        assert "HV3 Co" not in names  # MEDIUM priority

    def test_high_value_empty(self, client):
        resp = client.get("/crm/high-value")
        assert resp.status_code == 200
        # Just ensure it returns a list
        assert isinstance(resp.json(), list)
