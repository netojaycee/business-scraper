from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scraper.audit import contacts

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 LeadAudit/0.1"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en",
}
MAX_BYTES = 600_000
SOCIAL_HOSTS = (
    "facebook.com", "fb.com", "fb.me", "instagram.com", "linktr.ee", "linktree.com",
    "wa.me", "whatsapp.com", "twitter.com", "x.com", "tiktok.com", "youtube.com",
    "linkedin.com", "t.me", "bio.link", "beacons.ai",
)
# marker -> builder name; first match wins
_BUILDERS = (
    ("wixstatic.com", "wix"), ("wix.com", "wix"), ("squarespace", "squarespace"),
    ("weebly", "weebly"), ("blogspot.", "blogger"), ("blogger.com", "blogger"),
    ("cdn.shopify.com", "shopify"), ("webflow", "webflow"), ("godaddy", "godaddy"),
    ("business.site", "google-business-site"), ("wp-content", "wordpress"),
)
_CTA_TEXT = re.compile(
    r"\b(contact|book|call|enquir|inquir|get a quote|order|reserve|apply|whatsapp)\b", re.I
)
_COPYRIGHT = re.compile(
    r"(?:©|&copy;|copyright)[^0-9]{0,40}((?:19|20)\d{2})(?:\s*[-–]\s*((?:19|20)\d{2}))?", re.I
)


def blank_result(has_website: bool) -> Dict[str, Any]:
    return {
        "has_website": int(has_website), "website_is_social": 0, "http_status": None,
        "final_url": "", "https": None, "load_ms": None, "psi_mobile": None,
        "mobile_viewport": None, "title": "", "meta_description": "", "has_cta": None,
        "copyright_year": None, "builder": "", "emails_found": [], "socials": {},
        "whatsapp_found": "", "error": "",
    }


def host_of(url: str) -> str:
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", url or "", re.I):
        url = "//" + (url or "")
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_social_host(url: str) -> bool:
    host = host_of(url)
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw.lstrip("/")
    return raw


def _fetch(url: str, timeout: int, verify: bool = True) -> Tuple[requests.Response, str, int]:
    start = time.time()
    resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True,
                        stream=True, verify=verify)
    chunks, size = [], 0
    for chunk in resp.iter_content(65536):
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BYTES:
            break
    resp.close()
    ms = int((time.time() - start) * 1000)
    body = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    return resp, body, ms


def detect_builder(html: str) -> str:
    low = html.lower()
    for marker, name in _BUILDERS:
        if marker in low:
            return name
    return ""


def latest_copyright_year(html: str) -> Optional[int]:
    years = []
    for first, second in _COPYRIGHT.findall(html):
        years.append(int(second or first))
    return max(years) if years else None


def detect_cta(soup: BeautifulSoup) -> bool:
    if soup.select('a[href^="tel:"], a[href*="wa.me"], a[href*="whatsapp"], form'):
        return True
    for el in soup.select("a, button"):
        if _CTA_TEXT.search(el.get_text(" ", strip=True)[:60]):
            return True
    return False


def _contact_page(soup: BeautifulSoup, base_url: str) -> str:
    base_host = host_of(base_url)
    for a in soup.select("a[href]"):
        href, text = a["href"], a.get_text(" ", strip=True).lower()
        if "contact" in href.lower() or "contact" in text:
            full = urljoin(base_url, href)
            if full.startswith("http") and host_of(full) == base_host:
                return full
    return ""


def audit_url(raw_url: str, timeout: int = 12) -> Dict[str, Any]:
    """Audit one website. Never raises; failures are recorded in the result."""
    url = normalize_url(raw_url)
    result = blank_result(bool(url))
    if not url:
        return result
    if is_social_host(url):
        result["website_is_social"] = 1
        result["final_url"] = url
        return result

    parsed = urlparse(url)
    tries = [parsed._replace(scheme="https").geturl(), parsed._replace(scheme="http").geturl()]
    ssl_failed = False
    resp, html, ms, last_error = None, "", 0, ""
    for attempt in tries:
        try:
            resp, html, ms = _fetch(attempt, timeout)
            break
        except requests.exceptions.SSLError as exc:
            ssl_failed = True
            last_error = "SSL error: %s" % str(exc)[:120]
        except requests.exceptions.RequestException as exc:
            last_error = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    if resp is None:
        result["error"] = last_error or "unreachable"
        return result

    result["http_status"] = resp.status_code
    result["final_url"] = resp.url
    result["load_ms"] = ms
    result["https"] = int(resp.url.startswith("https://") and not ssl_failed)
    if resp.status_code >= 400:
        result["error"] = "HTTP %d" % resp.status_code
        return result

    # A redirect to a social page means the "website" is really a social profile.
    if is_social_host(resp.url):
        result["website_is_social"] = 1
        return result

    soup = BeautifulSoup(html, "html.parser")
    result["title"] = (soup.title.get_text(strip=True) if soup.title else "")[:200]
    desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    result["meta_description"] = (desc.get("content", "") if desc else "")[:300]
    result["mobile_viewport"] = int(bool(soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})))
    result["has_cta"] = int(detect_cta(soup))
    result["copyright_year"] = latest_copyright_year(html)
    result["builder"] = detect_builder(html)
    if "blogspot." in host_of(resp.url) or host_of(resp.url).endswith("business.site"):
        result["builder"] = result["builder"] or "free-subdomain"

    emails = contacts.extract_emails(html)
    socials = contacts.extract_socials(html)
    whatsapp = contacts.extract_whatsapp(html)
    if not emails:
        contact_url = _contact_page(soup, resp.url)
        if contact_url:
            try:
                _r2, html2, _ = _fetch(contact_url, timeout)
                emails = contacts.extract_emails(html2)
                socials = socials or contacts.extract_socials(html2)
                whatsapp = whatsapp or contacts.extract_whatsapp(html2)
            except requests.exceptions.RequestException:
                pass
    result["emails_found"] = emails[:5]
    result["socials"] = socials
    result["whatsapp_found"] = whatsapp
    return result
