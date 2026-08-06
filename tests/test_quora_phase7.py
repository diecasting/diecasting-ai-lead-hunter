"""Phase 7 — Quora + SEO Authority Engine tests.

Hermetic: uses the shared in-memory ``client`` / ``db`` fixtures (no network,
no OpenAI). Search-driven discovery is exercised with an injected resolver, and
answer generation is verified against its deterministic (no-key) path.
"""
import os

import pytest

from app.config import settings
from app.models.quora import ContentArticle, QuoraQuestion
from app.quora import answer_generator as answer_mod
from app.quora import content_db as content_mod
from app.quora import crud as qcrud
from app.quora import discovery as discovery_mod
from app.quora import seo as seo_mod
from app.quora import workflow as workflow_mod


# ---------------------------------------------------------------------------
# Unit: workflow state machine
# ---------------------------------------------------------------------------
def test_question_transition_valid():
    assert workflow_mod.validate_question_transition("new", "drafted") == "drafted"
    assert workflow_mod.validate_question_transition("drafted", "published") == "published"


def test_question_transition_invalid():
    with pytest.raises(ValueError):
        workflow_mod.validate_question_transition("new", "not_a_status")
    with pytest.raises(ValueError):
        workflow_mod.validate_question_transition("published", "research")  # typo


def test_answer_transition_valid_and_invalid():
    assert workflow_mod.validate_answer_transition("draft", "review") == "review"
    with pytest.raises(ValueError):
        workflow_mod.validate_answer_transition("exported", "research")  # not allowed


# ---------------------------------------------------------------------------
# Unit: content database ranking
# ---------------------------------------------------------------------------
def test_rank_content_for_query_orders_by_topic(db):
    qcrud.create_article(
        db, title="Porosity in HPDC", body_markdown="Porosity control in die casting.",
        topic="die casting", tags="porosity, defects",
    )
    qcrud.create_article(
        db, title="CNC toolpath basics", body_markdown="Toolpaths for milling.",
        topic="cnc", tags="toolpath",
    )
    ranked = content_mod.rank_content_for_query(db, "die casting porosity", topic="die casting")
    assert ranked, "expected at least one match"
    assert ranked[0].topic == "die casting"


# ---------------------------------------------------------------------------
# Unit: answer generator (deterministic, no OpenAI key)
# ---------------------------------------------------------------------------
def test_answer_generator_deterministic():
    articles = [
        ContentArticle(
            id=1, title="Porosity control", body_markdown="Control porosity via venting.",
            topic="die casting", tags="porosity",
        ),
        ContentArticle(
            id=2, title="Gate design", body_markdown="Gate design matters.",
            topic="die casting", tags="gate",
        ),
    ]
    question = {"question_text": "How to reduce porosity in die casting?", "topic": "die casting"}
    out = answer_mod.generate_answer(question, content_articles=articles, use_llm=False)
    assert out["used_content_ids"] == [1, 2]
    assert out["quality_score"] >= 40
    assert out["quality_score"] <= 100
    assert "How to reduce porosity" in out["content_markdown"]
    assert "Porosity control" in out["content_markdown"]


def test_answer_generator_empty_content_still_scores(db):
    question = {"question_text": "What is die casting?", "topic": "die casting"}
    out = answer_mod.generate_answer(question, content_articles=[], use_llm=False)
    assert out["used_content_ids"] == []
    assert 40 <= out["quality_score"] <= 100


# ---------------------------------------------------------------------------
# Unit: SEO reuse pipeline helpers
# ---------------------------------------------------------------------------
def test_generate_slug():
    assert seo_mod.generate_slug("How To Reduce Porosity?!") == "how-to-reduce-porosity"


def test_derive_meta_truncates():
    meta_title, meta_desc, keywords = seo_mod.derive_meta(
        "Die casting guide",
        "A " + "word " * 200,
        topic="die casting",
        tags="a, b, a",
    )
    assert meta_title == "Die casting guide"
    assert len(meta_desc) <= 160
    assert keywords == "die casting, a, b"  # dedupe (keeps first occurrence), order kept


# ---------------------------------------------------------------------------
# Unit: discovery with injected resolver (offline)
# ---------------------------------------------------------------------------
def test_discover_questions_injected_resolver():
    resolver = lambda kw: [
        {"question_text": "Q1", "quora_url": "https://quora.com/q1", "topic": kw},
        {"question_text": "Q1", "quora_url": "https://quora.com/q1", "topic": kw},  # dup
        {"question_text": "Q2", "quora_url": "", "topic": kw},
    ]
    out = discovery_mod.discover_questions("die casting", resolver=resolver, limit=10)
    assert len(out) == 2  # deduplicated
    assert out[0]["quora_url"] == "https://quora.com/q1"


