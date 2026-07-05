"""
fetch_articles.py
------------------
Fetch all public articles from OptiSigns' Zendesk Help Center
via the official REST API (no auth needed as Help Center is public).

API docs reference: https://developer.zendesk.com/api-reference/help_center/help-center-api/articles/

Endpoint used:
    GET https://{subdomain}/api/v2/help_center/articles.json?per_page=100&page={n}

Each item returns full fields: id, title, body (HTML), html_url,
updated_at, created_at, section_id, ... (see field table in the requirements).
"""

import time
import requests

BASE_URL = "https://support.optisigns.com/api/v2/help_center/articles.json"
PER_PAGE = 100
TIMEOUT = 20
MAX_RETRIES = 3


def _get_with_retry(url, params=None):
    """GET with light retry/backoff because Zendesk has rate limits (429)."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"  [rate-limited] waiting {wait}s before retrying...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts.")


def fetch_all_articles(min_articles=30, locale="en-us"):
    """
    Return a list of article dicts (filtered by locale if needed).
    Zendesk returns cursor-based pagination via `next_page` field.
    Stop when out of pages or reached enough min_articles.
    """
    articles = []
    url = BASE_URL
    params = {
        "per_page": PER_PAGE,
        "sort_by": "updated_at",
        "sort_order": "desc"
    }

    page_num = 1
    while url:
        print(f"[fetch] page {page_num} -> {url}")
        data = _get_with_retry(url, params=params if page_num == 1 else None)
        batch = data.get("articles", [])
        articles.extend(batch)

        url = data.get("next_page")  # Zendesk returns full URL with query, or None
        params = None
        page_num += 1

        # Stop early if we have enough data (can still fetch all if full crawl is wanted)
        if min_articles is not None and len(articles) >= min_articles:
            break

        # safety: avoid infinite loop if API returns weird errors
        if page_num > 50:
            break

    if min_articles is not None:
        articles = articles[:min_articles]
        
    print(f"[fetch] Total articles fetched: {len(articles)}")
    return articles


if __name__ == "__main__":
    result = fetch_all_articles(min_articles=30)
    for a in result[:5]:
        print("-", a["id"], a["title"], a["html_url"])
