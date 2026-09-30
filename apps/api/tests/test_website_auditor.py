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
