from __future__ import annotations

import html
import re
from urllib.parse import quote

import httpx
from loguru import logger

from models import Article
from sources.base import Source

KENYANS_NEWS_API_URL = "https://api.kresswell.me/kenyans/news"
KENYANS_ARTICLE_API_URL = "https://api.kresswell.me/kenyans/article/{}"
KENYANS_TRACKER_API_URL = "https://api.kresswell.me/kenyans/tracker"

KENYANS_BASE_URL = "https://www.kenyans.co.ke/news/{}"


def strip_unsupported_html(message: str) -> str:
    """Convert API markup to safe plain text for Telegram HTML mode."""
    text = re.sub(r"<[^>]*>", "", str(message))
    return html.escape(html.unescape(text))


class KenyansClient:
    """Shared JSON fetching for the kenyans.co.ke API sources."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_json(self, url: str):
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json()


class KenyansNewsSource(Source):
    name = "kenyans"
    interval = 30

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._api = KenyansClient(client)

    async def fetch_new(self) -> list[Article]:
        listing = await self._api.fetch_json(KENYANS_NEWS_API_URL)

        articles: list[Article] = []
        for item in listing:
            slug = item["link"]
            try:
                full_article = await self._api.fetch_json(
                    KENYANS_ARTICLE_API_URL.format(quote(slug, safe=""))
                )
            except (httpx.HTTPError, ValueError):
                logger.exception("Failed to fetch article {}", slug)
                continue

            content = full_article.get("content") or ""
            paragraphs = [p for p in content.split("\n\n") if p.strip()]

            articles.append(
                Article(
                    source=self.name,
                    dedup_id=f"news-{slug}",
                    url=KENYANS_BASE_URL.format(slug),
                    headline=item["headline"],
                    author=item.get("author"),
                    credit="kenyans.co.ke",
                    paragraphs=paragraphs,
                    images=full_article.get("images") or [],
                )
            )
        return articles


class KenyansTrackerSource(Source):
    name = "tracker"
    interval = 30

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._api = KenyansClient(client)

    async def fetch_new(self) -> list[Article]:
        data = await self._api.fetch_json(KENYANS_TRACKER_API_URL)

        articles: list[Article] = []
        for day in reversed(data):
            for item in reversed(day.get("news", [])):
                news_id = (
                    f"tracker-{day['date']}-{item['time']}"
                    .replace(" ", "")
                    .replace(",", "")
                )
                clean_message = strip_unsupported_html(
                    item.get("message", "")
                )
                brief = (
                    f"<b>{html.escape(str(item['time']))} - "
                    f"{html.escape(str(day['date']))}</b>\n\n"
                    f"{clean_message}"
                )
                articles.append(
                    Article(
                        source=self.name,
                        dedup_id=news_id,
                        credit="kenyans.co.ke",
                        style="brief",
                        brief_html=brief,
                    )
                )
        return articles
