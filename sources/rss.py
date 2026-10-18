from __future__ import annotations

import feedparser
import httpx
from loguru import logger

from models import Article
from sources.base import Source
from sources.extract import extract_page, images_from_html, paragraphs_from_html

MIN_FULL_TEXT_CHARS = 150


class RssSource(Source):
    """Generic RSS/Atom source with hybrid content extraction.

    Uses full text from the feed when present, otherwise fetches the article
    page; falls back to the feed summary.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        name: str,
        feed_url: str,
        credit: str,
        interval: int = 120,
        max_items: int = 5,
        fetch_full: bool = True,
    ) -> None:
        self._client = client
        self.name = name
        self.feed_url = feed_url
        self.credit = credit
        self.interval = interval
        self.max_items = max_items
        self.fetch_full = fetch_full

    async def fetch_new(self) -> list[Article]:
        response = await self._client.get(self.feed_url, follow_redirects=True)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        articles: list[Article] = []
        for entry in reversed(feed.entries[: self.max_items]):
            article = await self._entry_to_article(entry)
            if article:
                articles.append(article)
        return articles

    async def _entry_to_article(self, entry) -> Article | None:
        url = entry.get("link") or ""
        uid = entry.get("id") or entry.get("guid") or url
        if not uid:
            return None

        paragraphs, images = self._content_from_entry(entry)

        if self.fetch_full and url:
            joined = " ".join(paragraphs)
            if len(joined) < MIN_FULL_TEXT_CHARS:
                try:
                    page_paragraphs, page_images = await extract_page(
                        self._client, url
                    )
                    if len(" ".join(page_paragraphs)) > len(joined):
                        paragraphs = page_paragraphs
                    if page_images and not images:
                        images = page_images
                except (httpx.HTTPError, ValueError):
                    logger.exception(
                        "Failed to fetch full text {} {}", self.name, url
                    )

        headline = (entry.get("title") or "").strip()
        if not paragraphs and not headline:
            return None

        return Article(
            source=self.name,
            dedup_id=f"{self.name}:{uid}",
            url=url,
            headline=headline,
            author=entry.get("author"),
            credit=self.credit,
            paragraphs=paragraphs,
            images=images,
        )

    def _content_from_entry(self, entry) -> tuple[list[str], list[str]]:
        raw = ""
        if getattr(entry, "content", None):
            raw = entry.content[0].value or ""
        if not raw:
            raw = entry.get("description") or entry.get("summary") or ""

        paragraphs = paragraphs_from_html(raw)
        images = images_from_html(raw)
        if not images:
            images = self._images_from_entry(entry)
        return paragraphs, images

    @staticmethod
    def _images_from_entry(entry) -> list[str]:
        urls: list[str] = []
        for media in list(entry.get("media_content", [])) + list(
            entry.get("media_thumbnail", [])
        ):
            url = media.get("url")
            if url and url.startswith("http"):
                urls.append(url)
        for enclosure in entry.get("enclosures", []):
            url = enclosure.get("href") or enclosure.get("url")
            if url and str(enclosure.get("type", "")).startswith("image"):
                urls.append(url)
        return urls[:6]