# ---------------------------------------------------------------------------
# API: full content -> question -> answer -> reuse -> blog -> export workflow
# ---------------------------------------------------------------------------
def test_full_authority_workflow(client, tmp_path, monkeypatch):
    # isolate export directories
    monkeypatch.setattr(settings, "quora_export_dir", str(tmp_path / "q"))
    monkeypatch.setattr(settings, "seo_blog_dir", str(tmp_path / "seo"))

    # 1. seed content DB
    r = client.post(
        "/quora/content",
        json={"title": "Porosity in HPDC",
              "body_markdown": "Venting and gate design reduce porosity.",
              "topic": "die casting", "tags": "porosity, defects"},
    )
    assert r.status_code == 201, r.text
    content_id = r.json()["id"]

    # 2. add a question
    r = client.post(
        "/quora/questions",
        json={"question_text": "How to reduce porosity in die casting?",
              "topic": "die casting", "tags": "porosity"},
    )
    assert r.status_code == 201, r.text
    qid = r.json()["id"]
    assert r.json()["status"] == "new"

    # 3. generate an answer (deterministic, grounded in content)
    r = client.post(f"/quora/questions/{qid}/generate-answer", json={"use_llm": False})
    assert r.status_code == 201, r.text
    ans = r.json()
    assert ans["status"] == "draft"
    assert isinstance(ans["quality_score"], int)
    assert "Porosity in HPDC" in ans["content_markdown"]

    # question advanced to drafted
    r = client.get(f"/quora/questions/{qid}")
    assert r.json()["status"] == "drafted"
    assert r.json()["answer_count"] == 1

    # 4. advance answer to published
    r = client.patch(f"/quora/answers/{ans['id']}/status", json={"status": "published"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"

    # 5. reuse answer as SEO blog
    r = client.post(f"/quora/answers/{ans['id']}/reuse-blog")
    assert r.status_code == 201, r.text
    blog = r.json()
    assert blog["source_type"] == "answer"
    assert blog["source_id"] == ans["id"]
    assert blog["slug"]
    assert blog["meta_title"]
    assert blog["keywords"]

    # question marked published + answer_id set
    r = client.get(f"/quora/questions/{qid}")
    assert r.json()["status"] == "published"
    assert r.json()["answer_id"] == ans["id"]

    # 6. blog appears in SEO list
    r = client.get("/seo/blog")
    assert r.status_code == 200
    assert any(b["id"] == blog["id"] for b in r.json())

    # 7. export blog markdown (file written)
    r = client.post(f"/seo/blog/{blog['id']}/export-markdown")
    assert r.status_code == 200, r.text
    export = r.json()
    assert os.path.exists(export["path"])
    assert "# " + blog["title"] in export["markdown"]

    # 8. export answer markdown
    r = client.post(f"/quora/answers/{ans['id']}/export-markdown")
    assert r.status_code == 200, r.text
    assert os.path.exists(r.json()["path"])


def test_discover_api_persists_new_questions(client, monkeypatch):
    monkeypatch.setattr(
        discovery_mod,
        "discover_questions",
        lambda keyword, limit=20: [
            {"question_text": "Q about die casting", "quora_url": "https://quora.com/dc",
             "topic": keyword},
        ],
    )
    r = client.post("/quora/questions/discover", json={"keyword": "die casting", "limit": 5})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["discovered"] == 1
    assert body["created"] == 1
    assert body["questions"][0]["source"] == "search"

    # re-discover same url -> no duplicate
    r = client.post("/quora/questions/discover", json={"keyword": "die casting", "limit": 5})
    assert r.json()["created"] == 0


def test_question_status_invalid_transition_400(client):
    r = client.post("/quora/questions", json={"question_text": "Why is my part warping?"})
    qid = r.json()["id"]
    # jump straight to 'published' from 'new' is allowed; use a typo to force 400
    r = client.patch(f"/quora/questions/{qid}/status", json={"status": "bogus"})
    assert r.status_code == 400, r.text


def test_reuse_content_as_blog(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "seo_blog_dir", str(tmp_path / "seo"))
    r = client.post(
        "/quora/content",
        json={"title": "Tooling maintenance", "body_markdown": "Keep molds clean.",
              "topic": "tooling", "tags": "maintenance"},
    )
    cid = r.json()["id"]
    r = client.post(f"/quora/content/{cid}/reuse-blog")
    assert r.status_code == 201, r.text
    blog = r.json()
    assert blog["source_type"] == "content"
    assert blog["source_id"] == cid
    assert blog["slug"] == "tooling-maintenance"


def test_missing_resources_return_404(client):
    assert client.get("/quora/questions/999999").status_code == 404
    assert client.get("/quora/answers/999999").status_code == 404
    assert client.get("/seo/blog/999999").status_code == 404
    assert client.post("/quora/questions/999999/generate-answer", json={}).status_code == 404
