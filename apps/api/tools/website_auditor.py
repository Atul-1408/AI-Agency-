"""
Website Auditor Tool — Objective technical analysis and SSRF-safe crawling.
Evaluates:
  - Connectivity & status code
  - SSL / HTTPS support
  - Load latency (ms)
  - Mobile viewport responsiveness
  - Copyright recency signals
  - Technology stack signals
Zero subjective claims — strictly records verifiable technical facts.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import re
import socket
import time
from typing import Any, Dict, List, Optional
import urllib.parse

import httpx
import structlog

log = structlog.get_logger(__name__)

# SSRF Blocklist (Private, loopback, link-local CIDRs)
PRIVATE_CIDRS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class SSRFBlockedError(Exception):
    """Raised when a target URL resolves to a private or restricted network address."""
    pass


def validate_url_safety(url: str) -> None:
    """
    Validate that the URL does not resolve to private, loopback, or link-local addresses.
    Raises SSRFBlockedError if unsafe.
    """
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError(f"Invalid URL structure: {url}")

    # Check for localhost / loopback aliases
    if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        raise SSRFBlockedError(f"Restricted hostname '{hostname}' is blocked.")

    try:
        # Resolve all IPs
        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            for cidr in PRIVATE_CIDRS:
                if ip_obj in cidr:
                    raise SSRFBlockedError(f"Target '{hostname}' resolves to private IP {ip_str} which is blocked.")
    except socket.gaierror as e:
        # DNS resolution failure will be handled downstream by HTTP client
        pass


@dataclass
class AuditResult:
    """Recorded objective findings of a website technical inspection."""
    has_website: bool
    status_code: Optional[int] = None
    load_time_ms: Optional[int] = None
    has_ssl: Optional[bool] = None
    is_responsive: Optional[bool] = None
    copyright_year: Optional[int] = None
    tech_stack: Dict[str, Any] = field(default_factory=dict)
    audit_findings: List[str] = field(default_factory=list)
    html_content: Optional[str] = None
    error_message: Optional[str] = None


class WebsiteAuditorTool:
    """Safe, objective technical website auditor."""

    def __init__(self, crawl_delay_seconds: float = 1.0, timeout_seconds: float = 8.0):
        self.crawl_delay = crawl_delay_seconds
        self.timeout = timeout_seconds
        self._last_crawl_times: Dict[str, float] = {}

    async def _enforce_crawl_delay(self, domain: str) -> None:
        """Enforce crawl delay between consecutive requests to the same domain."""
        now = time.time()
        last_time = self._last_crawl_times.get(domain, 0.0)
        elapsed = now - last_time
        if elapsed < self.crawl_delay:
            wait_time = self.crawl_delay - elapsed
            await asyncio.sleep(wait_time)
        self._last_crawl_times[domain] = time.time()

    async def audit(self, website_url: Optional[str]) -> AuditResult:
        """
        Perform objective technical audit of target website.
        If URL is None/empty, returns empty website result immediately.
        """
        if not website_url or not website_url.strip():
            return AuditResult(
                has_website=False,
                audit_findings=["No website URL provided"],
            )

        raw_url = website_url.strip()
        if not raw_url.startswith(("http://", "https://")):
            raw_url = "https://" + raw_url

        parsed = urllib.parse.urlparse(raw_url)
        domain = parsed.hostname or raw_url

        # 1. SSRF Safety Check
        try:
            validate_url_safety(raw_url)
        except SSRFBlockedError as e:
            log.warning("SSRF check blocked URL", url=raw_url, reason=str(e))
            return AuditResult(
                has_website=True,
                audit_findings=[f"Auditing blocked: {str(e)}"],
                error_message=str(e),
            )

        # 2. Rate limiting / crawl delay
        await self._enforce_crawl_delay(domain)

        # 3. HTTP inspection
        headers = {
            "User-Agent": "AIAgencyBot/1.0 (+http://localhost:8000/bot; Technical Audit)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        has_ssl = raw_url.startswith("https://")
        start_time = time.perf_counter()

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                verify=True,
            ) as client:
                response = await client.get(raw_url, headers=headers)
                latency_ms = int((time.perf_counter() - start_time) * 1000)

                final_url = str(response.url)
                if final_url.startswith("https://"):
                    has_ssl = True
                elif final_url.startswith("http://"):
                    has_ssl = False

                html = response.text or ""
                return self._analyze_html(
                    status_code=response.status_code,
                    load_time_ms=latency_ms,
                    has_ssl=has_ssl,
                    html=html,
                )

        except httpx.HTTPStatusError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            status = e.response.status_code if e.response else None
            return AuditResult(
                has_website=True,
                status_code=status,
                load_time_ms=latency_ms,
                has_ssl=has_ssl,
                audit_findings=[f"HTTP Error {status} received"],
                error_message=str(e),
            )
        except httpx.ConnectError as e:
            return AuditResult(
                has_website=False,
                has_ssl=False,
                audit_findings=["Connection failed / Domain unreachable"],
                error_message=str(e),
            )
        except httpx.TimeoutException:
            return AuditResult(
                has_website=True,
                load_time_ms=int(self.timeout * 1000),
                has_ssl=has_ssl,
                audit_findings=[f"Connection timed out after {self.timeout}s"],
                error_message=f"Timeout after {self.timeout}s",
            )
        except Exception as e:
            log.warning("Website audit encountered exception", url=raw_url, error=str(e))
            return AuditResult(
                has_website=False,
                audit_findings=[f"Audit error: {type(e).__name__}"],
                error_message=str(e),
            )

    def _analyze_html(
        self,
        status_code: int,
        load_time_ms: int,
        has_ssl: bool,
        html: str,
    ) -> AuditResult:
        """Extract objective technical indicators directly from HTML text."""
        findings: List[str] = []
        tech_stack: Dict[str, Any] = {}

        # Status code finding
        if status_code == 200:
            findings.append("HTTP 200 OK")
        else:
            findings.append(f"HTTP status: {status_code}")

        # SSL finding
        if has_ssl:
            findings.append("HTTPS / SSL enabled")
        else:
            findings.append("Insecure: Missing HTTPS / SSL")

        # Load time finding
        if load_time_ms > 2500:
            findings.append(f"Slow load time: {load_time_ms}ms (threshold 2500ms)")
        else:
            findings.append(f"Response time: {load_time_ms}ms")

        # Mobile Viewport Responsive Check
        is_responsive = bool(re.search(
            r'<meta\s+[^>]*name=["\']viewport["\'][^>]*content=["\'][^"\']*width=device-width',
            html,
            re.IGNORECASE,
        ))
        if is_responsive:
            findings.append("Mobile responsive viewport meta tag detected")
        else:
            findings.append("Not mobile responsive: Missing viewport meta tag")

        # Copyright / Recency Check
        current_year = datetime.now(timezone.utc).year
        copyright_year: Optional[int] = None
        # Matches © 2018, &copy; 2018, Copyright 2018, Copyright 2015-2019
        c_match = re.search(
            r'(?:&copy;|©|copyright|\(c\))\s*(?:20\d\d\s*[-–]\s*)?(20\d\d)',
            html,
            re.IGNORECASE,
        )
        if c_match:
            try:
                copyright_year = int(c_match.group(1))
                age = current_year - copyright_year
                if age >= 4:
                    findings.append(f"Outdated copyright year: {copyright_year} ({age} years old)")
                else:
                    findings.append(f"Recent copyright year: {copyright_year}")
            except Exception:
                pass

        # Detectable Tech Stack signals
        lower_html = html.lower()
        if "wp-content" in lower_html or "wp-includes" in lower_html:
            tech_stack["cms"] = "WordPress"
            findings.append("CMS: WordPress detected")
        elif "cdn.shopify.com" in lower_html or "shopify.theme" in lower_html:
            tech_stack["ecommerce"] = "Shopify"
            findings.append("Platform: Shopify detected")
        elif "static.wixstatic.com" in lower_html or "wix.com" in lower_html:
            tech_stack["builder"] = "Wix"
            findings.append("Builder: Wix detected")
        elif "squarespace.com" in lower_html:
            tech_stack["builder"] = "Squarespace"
            findings.append("Builder: Squarespace detected")

        if "__next_data__" in lower_html or "/_next/" in lower_html:
            tech_stack["framework"] = "Next.js"
            findings.append("Framework: Modern Next.js application")
        elif "react-root" in lower_html or "data-reactroot" in lower_html:
            tech_stack["framework"] = "React"

        return AuditResult(
            has_website=True,
            status_code=status_code,
            load_time_ms=load_time_ms,
            has_ssl=has_ssl,
            is_responsive=is_responsive,
            copyright_year=copyright_year,
            tech_stack=tech_stack,
            audit_findings=findings,
            html_content=html,
        )
