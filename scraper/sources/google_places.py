from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

from scraper import db
from scraper.sources.base import Lead, Source

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
PROVIDER = "google_places"
# Phone, website and rating put Text Search in the higher (Enterprise) billing tier.
SKU = "text_search_enterprise"
PAGE_SIZE = 20
MAX_PAGES = 3  # Text Search returns at most 60 results per query

FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.googleMapsUri",
        "places.businessStatus",
        "places.location",
        "nextPageToken",
    ]
)


class PlacesError(RuntimeError):
    pass


class PlacesBillingError(PlacesError):
    pass


class SpendCapReached(PlacesError):
    pass


def build_queries(base_queries: List[str], city: str, areas: Optional[List[str]]) -> List[str]:
    """One text query per (search term, area). Falls back to the city alone."""
    places = areas if areas else [""]
    queries = []
    for term in base_queries:
        for area in places:
            where = ", ".join(p for p in (area, city) if p)
            queries.append("%s in %s" % (term, where))
    return queries


def estimate_requests(query_count: int, max_pages: int = MAX_PAGES) -> int:
    """Upper bound: every query uses all its pages."""
    return query_count * max_pages


class GooglePlaces(Source):
    name = PROVIDER

    def __init__(
        self,
        api_key: str,
        conn: sqlite3.Connection,
        max_requests: int,
        max_requests_per_day: int,
        region_code: str = "NG",
        delay: float = 0.2,
    ) -> None:
        if not api_key:
            raise PlacesError("GOOGLE_PLACES_API_KEY is not set (see status.md P0-7).")
        self.api_key = api_key
        self.conn = conn
        self.max_requests = max_requests
        self.max_requests_per_day = max_requests_per_day
        self.region_code = region_code
        self.delay = delay
        self.requests_made = 0

    def _check_cap(self) -> None:
        if self.requests_made >= self.max_requests:
            raise SpendCapReached(
                "Per-run cap of %d requests reached." % self.max_requests
            )
        if db.usage_today(self.conn, PROVIDER) >= self.max_requests_per_day:
            raise SpendCapReached(
                "Daily cap of %d requests reached." % self.max_requests_per_day
            )

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        self._check_cap()
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }
        for attempt in range(2):
            resp = requests.post(ENDPOINT, json=body, headers=headers, timeout=30)
            if resp.status_code == 429 and attempt == 0:
                time.sleep(2)
                continue
            break
        # Count every attempt that reached Google, success or not.
        self.requests_made += 1
        db.record_usage(self.conn, PROVIDER, SKU, 1)
        if resp.status_code == 403:
            raise PlacesBillingError(
                "403 from Places API. Billing is probably not linked, the API is not "
                "enabled, or the key is restricted. Response: %s" % resp.text[:300]
            )
        if resp.status_code != 200:
            raise PlacesError("Places API %s: %s" % (resp.status_code, resp.text[:300]))
        return resp.json()

    def fetch(  # type: ignore[override]
        self,
        niche: str,
        city: str,
        country: str,
        queries: List[str],
        max_pages: int = MAX_PAGES,
    ) -> Iterator[Lead]:
        for query in queries:
            token: Optional[str] = None
            for _page in range(max_pages):
                body: Dict[str, Any] = {
                    "textQuery": query,
                    "pageSize": PAGE_SIZE,
                    "regionCode": self.region_code,
                }
                if token:
                    body["pageToken"] = token
                data = self._post(body)
                for place in data.get("places", []):
                    lead = self._to_lead(place, niche, city, country)
                    if lead:
                        yield lead
                token = data.get("nextPageToken")
                if not token:
                    break
                time.sleep(self.delay)

    @staticmethod
    def _to_lead(place: Dict[str, Any], niche: str, city: str, country: str) -> Optional[Lead]:
        if place.get("businessStatus") in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
            return None
        name = (place.get("displayName") or {}).get("text", "").strip()
        if not name or not place.get("id"):
            return None
        loc = place.get("location") or {}
        return Lead(
            source=PROVIDER,
            source_id=place["id"],
            name=name,
            niche=niche,
            city=city,
            country=country,
            address=place.get("formattedAddress", ""),
            phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or "",
            website=place.get("websiteUri", ""),
            maps_url=place.get("googleMapsUri", ""),
            rating=place.get("rating"),
            review_count=place.get("userRatingCount"),
            lat=loc.get("latitude"),
            lon=loc.get("longitude"),
            raw=place,
        )
