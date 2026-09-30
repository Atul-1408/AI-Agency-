"""
Public Contact Finder Tool.
Extracts strictly publicly listed business contact points (email, phone).
Prohibits personal social media profile scraping and personal PII.
Accurately reports email verification states (UNVERIFIED, SYNTAX_VALID, MX_VERIFIED, UNREACHABLE).
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import socket
from typing import List, Optional, Set
import structlog

from models import EmailVerificationStatus

log = structlog.get_logger(__name__)

# Valid business email regex (RFC 5322 simplified for web extraction)
EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'
)

# Non-contact file extensions and common assets mistaken for emails
IGNORED_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".woff", ".woff2"
)

# Common placeholders that are not actual business contacts
PLACEHOLDER_DOMAINS = (
    "example.com", "example.org", "wixpress.com", "domain.com", "yoursite.com", "email.com"
)

# Phone regex (North American & standard international formats)
PHONE_REGEX = re.compile(
    r'(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
)


@dataclass
class ContactInfo:
    """Discovered public business contacts."""
    email: Optional[str] = None
    email_verification_status: EmailVerificationStatus = EmailVerificationStatus.UNREACHABLE
    phone: Optional[str] = None
    contact_notes: Optional[str] = None


class PublicContactFinderTool:
    """Extracts public business contacts and evaluates verification states."""

    def extract_from_html(self, html: str, target_domain: Optional[str] = None) -> ContactInfo:
        """Extract public business emails and phones from public HTML body."""
        if not html:
            return ContactInfo()

        # 1. Extract candidate business emails
        candidate_emails: Set[str] = set()

        # Check mailto: links first (highest fidelity public contact intention)
        mailto_matches = re.findall(r'href=["\']mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7})', html, re.IGNORECASE)
        for em in mailto_matches:
            candidate_emails.add(em.strip().lower())

        # Check general body text
        body_matches = EMAIL_REGEX.findall(html)
        for em in body_matches:
            clean = em.strip().lower()
            if not any(clean.endswith(ext) for ext in IGNORED_EXTENSIONS):
                domain_part = clean.split("@")[-1]
                if domain_part not in PLACEHOLDER_DOMAINS:
                    candidate_emails.add(clean)

        # 2. Select primary business email
        primary_email: Optional[str] = None
        # Prioritize domain-matched corporate emails (e.g. info@domain.com)
        if target_domain:
            norm_dom = target_domain.lower().replace("www.", "")
            for em in candidate_emails:
                if em.endswith("@" + norm_dom) or em.endswith("." + norm_dom):
                    primary_email = em
                    break

        if not primary_email and candidate_emails:
            # Pick first valid business candidate
            primary_email = sorted(candidate_emails)[0]

        # 3. Determine Verification Status
        verification_status = EmailVerificationStatus.UNREACHABLE
        if primary_email:
            verification_status = self.verify_email(primary_email)

        # 4. Extract public business phone
        primary_phone: Optional[str] = None
        tel_matches = re.findall(r'href=["\']tel:([+0-9\-\.\(\)\s]+)["\']', html, re.IGNORECASE)
        if tel_matches:
            primary_phone = tel_matches[0].strip()
        else:
            phone_matches = PHONE_REGEX.findall(html)
            if phone_matches:
                primary_phone = phone_matches[0].strip()

        return ContactInfo(
            email=primary_email,
            email_verification_status=verification_status,
            phone=primary_phone,
        )

    def verify_email(self, email: str) -> EmailVerificationStatus:
        """
        Verify email validity honestly.
        1. Syntax regex check -> SYNTAX_VALID
        2. DNS MX check -> MX_VERIFIED
        """
        if not email or "@" not in email:
            return EmailVerificationStatus.UNREACHABLE

        domain = email.split("@")[1].strip().lower()
        if not domain or "." not in domain:
            return EmailVerificationStatus.UNREACHABLE

        # Syntax check
        if not EMAIL_REGEX.match(email):
            return EmailVerificationStatus.UNREACHABLE

        # DNS MX check
        try:
            # Using socket or dnspython if installed
            import dns.resolver
            records = dns.resolver.resolve(domain, "MX")
            if records and len(records) > 0:
                return EmailVerificationStatus.MX_VERIFIED
        except Exception:
            # If dnspython is unavailable or resolution times out, fallback to socket host check
            try:
                socket.getaddrinfo(domain, 25)
                # Domain resolves to mail host
                return EmailVerificationStatus.SYNTAX_VALID
            except Exception:
                pass

        return EmailVerificationStatus.SYNTAX_VALID
