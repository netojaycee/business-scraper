from __future__ import annotations

import re
from typing import Dict, List
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_JUNK = (
    "example.", "sentry", "wixpress", "yourdomain", "domain.com", "email.com",
    "yourname", "@2x", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "u003e",
)
_SOCIAL_PATTERNS = {
    "facebook": re.compile(r"https?://(?:www\.|m\.|web\.)?(?:facebook\.com|fb\.com)/[^\s\"'<>?#]+", re.I),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[^\s\"'<>?#]+", re.I),
    "twitter": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[^\s\"'<>?#]+", re.I),
    "linkedin": re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/(?:company|in)/[^\s\"'<>?#]+", re.I),
    "tiktok": re.compile(r"https?://(?:www\.)?tiktok\.com/@[^\s\"'<>?#]+", re.I),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/(?:c/|channel/|@|user/)[^\s\"'<>?#]+", re.I),
}
_SHARE_PARTS = ("sharer", "share?", "/intent/", "/dialog/", "/plugins/", "/tr?")


def _clean_email(value: str) -> str:
    return value.strip().strip(".,;:()<>[]\"'").lower()


def extract_emails(html: str) -> List[str]:
    """mailto: links first, then addresses visible in the text. Junk filtered, order kept."""
    found: List[str] = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select('a[href^="mailto:"]'):
        raw = unquote(a["href"][7:].split("?")[0])
        for part in raw.split(","):
            email = _clean_email(part)
            if EMAIL_RE.fullmatch(email):
                found.append(email)
    for match in EMAIL_RE.findall(soup.get_text(" ")):
        found.append(_clean_email(match))
    out: List[str] = []
    for email in found:
        if any(j in email for j in _JUNK):
            continue
        if email not in out:
            out.append(email)
    return out


def extract_socials(html: str) -> Dict[str, str]:
    socials: Dict[str, str] = {}
    for name, pattern in _SOCIAL_PATTERNS.items():
        for match in pattern.findall(html):
            link = match.rstrip("/.,;)")
            if any(part in link.lower() for part in _SHARE_PARTS):
                continue
            socials[name] = link
            break
    return socials


def extract_whatsapp(html: str) -> str:
    """Return a digits-only WhatsApp number from wa.me / api.whatsapp.com links, or ''."""
    for match in re.findall(r"https?://(?:wa\.me/|api\.whatsapp\.com/send\?[^\"'\s>]*)[^\"'\s>]*", html, re.I):
        parsed = urlparse(match)
        if parsed.netloc.lower() == "wa.me":
            digits = re.sub(r"\D", "", parsed.path)
        else:
            digits = re.sub(r"\D", "", parse_qs(parsed.query).get("phone", [""])[0])
        if len(digits) >= 10:
            return digits
    return ""
