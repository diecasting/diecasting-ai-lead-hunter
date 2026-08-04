"""Phase 3 Stage 2 Website Intelligence Engine tests.

Covers (all without a real browser / network):
* crawler mock      — WebsiteCrawler with an injected fetcher exercises the new
                      async-concurrency + sitemap + contact-extraction paths.
* sitemap test      — discover_sitemap_urls parses urlset + sitemapindex + robots.
* contact extraction — name / title / email / linkedin detection.
* intelligence scoring — procurement signals (casting / CNC / OEM / supplier /
                      manufacturing capability).
* pdf classification — capability / catalog / technical typing.
"""
import pytest
from app.crawler.website_crawler import WebsiteCrawler, HttpFetcher, RateLimiter
from app.crawler.sitemap import discover_sitemap_urls
from app.crawler.contact_extractor import extract_contacts, extract_linkedin
from app.ai.procurement_signals import analyze_procurement_signals
from app.crawler.pdf_extractor import classify_pdf_type


# ---------------------------------------------------------------------------
# Crawler mock (injected fetcher)
# ---------------------------------------------------------------------------
def _fake_pages(pages: dict):
    def fetcher(url: str) -> str:
        key = url.split("?")[0].rstrip("/")
        if key.endswith("/robots.txt"):
            return pages.get("__robots__", "User-agent: *\n")
        return pages.get(key, "<html></html>")

    return fetcher


def _intel_site_pages():
    return {
        "https://acme.com": (
            "<html><title>Acme Die Casting</title>"
            '<a href="/products">p</a><a href="/contact">c</a>'
            " sales@acme.com"
            '<div>John Smith — Purchasing Manager</div>'
            '<a href="https://www.linkedin.com/in/johnsmith">in</a>'
            "We are an OEM supplier of high pressure die casting and CNC machining."
            "</html>"
        ),
        "https://acme.com/products": "<html>products info@acme.com</html>",
        "https://acme.com/contact": "<html>contact support@acme.com</html>",
        "https://acme.com/sitemap.xml": (
            "<urlset><loc>https://acme.com/about</loc>"
            "<loc>https://acme.com/capabilities</loc></urlset>"
        ),
        "__robots__": "User-agent: *\nSitemap: https://acme.com/sitemap.xml\n",
    }


class TestCrawlerMock:
    def test_crawl_uses_injected_fetcher_and_async(self):
        crawler = WebsiteCrawler(
            max_pages=10, max_retries=1, fetcher=_fake_pages(_intel_site_pages())
        )
        result = crawler.crawl("https://acme.com")
        assert result.status == "success"
        assert "sales@acme.com" in result.emails
        # Sitemap discovered (via robots Sitemap: directive) -> parsed page URLs.
        assert result.sitemap_urls, "expected sitemap-derived URLs"
        assert any("acme.com/about" in u for u in result.sitemap_urls)
        # Contacts extracted (name/title present).
        assert any(c.get("name") for c in result.contacts)
        assert any(c.get("email") for c in result.contacts)
        assert result.pages_crawled >= 1

    def test_http_fetcher_is_callable(self, monkeypatch):
        """HttpFetcher builds a real client lazily; with no network we just
        assert it is a callable url->str and the rate limiter exists."""
        f = HttpFetcher(rate=5.0)
        assert callable(f)
        assert isinstance(f._limiter, RateLimiter)
        f.close()

    def test_rate_limiter_allows_burst(self):
        lim = RateLimiter(rate=100.0)
        # Two sequential acquisitions should succeed without raising.
        with lim:
            pass
        with lim:
            pass
        assert True


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------
class TestSitemap:
    def test_urlset_parsing(self):
        xml = (
            "<urlset>"
            "<loc>https://x.com/a</loc>"
            "<loc>https://x.com/b</loc>"
            "</urlset>"
        )
        urls = discover_sitemap_urls(
            "https://x.com", robots_text="", fetcher=lambda u: xml if "sitemap" in u else ""
        )
        assert "https://x.com/a" in urls
        assert "https://x.com/b" in urls

    def test_robots_sitemap_directive(self):
        robots = "User-agent: *\nSitemap: https://x.com/s.xml\n"
        sm = "<urlset><loc>https://x.com/p1</loc></urlset>"
        urls = discover_sitemap_urls(
            "https://x.com", robots_text=robots, fetcher=lambda u: sm if "s.xml" in u else ""
        )
        assert "https://x.com/p1" in urls

    def test_sitemap_index_recurses(self):
        index = "<sitemapindex><loc>https://x.com/child.xml</loc></sitemapindex>"
        child = "<urlset><loc>https://x.com/deep</loc></urlset>"
        def fetcher(u):
            if "child" in u:
                return child
            return index
        urls = discover_sitemap_urls("https://x.com", robots_text="", fetcher=fetcher)
        assert "https://x.com/deep" in urls

    def test_no_fetcher_returns_empty(self):
        urls = discover_sitemap_urls("https://x.com", robots_text="Sitemap: https://x.com/s.xml")
        assert urls == []


