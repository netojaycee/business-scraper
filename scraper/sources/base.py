from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional

_NG_MOBILE = re.compile(r"^\+234[789][01]\d{8}$")


def normalize_phone(raw: Any) -> str:
    """Normalise to E.164-ish. Nigerian local formats become +234...

    Returns '' when there is no usable number. Only the first number is kept
    when several are separated by / , ; | or 'or'.
    """
    if raw is None:
        return ""
    text = re.split(r"[;,/|]| or ", str(raw))[0].strip()
    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
        has_plus = True
    if has_plus:
        return "+" + digits
    if digits.startswith("234") and len(digits) >= 12:
        return "+" + digits
    if digits.startswith("0") and len(digits) == 11:
        return "+234" + digits[1:]
    if len(digits) == 10 and digits[0] in "789":
        return "+234" + digits
    if len(digits) >= 11:
        return "+" + digits
    return digits


def is_likely_whatsapp(phone: str) -> bool:
    """Nigerian mobile numbers are very likely to be on WhatsApp. Landlines are not."""
    return bool(_NG_MOBILE.match(phone or ""))


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


@dataclass
class Lead:
    source: str
    source_id: str
    name: str
    niche: str = ""
    city: str = ""
    country: str = ""
    address: str = ""
    phone: str = ""
    whatsapp: str = ""
    email: str = ""
    website: str = ""
    maps_url: str = ""
    rating: Optional[float] = None
    review_count: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.phone = normalize_phone(self.phone)
        if not self.whatsapp and is_likely_whatsapp(self.phone):
            self.whatsapp = self.phone
        self.email = (self.email or "").strip().lower()
        self.website = (self.website or "").strip()

    def dedupe_key(self) -> str:
        if self.phone:
            return "p:" + self.phone
        name = norm_name(self.name)
        if name:
            return "n:%s|%s" % (name, norm_name(self.city))
        return ""


class Source:
    """A lead source. Subclasses yield Lead objects; nothing else needs to change."""

    name = "source"

    def fetch(self, **kwargs: Any) -> Iterator[Lead]:  # pragma: no cover - interface
        raise NotImplementedError
