from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from scraper.sources.base import Lead, Source

# Canonical field -> accepted column names (compared lowercased, alphanumerics only).
# Covers Apify and Outscraper Google Maps exports plus hand-made sheets.
ALIASES = {
    "name": ["name", "title", "businessname", "business", "company", "displayname"],
    "phone": ["phone", "phonenumber", "telephone", "mobile", "phoneunformatted", "contactphone"],
    "email": ["email", "email1", "emails", "contactemail"],
    "website": ["website", "site", "url", "websiteurl", "websiteuri", "domain"],
    "address": ["address", "fulladdress", "formattedaddress", "street"],
    "city": ["city"],
    "country": ["country", "countrycode"],
    "rating": ["rating", "totalscore", "score", "stars"],
    "review_count": ["reviews", "reviewscount", "reviewcount", "userratingcount", "numberofreviews"],
    "maps_url": ["mapsurl", "googlemapsurl", "googlemapsuri", "maplink", "location_link", "googleurl"],
    "source_id": ["placeid", "googleid", "cid", "id", "fid"],
    "niche": ["category", "categoryname", "type", "niche", "categories"],
    "lat": ["latitude", "lat", "locationlat"],
    "lon": ["longitude", "lng", "lon", "locationlng"],
}


def _key(col: str) -> str:
    return re.sub(r"[^a-z0-9]", "", col.lower())


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    num = _to_float(value)
    return int(num) if num is not None else None


def build_column_map(columns: List[str]) -> Dict[str, str]:
    """Map canonical field -> actual column name, first alias match wins."""
    by_key = {_key(c): c for c in columns}
    mapping = {}
    for canon, aliases in ALIASES.items():
        for alias in aliases:
            if alias in by_key:
                mapping[canon] = by_key[alias]
                break
    return mapping


def _get(row: Dict[str, Any], mapping: Dict[str, str], canon: str) -> Any:
    col = mapping.get(canon)
    if not col:
        return ""
    value = row.get(col)
    return "" if value is None else value


def row_to_lead(
    row: Dict[str, Any],
    mapping: Dict[str, str],
    source: str,
    niche: str = "",
    city: str = "",
    country: str = "",
) -> Optional[Lead]:
    name = str(_get(row, mapping, "name")).strip()
    if not name:
        return None
    phone = str(_get(row, mapping, "phone")).strip()
    address = str(_get(row, mapping, "address")).strip()
    source_id = str(_get(row, mapping, "source_id")).strip()
    if not source_id:
        basis = "|".join([name.lower(), phone, address.lower()])
        source_id = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return Lead(
        source=source,
        source_id=source_id,
        name=name,
        niche=niche or str(_get(row, mapping, "niche")).strip(),
        city=str(_get(row, mapping, "city")).strip() or city,
        country=str(_get(row, mapping, "country")).strip() or country,
        address=address,
        phone=phone,
        email=str(_get(row, mapping, "email")).strip(),
        website=str(_get(row, mapping, "website")).strip(),
        maps_url=str(_get(row, mapping, "maps_url")).strip(),
        rating=_to_float(_get(row, mapping, "rating")),
        review_count=_to_int(_get(row, mapping, "review_count")),
        lat=_to_float(_get(row, mapping, "lat")),
        lon=_to_float(_get(row, mapping, "lon")),
        raw={k: v for k, v in row.items() if v not in (None, "")},
    )


class CsvImport(Source):
    """Import leads from a CSV or JSON file (Apify/Outscraper exports, manual sheets)."""

    name = "csv"

    def fetch(  # type: ignore[override]
        self,
        path: str,
        niche: str = "",
        city: str = "",
        country: str = "Nigeria",
        source: str = "csv",
    ) -> Iterator[Lead]:
        file = Path(path)
        if file.suffix.lower() == ".json":
            data = json.loads(file.read_text())
            rows = data if isinstance(data, list) else data.get("items", [])
            columns = sorted({k for r in rows if isinstance(r, dict) for k in r})
        else:
            with file.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                columns = list(reader.fieldnames or [])
                rows = list(reader)
        mapping = build_column_map(columns)
        if "name" not in mapping:
            raise ValueError(
                "No name column found. Columns seen: %s" % ", ".join(columns)
            )
        for row in rows:
            if not isinstance(row, dict):
                continue
            lead = row_to_lead(row, mapping, source, niche, city, country)
            if lead:
                yield lead
