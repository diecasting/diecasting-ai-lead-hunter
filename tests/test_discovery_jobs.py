"""Phase 5 Stage 2 — Batch Lead Discovery Queue tests.

Covers:
  * queue creation          — POST /discovery/jobs returns a pending job
  * processing             — run_job resolves URLs, analyses each, tracks
                             progress (total/processed/success/failed/skipped)
  * status updates         — pending -> running -> completed; per-task states
  * 50-URL batch           — a full 50-URL job completes with accurate counts
  * duplicate handling     — URLs already in the CRM / prior discoveries are
                             skipped, not re-analysed
  * failed website handling— a crawling/analysis failure marks the task failed
                             and the job still completes
  * CRM integration        — discoveries produced by a job can be bulk-added
                             to the CRM via POST /discovery/{id}/lead
"""
from fastapi.testclient import TestClient

from app.crawler.website_crawler import CrawlResult
from app.discovery import queue as discovery_queue
from app.discovery.analyzer import analyze_website

SAMPLE_HTML = """
Acme Castings GmbH is a contract manufacturer of precision aluminum and
ADC12 die-cast components for the automotive and aerospace industries.
We specialize in high pressure die casting, gravity casting, cnc machining
and in-house tooling. We are looking for suppliers for a new EV motor
housing program and currently sourcing die-cast housings; request for
quotation (RFQ) is open. Production capability: custom parts, made to order.
"""


class _FakeCrawler:
    """Crawler that returns sample text for every URL (or fails on demand)."""

    def __init__(self, fail_urls: set = None):
        self.fail_urls = fail_urls or set()

    def crawl(self, url: str) -> CrawlResult:
        if url in self.fail_urls:
            raise RuntimeError("simulated crawl failure")
        return CrawlResult(url=url, text_content=SAMPLE_HTML, pages_crawled=1)


def _make_urls(n: int, prefix: str = "https://batch-{}.example.com") -> list:
    return [prefix.format(i) for i in range(1, n + 1)]


# ---------------------------------------------------------------------------
# Queue module (offline)
# ---------------------------------------------------------------------------
def test_create_job_pending(db):
    job = discovery_queue.create_job(db, "automotive aluminum die casting supplier Germany")
    assert job.id
    assert job.status == "pending"
    assert job.keyword == "automotive aluminum die casting supplier Germany"
    assert job.total_urls == 0
    assert job.processed_urls == 0


def test_run_job_processes_urls_and_tracks_progress(db):
    job = discovery_queue.create_job(db, "die casting suppliers")
    urls = _make_urls(5)
    progress = discovery_queue.run_job(
        db, job, resolver=lambda kw: urls, crawler=_FakeCrawler()
    )
    assert progress == {
        "total": 5, "processed": 5, "success": 5, "failed": 0, "skipped": 0,
    }
    db.refresh(job)
    assert job.status == "completed"
    assert job.total_urls == 5
    assert job.processed_urls == 5
    assert job.completed_at is not None
    # Every task analysed with a linked discovery.
    for task in job.tasks:
        assert task.status == "analyzed"
        assert task.discovery_id is not None
        assert task.discovery.company_name


def test_run_job_50_url_batch(db):
    job = discovery_queue.create_job(db, "aluminum die casting Germany")
    urls = _make_urls(50)
    progress = discovery_queue.run_job(
        db, job, resolver=lambda kw: urls, crawler=_FakeCrawler()
    )
    assert progress["total"] == 50
    assert progress["processed"] == 50
    assert progress["success"] == 50
    assert progress["failed"] == 0
    assert progress["skipped"] == 0
    db.refresh(job)
    assert job.status == "completed"
    assert len(job.tasks) == 50


def test_run_job_duplicate_urls_skipped(db):
    # Pre-existing lead with one of the candidate URLs.
    from app.crud import leads as leads_crud

    known_url = "https://batch-2.example.com"
    leads_crud.create(db, name="Known Co", website=known_url)

    job = discovery_queue.create_job(db, "die casting suppliers")
    urls = _make_urls(4)
    progress = discovery_queue.run_job(
        db, job, resolver=lambda kw: urls, crawler=_FakeCrawler()
    )
    assert progress["success"] == 3
    assert progress["skipped"] == 1
    db.refresh(job)
    dup_task = next(t for t in job.tasks if t.url == known_url)
    assert dup_task.status == "skipped"
    assert "duplicate" in dup_task.error_message
    assert dup_task.discovery_id is None


def test_run_job_intra_batch_duplicate_deduped(db):
    """A URL repeated inside the same batch resolves to a single task.

    URL dedup happens at resolve time, so the duplicate never produces a
    second task or a second analysis.
    """
    job = discovery_queue.create_job(db, "die casting suppliers")
    urls = [
        "https://dup.example.com",
        "https://dup.example.com",
        "https://ok.example.com",
    ]
    progress = discovery_queue.run_job(
        db, job, resolver=lambda kw: urls, crawler=_FakeCrawler()
    )
    assert progress == {
        "total": 2, "processed": 2, "success": 2, "failed": 0, "skipped": 0,
    }
    db.refresh(job)
    assert len(job.tasks) == 2


