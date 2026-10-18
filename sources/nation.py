from __future__ import annotations
import httpx
from sources.rss import RssSource

def build(client: httpx.AsyncClient) -> RssSource:
    return RssSource(
        client,
        name="nation",
        feed_url="https://nation.africa/kenya/rss.xml",
        credit="nation.africa",
        interval=300,
        max_items=5,
    )
