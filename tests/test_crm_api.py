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


class TestRanking:
    """GET /crm/ranking (Phase 3 Stage 3)."""

    def _post(self, client, name, website, **extra):
        payload = {"name": name, "website": website}
        payload.update(extra)
        return client.post("/leads", json=payload)

    def test_ranking_empty(self, client):
        resp = client.get("/crm/ranking")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert "ranked" in data
        assert "by_priority" in data

    def test_ranking_returns_sorted_top_leads(self, client):
        # Lead A: strong fit
        self._post(
            client,
            "RankA Co",
            "https://ranka.example.com",
            casting_need_score=90,
            business_type="Manufacturer / OEM",
            buying_signal="HIGH (rfq)",
            lead_score=92,
            priority="HIGH",
        )
        # Lead B: weak fit
        self._post(
            client,
            "RankB Co",
            "https://rankb.example.com",
            casting_need_score=10,
            lead_score=20,
            priority="LOW",
        )
        resp = client.get("/crm/ranking?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        ranked = data["ranked"]
        # Highest score first.
        scores = [l["lead_score"] for l in ranked]
        assert scores == sorted(scores, reverse=True)
        assert ranked[0]["name"] == "RankA Co"

    def test_ranking_min_score_filter(self, client):
        self._post(
            client,
            "RankA Co",
            "https://ranka.example.com",
            lead_score=92,
            priority="HIGH",
        )
        self._post(
            client,
            "RankB Co",
            "https://rankb.example.com",
            lead_score=20,
            priority="LOW",
        )
        resp = client.get("/crm/ranking?min_score=80")
        assert resp.status_code == 200
        data = resp.json()
        names = [l["name"] for l in data["ranked"]]
        assert "RankA Co" in names
        assert "RankB Co" not in names

    def test_ranking_priority_filter(self, client):
        self._post(
            client,
            "RankA Co",
            "https://ranka.example.com",
            lead_score=92,
            priority="HIGH",
        )
        self._post(
            client,
            "RankB Co",
            "https://rankb.example.com",
            lead_score=20,
            priority="LOW",
        )
        resp = client.get("/crm/ranking?priority=LOW")
        assert resp.status_code == 200
        data = resp.json()
        names = [l["name"] for l in data["ranked"]]
        assert "RankB Co" in names
        assert "RankA Co" not in names

    def test_ranking_grouped_by_priority(self, client):
        self._post(
            client,
            "RankA Co",
            "https://ranka.example.com",
            lead_score=92,
            priority="HIGH",
        )
        self._post(
            client,
            "RankB Co",
            "https://rankb.example.com",
            lead_score=20,
            priority="LOW",
        )
        resp = client.get("/crm/ranking")
        data = resp.json()
        assert data["by_priority"]["HIGH"][0]["name"] == "RankA Co"
        assert data["by_priority"]["LOW"][0]["name"] == "RankB Co"

    def test_high_value_sorted_by_lead_score(self, client):
        # Two not-contacted HIGH-priority leads; highest lead_score first.
        self._post(
            client,
            "HV-Low",
            "https://hvlow.example.com",
            sales_priority="HIGH",
            lead_score=30,
            priority="LOW",
            lead_status="new",
        )
        self._post(
            client,
            "HV-High",
            "https://hvhigh.example.com",
            sales_priority="HIGH",
            lead_score=88,
            priority="HIGH",
            lead_status="new",
        )
        resp = client.get("/crm/high-value")
        assert resp.status_code == 200
        names = [l["name"] for l in resp.json()]
        assert names[0] == "HV-High"

