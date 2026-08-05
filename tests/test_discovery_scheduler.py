"""Phase 5 Stage 3 — Discovery Scheduler and Lead Qualification tests.

Covers:
  * scheduler creation      — POST /discovery/schedules (+ validation)
  * schedule execution      — run_schedule creates a linked job, updates
                              last_run / next_run, tracks progress
  * qualification rules     — qualifying discoveries auto-add to the CRM;
                              low score / missing signals do not qualify
  * duplicate prevention    — re-running a schedule never duplicates leads
  * due-schedule detection  — run_due_schedules picks enabled+due only
  * schedule CRUD API       — PATCH enable/disable, DELETE
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.crawler.website_crawler import CrawlResult
from app.discovery import scheduler as discovery_scheduler
from app.discovery.analyzer import analyze_website
from app.discovery.qualify import qualification_rules_pass
from app.models.discovery_schedule import DiscoverySchedule

SAMPLE_HTML = """
Acme Castings GmbH is a contract manufacturer of precision aluminum and
ADC12 die-cast components for the automotive and aerospace industries.
We specialize in high pressure die casting, gravity casting, cnc machining
and in-house tooling. We are looking for suppliers for a new EV motor
housing program and currently sourcing die-cast housings; request for
quotation (RFQ) is open. Production capability: custom parts, made to order.
"""


class _FakeCrawler:
    def crawl(self, url: str) -> CrawlResult:
        return CrawlResult(url=url, text_content=SAMPLE_HTML, pages_crawled=1)


def _urls(n: int, prefix: str = "https://sch-{}.example.com") -> list:
    return [prefix.format(i) for i in range(1, n + 1)]


def _make_schedule(db, **kw):
    defaults = dict(keyword="automotive aluminum die casting Germany")
    defaults.update(kw)
    return discovery_scheduler.create_schedule(db, **defaults)


def _run(db, schedule, urls=None):
    return discovery_scheduler.run_schedule(
        db, schedule,
        resolver=lambda kw: urls or _urls(4),
        crawler=_FakeCrawler(),
    )


# ---------------------------------------------------------------------------
# Qualification rules (unit)
# ---------------------------------------------------------------------------
def test_qualification_rules_pass_for_complete_discovery(db):
    disc = analyze_website(
        "https://qualify.example.com", crawler=_FakeCrawler()
    )
    from app.discovery import crud as discovery_crud

    row = discovery_crud.create(
        db, company_name=disc.company_name, website=disc.url,
        detected_materials=", ".join(disc.detected_materials),
        detected_processes=", ".join(disc.detected_processes),
        buying_signals="; ".join(disc.buying_signals),
        confidence_score=disc.confidence_score,
        lead_score=disc.lead_score,
        profile=disc.to_profile_json(),
    )
    ok, reason = qualification_rules_pass(row)
    assert ok is True
    assert reason == ""


def test_qualification_blocks_missing_process_or_signal(db):
    from app.discovery import crud as discovery_crud

    no_process = discovery_crud.create(
        db, company_name="No Process Co", website="https://nop.example.com",
        buying_signals="rfq", confidence_score=90, lead_score=80,
    )
    ok, reason = qualification_rules_pass(no_process)
    assert ok is False
    assert "process" in reason

    no_signal = discovery_crud.create(
        db, company_name="No Signal Co", website="https://nos.example.com",
        detected_processes="die casting", confidence_score=90, lead_score=80,
    )
    ok, reason = qualification_rules_pass(no_signal)
    assert ok is False
    assert "buying signal" in reason


# ---------------------------------------------------------------------------
# Scheduler module
# ---------------------------------------------------------------------------
def test_create_schedule_defaults(db):
    s = _make_schedule(db)
    assert s.keyword == "automotive aluminum die casting Germany"
    assert s.frequency == "daily"
    assert s.enabled is True
    assert s.lead_score_threshold == 50
    assert s.confidence_threshold == 40
    assert s.next_run is not None  # due immediately when enabled


def test_schedule_execution_tracks_run_and_history(db):
    s = _make_schedule(db)
    report = _run(db, s)
    assert report["progress"]["total"] == 4
    assert report["progress"]["success"] == 4
    assert report["job_id"] is not None

    db.refresh(s)
    assert s.last_run is not None
    assert s.next_run is not None
    assert s.next_run > s.last_run  # advanced by the frequency
    # Execution history: the schedule owns the job.
    assert [j.id for j in s.jobs] == [report["job_id"]]
    assert s.jobs[0].schedule_id == s.id


def test_schedule_execution_qualifies_and_adds_to_crm(db):
    s = _make_schedule(db)  # defaults 50/40; sample scores 75/90
    report = _run(db, s)
    assert len(report["qualified"]) == 4
    assert len(report["added"]) == 4
    assert report["not_qualified"] == []
    assert len(s.jobs[0].tasks) == 4

    # Every analysed discovery now points at a CRM lead (lead_source=discovery).
    from app.crud import leads as leads_crud

    for task in s.jobs[0].tasks:
        assert task.discovery.lead_id is not None
        lead = leads_crud.get(db, task.discovery.lead_id)
        assert lead.lead_source == "discovery"


def test_qualification_threshold_blocks_low_scores(db):
    s = _make_schedule(db, lead_score_threshold=200)  # unreachable
    report = _run(db, s)
    assert report["qualified"] == []
    assert len(report["not_qualified"]) == 4
    assert "below threshold" in report["not_qualified"][0]["reason"]


def test_duplicate_prevention_on_second_run(db):
    s = _make_schedule(db)
    first = _run(db, s, urls=_urls(3))
    assert len(first["added"]) == 3

    # Second run: same URLs — all already known (discoveries + leads exist).
    second = _run(db, s, urls=_urls(3))
    db.refresh(s)
    assert second["progress"]["skipped"] == 3
    assert second["added"] == []  # no new leads created
    # Lead count unchanged.
    from app.crud import leads as leads_crud

    disc_leads = [
        l for l in leads_crud.get_multi(db, limit=500)
        if l.lead_source == "discovery"
    ]
    assert len(disc_leads) == 3


def test_run_due_schedules_picks_enabled_and_due(db):
    due = _make_schedule(db, keyword="due keyword")
    due.next_run = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add(due)
    db.commit()

    disabled = _make_schedule(db, keyword="disabled keyword", enabled=False)
    disabled.next_run = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add(disabled)
    db.commit()

    future = _make_schedule(db, keyword="future keyword")
    future.next_run = datetime.now(timezone.utc) + timedelta(days=1)
    db.add(future)
    db.commit()

    report = discovery_scheduler.run_due_schedules(
        db, resolver=lambda kw: _urls(2), crawler=_FakeCrawler()
    )
    assert report["schedules_due"] == 1
    assert report["runs"][0]["schedule_id"] == due.id


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_api_create_and_list_schedules(client: TestClient):
    r = client.post(
        "/discovery/schedules",
        json={"keyword": "zinc die casting Poland", "frequency": "weekly"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["keyword"] == "zinc die casting Poland"
    assert body["frequency"] == "weekly"
    assert body["enabled"] is True
    assert body["next_run"] is not None

    listed = client.get("/discovery/schedules").json()
    assert any(s["id"] == body["id"] for s in listed)


def test_api_create_schedule_validation(client: TestClient):
    assert client.post("/discovery/schedules", json={"keyword": "  "}).status_code == 422
    r = client.post("/discovery/schedules", json={"keyword": "x", "frequency": "hourly"})
    assert r.status_code == 422
    assert "frequency" in r.json()["detail"]


def test_api_schedule_crud(client: TestClient, monkeypatch):
    from app.discovery import queue as q
    from app.discovery.analyzer import analyze_website as real_analyze

    monkeypatch.setattr(
        "app.discovery.queue._resolve_urls", lambda db, keyword, **kw: _urls(3)
    )
    monkeypatch.setattr(
        "app.discovery.queue.analyze_website",
        lambda url, **kw: real_analyze(url, crawler=_FakeCrawler()),
    )

    created = client.post("/discovery/schedules", json={"keyword": "crud schedule"}).json()
    sid = created["id"]

    # Run now -> job + auto-qualification.
    run = client.post(f"/discovery/schedules/{sid}/run")
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert run.json()["success"] == 3

    # History lists the job.
    history = client.get(f"/discovery/schedules/{sid}/history").json()
    assert len(history) == 1
    assert history[0]["id"] == run.json()["id"]

    # Disable + re-enable.
    off = client.patch(f"/discovery/schedules/{sid}", json={"enabled": False}).json()
    assert off["enabled"] is False
    on = client.patch(f"/discovery/schedules/{sid}", json={"enabled": True}).json()
    assert on["enabled"] is True

    # Delete.
    assert client.delete(f"/discovery/schedules/{sid}").status_code == 204
    assert client.get(f"/discovery/schedules/{sid}/history").status_code == 404
