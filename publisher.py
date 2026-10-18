from __future__ import annotations

import asyncio
import html
import random
import re

from aiogram import Bot
from aiogram.types import (
    InputMediaPhoto,
    InputRichBlockButtons,
    InputRichBlockDivider,
    InputRichBlockFooter,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSectionHeading,
    InputRichMessage,
    RichMessageButton,
    RichTextUrl,
)
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from models import Article

LINK_PATTERN = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

SHARE_URL = "https://t.me/yanayojiri"


def build_fallback_text(article: Article) -> str:
    lines: list[str] = []
    if article.headline:
        lines.append(f"<b>{html.escape(article.headline)}</b>")
    for p in article.paragraphs[:3]:
        text = re.sub(r"<[^>]*>", "", p)
        text = html.unescape(text).strip()
        if text:
            lines.append(text)
    if article.url:
        lines.append(f'\n<a href="{article.url}">Read full story</a>')
    lines.append(f"\n<small>Via {html.escape(article.credit)}</small>")
    return "\n\n".join(lines)



def build_paragraph_parts(paragraph: str) -> list:
    """Turn a paragraph fragment (plain text with optional <a> tags) into
    Telegram rich-text parts."""
    parts: list = []
    last_end = 0

    for match in LINK_PATTERN.finditer(paragraph):
        before = paragraph[last_end:match.start()]
        if before:
            parts.append(html.unescape(re.sub(r"<[^>]*>", "", before)))

        link_url = html.unescape(match.group(1))
        link_text = html.unescape(re.sub(r"<[^>]*>", "", match.group(2)))

        if link_url.startswith(("https://", "http://")):
            parts.append(RichTextUrl(text=link_text, url=link_url))
        else:
            parts.append(link_text)

        last_end = match.end()

    after = paragraph[last_end:]
    if after:
        parts.append(html.unescape(re.sub(r"<[^>]*>", "", after)))

    if not parts:
        parts = [html.unescape(re.sub(r"<[^>]*>", "", paragraph))]

    return parts


def render_rich_blocks(article: Article) -> list:
    """Build the Telegram rich-message blocks for a full article."""
    blocks: list = []

    blocks.append(
        InputRichBlockSectionHeading(size=2, text=article.headline)
    )

    if article.images:
        blocks.append(
            InputRichBlockPhoto(
                photo=InputMediaPhoto(media=article.images[0])
            )
        )

    blocks.append(InputRichBlockDivider())

    paragraph_blocks: list = []
    for paragraph in article.paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        paragraph_blocks.append(
            InputRichBlockParagraph(text=build_paragraph_parts(paragraph))
        )
        paragraph_blocks.append(InputRichBlockDivider())

    remaining_images = article.images[1:]
    slots = list(range(0, len(paragraph_blocks), 2))
    count = min(len(remaining_images), len(slots))

    selected_slots = sorted(random.sample(slots, count), reverse=True)

    for image_url, index in zip(
        [remaining_images[i] for i in range(count)],
        selected_slots,
    ):
        paragraph_blocks.insert(
            index,
            InputRichBlockPhoto(photo=InputMediaPhoto(media=image_url)),
        )
        paragraph_blocks.insert(index, InputRichBlockDivider())

    blocks.extend(paragraph_blocks)

    author = html.escape(str(article.author or article.credit))
    blocks.append(
        InputRichBlockFooter(
            text=f"📰 Original article by {author} on {article.credit}"
        )
    )
    blocks.append(InputRichBlockDivider())

    blocks.append(
        InputRichBlockButtons(
            buttons=[
                RichMessageButton(
                    text="🌐 Read on Website",
                    url=article.url,
                    style="primary",
                ),
                RichMessageButton(
                    text="📣 Share Channel",
                    url=f"tg://share?url={SHARE_URL}",
                    style="success",
                ),
            ]
        )
    )

    return blocks


class Publisher:
    """Sends articles to Telegram with global rate limiting and dedup."""

    def __init__(
        self,
        bot: Bot,
        collection: AsyncIOMotorCollection,
        chat_id: int,
        send_delay: float = 2.0,
    ) -> None:
        self._bot = bot
        self._collection = collection
        self._chat_id = chat_id
        self._send_delay = send_delay
        self._lock = asyncio.Lock()

    async def is_published(self, dedup_id: str) -> bool:
        return (
            await self._collection.find_one({"_id": dedup_id}, {"_id": 1})
            is not None
        )

    async def mark_published(self, dedup_id: str) -> None:
        try:
            await self._collection.insert_one({"_id": dedup_id})
        except DuplicateKeyError:
            logger.debug("Already recorded: {}", dedup_id)

    async def publish(self, article: Article) -> bool:
        """Publish one article; returns True if it was newly sent."""
        if await self.is_published(article.dedup_id):
            return False

            try:
                if article.style == "brief":
                    await self._bot.send_message(
                        chat_id=self._chat_id,
                        text=article.brief_html,
                    )
                else:
                    await self._bot.send_rich_message(
                        chat_id=self._chat_id,
                        rich_message=InputRichMessage(
                            blocks=render_rich_blocks(article)
                        ),
                    )
            except TelegramBadRequest as exc:
                if "failed to get HTTP URL content" in str(exc):
                    logger.warning(
                        "Rich message failed for {} (bad image/link), falling back to text: {}",
                        article.dedup_id,
                        exc,
                    )
                    await self._bot.send_message(
                        chat_id=self._chat_id,
                        text=build_fallback_text(article),
                    )
                else:
                    raise
            except Exception:
                raise
            await asyncio.sleep(self._send_delay)

        await self.mark_published(article.dedup_id)
        logger.info(
            "Published {} article: {}", article.source, article.dedup_id
        )
        return True
