from __future__ import annotations

from typing import Optional

import requests

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def mobile_score(url: str, api_key: str = "", timeout: int = 90) -> Optional[int]:
    """PageSpeed Insights mobile performance score 0-100, or None if unavailable.

    Works without a key at a low rate limit; a key raises it. Failures return None
    so a rate limit never blocks the rest of the audit.
    """
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if api_key:
        params["key"] = api_key
    try:
        resp = requests.get(ENDPOINT, params=params, timeout=timeout)
        if resp.status_code != 200:
            return None
        score = resp.json()["lighthouseResult"]["categories"]["performance"]["score"]
        return None if score is None else int(round(score * 100))
    except (requests.exceptions.RequestException, KeyError, ValueError):
        return None
