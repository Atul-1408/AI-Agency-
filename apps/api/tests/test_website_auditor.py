"""
Tests for WebsiteAuditorTool: SSRF protection, objective analysis, and parsing.
"""
from __future__ import annotations

import pytest

from tools.website_auditor import SSRFBlockedError, WebsiteAuditorTool, validate_url_safety


def test_ssrf_protection_blocks_restricted_hosts():
    """Verify internal and private addresses are strictly blocked."""
    with pytest.raises(SSRFBlockedError, match="Restricted hostname 'localhost' is blocked"):
        validate_url_safety("http://localhost:8000")

    with pytest.raises(SSRFBlockedError, match="Restricted hostname '127.0.0.1' is blocked"):
        validate_url_safety("http://127.0.0.1:3000")


def test_analyze_html_modern_responsive_website():
    """Analysis correctly detects mobile viewport tag and modern frameworks."""
    auditor = WebsiteAuditorTool()
    sample_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Modern Agency</title>
        <script id="__NEXT_DATA__">{}</script>
    </head>
    <body>
        <main>Welcome</main>
        <footer>© 2026 Modern Agency</footer>
    </body>
    </html>
    """
    result = auditor._analyze_html(
        status_code=200,
        load_time_ms=350,
        has_ssl=True,
        html=sample_html,
    )

    assert result.has_website is True
    assert result.is_responsive is True
    assert result.has_ssl is True
    assert result.copyright_year == 2026
    assert result.tech_stack.get("framework") == "Next.js"
    assert any("Mobile responsive" in f for f in result.audit_findings)


def test_analyze_html_legacy_unresponsive_website():
    """Analysis correctly detects missing viewport and outdated copyright without subjective claims."""
    auditor = WebsiteAuditorTool()
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Old Plumbing</title>
        <!-- No viewport tag -->
    </head>
    <body>
        <h1>Joe's Plumbing</h1>
        <div><a href="/wp-content/uploads/logo.png">Logo</a></div>
        <footer>Copyright 2017 Joe's Plumbing</footer>
    </body>
    </html>
    """
    result = auditor._analyze_html(
        status_code=200,
        load_time_ms=2800,
        has_ssl=False,
        html=sample_html,
    )

    assert result.is_responsive is False
    assert result.has_ssl is False
    assert result.copyright_year == 2017
    assert result.tech_stack.get("cms") == "WordPress"
    assert any("Not mobile responsive" in f for f in result.audit_findings)
    assert any("Insecure: Missing HTTPS" in f for f in result.audit_findings)
    assert any("Outdated copyright year: 2017" in f for f in result.audit_findings)
    assert any("Slow load time: 2800ms" in f for f in result.audit_findings)


# ── Redirect Security Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redirect_public_to_public_allowed():
    """1. Public URL redirecting to another public URL is safely followed."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://public-start.example.com/":
            return httpx.Response(301, headers={"Location": "https://public-target.example.com/final"})
        if str(request.url) == "https://public-target.example.com/final":
            return httpx.Response(200, text="<html><head><meta name='viewport' content='width=device-width'></head><body>Welcome</body></html>")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-start.example.com/")

    assert result.has_website is True
    assert result.status_code == 200
    assert result.is_responsive is True
    assert "ssrf_redirect_blocked" not in result.audit_findings


@pytest.mark.asyncio
async def test_redirect_to_localhost_blocked():
    """2. Public URL -> localhost redirect is blocked."""
    import httpx

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://localhost:8000/admin"})

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-site.example.com/")

    assert result.status_code == 302
    assert "ssrf_redirect_blocked" in result.audit_findings
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirect_to_127_0_0_1_blocked():
    """3. Public URL -> 127.0.0.1 redirect is blocked."""
    import httpx

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/secret"})

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-site.example.com/")

    assert "ssrf_redirect_blocked" in result.audit_findings
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirect_to_10_0_0_1_blocked():
    """4. Public URL -> 10.0.0.1 redirect is blocked."""
    import httpx

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://10.0.0.1/internal"})

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-site.example.com/")

    assert "ssrf_redirect_blocked" in result.audit_findings
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirect_to_192_168_1_1_blocked():
    """5. Public URL -> 192.168.1.1 redirect is blocked."""
    import httpx

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://192.168.1.1/router"})

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-site.example.com/")

    assert "ssrf_redirect_blocked" in result.audit_findings
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirect_to_169_254_169_254_blocked():
    """6. Public URL -> 169.254.169.254 (Cloud metadata) redirect is blocked."""
    import httpx

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-site.example.com/")

    assert "ssrf_redirect_blocked" in result.audit_findings
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirect_multi_hop_blocked_at_private_hop():
    """7. Multi-hop redirect (public -> public -> private) is blocked at private hop."""
    import httpx

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == "https://public-step1.example.com/":
            return httpx.Response(302, headers={"Location": "https://public-step2.example.com/"})
        if str(request.url) == "https://public-step2.example.com/":
            return httpx.Response(302, headers={"Location": "http://10.20.30.40/database"})
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-step1.example.com/")

    assert "ssrf_redirect_blocked" in result.audit_findings
    assert len(calls) == 2  # First two public calls made; third call blocked before execution


@pytest.mark.asyncio
async def test_redirect_loop_stops_after_max_redirects():
    """8. Redirect loop safely stops after MAX_REDIRECTS."""
    import httpx

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "loop-a" in str(request.url):
            return httpx.Response(302, headers={"Location": "https://public-loop-b.example.com/"})
        return httpx.Response(302, headers={"Location": "https://public-loop-a.example.com/"})

    transport = httpx.MockTransport(handler)
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.0, transport=transport)
    result = await auditor.audit("https://public-loop-a.example.com/")

    assert any("Exceeded maximum redirect limit" in f for f in result.audit_findings)
    assert len(calls) <= 7
