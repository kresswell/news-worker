from __future__ import annotations
import httpx
from sources.rss import RssSource

def build(client: httpx.AsyncClient) -> RssSource:
    return RssSource(
        client,
        name="standard",
        feed_url="https://www.standardmedia.co.ke/rss/headlines.php",
        credit="standardmedia.co.ke",
        interval=300,
        max_items=5,
    )
