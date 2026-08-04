"""Unit tests for app.crawler.page_discovery (no browser required)."""
from app.crawler.page_discovery import (
    classify_path,
    candidate_urls,
    discover_pages,
    extract_links,
    extract_text,
)


def test_classify_path_categories():
    assert classify_path("/contact") == "contact"
    assert classify_path("/contact-us") == "contact"
    assert classify_path("/contactus") == "contact"
    assert classify_path("/sales") == "contact"
    assert classify_path("/rfq") == "contact"
    assert classify_path("/products") == "product"
    assert classify_path("/solution") == "product"
    assert classify_path("/capabilities") == "product"
    assert classify_path("/about") == "company"
    assert classify_path("/company") == "company"
    assert classify_path("/factory") == "company"
    assert classify_path("/blog") == "other"
    assert classify_path("/") == "other"


def test_candidate_urls_uses_canonical_set():
    urls = candidate_urls("https://acme.com")
    paths = set(urls.keys())
    assert "/" in paths
    assert urls["/"] == "https://acme.com/"
    # Every spec-mandated contact / quote entry point is present.
    for p in ("/contact", "/contact-us", "/request-quote", "/rfq"):
        assert p in paths
    assert "/solutions" in paths
    assert "/sitemap.xml" in paths
    # No duplicates.
    assert len(paths) == len(urls)


def test_extract_links_keeps_internal_only():
    html = (
        '<a href="/about">a</a>'
        '<a href="https://acme.com/products">p</a>'
        '<a href="https://other.com/x">ext</a>'
        '<a href="mailto:foo@acme.com">m</a>'
        '<a href="#top">top</a>'
    )
    links = extract_links(html, base_domain="acme.com")
    assert "https://acme.com/about" in links
    assert "https://acme.com/products" in links
    assert all("other.com" not in l for l in links)
    assert all(not l.startswith("mailto:") for l in links)


def test_discover_pages_groups_links():
    html = (
        '<a href="/contact-us">c</a>'
        '<a href="/products">p</a>'
        '<a href="/about">a</a>'
        '<a href="https://external.com">e</a>'
    )
    discovered = discover_pages("https://acme.com", html)
    assert any("contact-us" in u for u in discovered["contact"])
    assert any("products" in u for u in discovered["product"])
    assert any("about" in u for u in discovered["company"])
    assert all("external.com" not in u for u in discovered["contact"])


def test_extract_text_strips_tags():
    html = "<html><head><style>.x{}</style></head><body><p>Hello <b>World</b></p></body></html>"
    text = extract_text(html)
    assert "Hello" in text and "World" in text
    assert "<" not in text
