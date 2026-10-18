from __future__ import annotations

import httpx

from sources.rss import RssSource


def build(client: httpx.AsyncClient) -> RssSource:
    return RssSource(
        client,
        name="citizen",
        feed_url="https://www.citizen.digital/feed.xml",
        credit="citizen.digital",
        interval=120,
        max_items=5,
    )
