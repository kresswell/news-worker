from __future__ import annotations
import httpx
from sources.rss import RssSource

def build(client: httpx.AsyncClient) -> RssSource:
    return RssSource(
        client,
        name="kbc",
        feed_url="https://www.kbc.co.ke/feed/",
        credit="kbc.co.ke",
        interval=300,
        max_items=5,
    )
