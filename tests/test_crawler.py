"""Tests for WebsiteCrawler using an injected fake fetcher (no browser)."""
from app.crawler.website_crawler import (
    WebsiteCrawler,
    is_path_allowed,
    parse_robots,
)


def _fake_fetcher(pages: dict):
    def fetcher(url: str) -> str:
        key = url.split("?")[0].rstrip("/")
        if key.endswith("/robots.txt"):
            return pages.get("__robots__", "User-agent: *\n")
        return pages.get(key, "<html></html>")

    return fetcher


def test_crawl_extracts_emails_and_discovers_pages():
    pages = {
        "https://acme.com": (
            '<html><title>Acme</title><a href="/products">p</a>'
            '<a href="/contact">c</a> sales@acme.com info@acme.com</html>'
        ),
        "https://acme.com/products": "<html>products noreply@acme.com</html>",
        "https://acme.com/contact": "<html>contact support@acme.com</html>",
        "https://acme.com/sitemap.xml": "<xml>sitemap</xml>",
    }
    crawler = WebsiteCrawler(
        max_pages=20, max_retries=1, fetcher=_fake_fetcher(pages)
    )
    result = crawler.crawl("https://acme.com")

    assert result.status == "success"
    assert "sales@acme.com" in result.emails
    assert "noreply@acme.com" not in result.emails
    assert "support@acme.com" not in result.emails
    assert any("sitemap.xml" in u for u in result.pages_found)
    assert len(result.text_content) > 0
    assert result.pages_crawled >= 1


def test_crawl_retries_then_succeeds():
    state = {"home_attempts": 0}

    def fetcher(url: str) -> str:
        if url.rstrip("/") == "https://acme.com":
            state["home_attempts"] += 1
            if state["home_attempts"] == 1:
                raise RuntimeError("transient network error")
            return "<html>home sales@acme.com</html>"
        return "<html></html>"

    crawler = WebsiteCrawler(max_pages=5, max_retries=3, fetcher=fetcher)
    result = crawler.crawl("https://acme.com")
    assert result.status == "success"
    assert state["home_attempts"] == 2  # one failure then success
    assert "sales@acme.com" in result.emails


def test_crawl_fails_after_retries():
    def fetcher(url: str) -> str:
        raise RuntimeError("site down")

    crawler = WebsiteCrawler(max_pages=5, max_retries=2, fetcher=fetcher)
    result = crawler.crawl("https://acme.com")
    assert result.status == "failed"
    assert result.error


def test_robots_blocks_disallowed_paths():
    pages = {
        "https://acme.com": (
            '<html><a href="/private">x</a><a href="/contact">c</a>'
            " sales@acme.com</html>"
        ),
        "https://acme.com/contact": "<html>contact</html>",
        "https://acme.com/private": "<html>secret</html>",
        "__robots__": "User-agent: *\nDisallow: /private\n",
    }
    crawler = WebsiteCrawler(
        max_pages=10, max_retries=1, fetcher=_fake_fetcher(pages)
    )
    result = crawler.crawl("https://acme.com")
    assert not any("private" in u for u in result.pages_found)
    assert "sales@acme.com" in result.emails


def test_robots_parser():
    rules = parse_robots("User-agent: *\nDisallow: /admin\nDisallow: /secret\n")
    assert is_path_allowed(rules, "/admin") is False
    assert is_path_allowed(rules, "/secret/page") is False
    assert is_path_allowed(rules, "/contact") is True
    # root disallow blocks everything
    blocked = parse_robots("User-agent: *\nDisallow: /\n")
    assert is_path_allowed(blocked, "/anything") is False