def test_run_job_failed_website_handled(db):
    failing = "https://batch-3.example.com"
    job = discovery_queue.create_job(db, "die casting suppliers")
    progress = discovery_queue.run_job(
        db, job,
        resolver=lambda kw: _make_urls(4),
        crawler=_FakeCrawler(fail_urls={failing}),
    )
    assert progress["success"] == 3
    assert progress["failed"] == 1
    db.refresh(job)
    assert job.status == "completed"  # per-URL failure does not fail the job
    failed_task = next(t for t in job.tasks if t.url == failing)
    assert failed_task.status == "failed"
    assert "simulated crawl failure" in failed_task.error_message


def test_run_job_resolver_failure_marks_job_failed(db):
    job = discovery_queue.create_job(db, "die casting suppliers")

    def boom(keyword):
        raise RuntimeError("search backend down")

    progress = discovery_queue.run_job(db, job, resolver=boom, crawler=_FakeCrawler())
    db.refresh(job)
    assert job.status == "failed"
    assert progress["error"]
    assert "search backend down" in progress["error"]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _patch_job_pipeline(monkeypatch):
    """Make the jobs API run offline: fixed URL resolver + fake crawler.

    Patches the module-internal helpers (not run_job itself) so the real
    queue orchestration, progress tracking and persistence are exercised.
    """
    from app.discovery.analyzer import analyze_website as real_analyze

    def fake_resolve(db, keyword, **kwargs):
        return _make_urls(3)

    def fake_analyze(url, **kwargs):
        return real_analyze(url, crawler=_FakeCrawler())

    monkeypatch.setattr("app.discovery.queue._resolve_urls", fake_resolve)
    monkeypatch.setattr("app.discovery.queue.analyze_website", fake_analyze)


def test_api_create_and_run_job(client: TestClient, monkeypatch):
    _patch_job_pipeline(monkeypatch)
    r = client.post("/discovery/jobs", json={"keyword": "automotive aluminum die casting Germany"})
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    # Pending before run.
    before = client.get(f"/discovery/jobs/{job_id}").json()
    assert before["status"] == "pending"
    assert before["total"] == 0

    # Run -> completed with progress + tasks.
    run = client.post(f"/discovery/jobs/{job_id}/run")
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["total"] == 3
    assert body["processed"] == 3
    assert body["success"] == 3
    assert body["failed"] == 0
    assert body["skipped"] == 0
    assert len(body["tasks"]) == 3
    assert body["tasks"][0]["status"] == "analyzed"
    assert body["tasks"][0]["company_name"]
    assert body["tasks"][0]["discovery_id"] is not None

    # GET reflects the same progress.
    after = client.get(f"/discovery/jobs/{job_id}").json()
    assert after["success"] == 3


def test_api_create_job_requires_keyword(client: TestClient):
    assert client.post("/discovery/jobs", json={}).status_code == 422
    r = client.post("/discovery/jobs", json={"keyword": "   "})
    assert r.status_code == 422


def test_api_job_404(client: TestClient):
    assert client.get("/discovery/jobs/999999").status_code == 404
    assert client.post("/discovery/jobs/999999/run").status_code == 404


def test_api_crm_integration_after_job(client: TestClient, monkeypatch):
    """Discoveries produced by a job are bulk-addable to the CRM."""
    _patch_job_pipeline(monkeypatch)
    job_id = client.post("/discovery/jobs", json={"keyword": "die casting suppliers"}).json()["job_id"]
    body = client.post(f"/discovery/jobs/{job_id}/run").json()

    added = 0
    for task in body["tasks"]:
        r = client.post(f"/discovery/{task['discovery_id']}/lead")
        assert r.status_code == 201
        assert r.json()["lead_source"] == "discovery"
        added += 1
    assert added == 3

    # Re-adding the same discoveries is rejected (409) — CRM dedup intact.
    task = body["tasks"][0]
    again = client.post(f"/discovery/{task['discovery_id']}/lead")
    assert again.status_code == 409


def test_api_existing_outreach_workflow_unchanged(client: TestClient, monkeypatch):
    """Generating + sending an email still works after a discovery job."""
    _patch_job_pipeline(monkeypatch)
    job_id = client.post("/discovery/jobs", json={"keyword": "die casting suppliers"}).json()["job_id"]
    body = client.post(f"/discovery/jobs/{job_id}/run").json()
    task = body["tasks"][0]
    lead = client.post(f"/discovery/{task['discovery_id']}/lead").json()
    lead_id = lead["id"]

    # Discovered leads have no extracted email; set one before generating so
    # the draft captures a recipient and the send gate can pass.
    client.patch(f"/leads/{lead_id}", json={"contact_email": "buyer@discovered.example.com"})
    gen = client.post(f"/leads/{lead_id}/generate-email")
    assert gen.status_code == 201
    message_id = gen.json()["id"]

    client.patch(f"/outreach/drafts/{message_id}/gate", json={"gate_status": "ready"})
    s = client.post(f"/outreach/drafts/{message_id}/send")
    assert s.status_code == 200
    assert s.json()["success"] is True

    # The discovery link survived: discovery.lead_id points at the CRM lead.
    disc = client.get("/discovery").json()
    mine = [d for d in disc if d["id"] == task["discovery_id"]][0]
    assert mine["lead_id"] == lead_id