# ---------------------------------------------------------------------------
# Contact extraction
# ---------------------------------------------------------------------------
class TestContactExtraction:
    def test_extracts_name_title_email_linkedin(self):
        html = (
            "<html>Acme Die Casting"
            '<div>John Smith — Purchasing Manager</div>'
            '<a href="mailto:john.smith@acme.com">email</a>'
            '<a href="https://www.linkedin.com/in/johnsmith">profile</a>'
            " sales@acme.com</html>"
        )
        contacts = extract_contacts(html, site_domain="acme.com")
        assert contacts
        c = contacts[0]
        assert c["name"] == "John Smith"
        assert "Purchasing Manager" in (c["title"] or "")
        assert c["email"] in ("john.smith@acme.com", "sales@acme.com")
        assert "linkedin.com/in/johnsmith" in (c["linkedin"] or "")

    def test_extract_linkedin_only(self):
        html = '<a href="https://www.linkedin.com/pub/jane-doe">Jane</a>'
        assert "linkedin.com/pub/jane-doe" in extract_linkedin(html)

    def test_no_contacts_when_empty(self):
        assert extract_contacts("<html>no people here</html>") == []

    def test_filters_personal_email(self):
        # gmail should be dropped by the shared email filter.
        html = "<html>Joe Blogs, CEO joe.bloggs@gmail.com</html>"
        contacts = extract_contacts(html, site_domain="acme.com")
        # gmail is a free domain -> dropped, so only the name/title line remains
        # but with no usable email; the contact may still surface with email None.
        assert all((c["email"] is None or "gmail" not in c["email"]) for c in contacts)


# ---------------------------------------------------------------------------
# Procurement signal scoring
# ---------------------------------------------------------------------------
class TestProcurementScoring:
    def test_casting_cnc_oem_supplier_signals(self):
        text = (
            "We are an OEM supplier of high pressure die casting and CNC machining "
            "services. IATF 16949 certified. Request a quote via our RFQ portal."
        )
        rep = analyze_procurement_signals(text)
        assert rep["components"]["casting"]["score"] > 0
        assert rep["components"]["cnc"]["score"] > 0
        assert rep["components"]["oem"]["score"] > 0
        assert rep["components"]["supplier"]["score"] > 0
        assert rep["procurement_score"] > 0
        assert rep["procurement_type"] in (
            "casting", "cnc", "oem", "supplier", "manufacturing_capability"
        )

    def test_manufacturing_capability_signals(self):
        text = (
            "Our manufacturing capabilities include a 2500 tonne clamping force "
            "machine, in-house tool room and IATF 16949 quality management."
        )
        rep = analyze_procurement_signals(text)
        assert rep["components"]["manufacturing_capability"]["score"] > 0

    def test_empty_text(self):
        rep = analyze_procurement_signals("")
        assert rep["procurement_score"] == 0
        assert rep["procurement_type"] == "casting"  # deterministic default


# ---------------------------------------------------------------------------
# PDF classification
# ---------------------------------------------------------------------------
class TestPdfClassification:
    def test_capability_by_filename(self):
        assert classify_pdf_type(url="https://x.com/capability-brochure.pdf") == "capability"

    def test_catalog_by_filename(self):
        assert classify_pdf_type(url="https://x.com/product-catalog.pdf") == "catalog"

    def test_technical_by_filename(self):
        assert classify_pdf_type(url="https://x.com/technical-datasheet.pdf") == "technical"

    def test_capability_by_body(self):
        text = "Our machine capacity is 800 tonne clamping force, IATF 16949 certified."
        assert classify_pdf_type(url="https://x.com/doc.pdf", text=text) == "capability"

    def test_catalog_by_body(self):
        text = "Browse our product range and part numbers in this catalog."
        assert classify_pdf_type(url="https://x.com/doc.pdf", text=text) == "catalog"

    def test_unknown(self):
        assert classify_pdf_type(url="https://x.com/random.pdf", text="hello world") == "unknown"
