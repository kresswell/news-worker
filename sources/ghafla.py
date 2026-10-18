from __future__ import annotations

import httpx

from sources.rss import RssSource


def build(client: httpx.AsyncClient) -> RssSource:
    return RssSource(
        client,
        name="ghafla",
        feed_url="https://www.ghafla.co.ke/feed",
        credit="ghafla.co.ke",
        interval=300,
        max_items=5,
    )
