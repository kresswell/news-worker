
import asyncio
import html
import os
import random
import re
from contextlib import suppress
from urllib.parse import quote

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    InputRichMessage,
    InputRichBlockSectionHeading,
    InputRichBlockParagraph,
    InputRichBlockFooter,
    InputRichBlockDivider,
    InputRichBlockPhoto,
    InputMediaPhoto,
    RichTextUrl,
    RichMessageButton,
    InputRichBlockButtons,
)
from dotenv import load_dotenv
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

load_dotenv()

TRACKER_API_URL = "https://api.kresswell.me/kenyans/tracker"
NEWS_API_URL = "https://api.kresswell.me/kenyans/news"
ARTICLE_API_URL = "https://api.kresswell.me/kenyans/article/{}"

MONGO_URI = os.getenv("MONGO_URI")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVAL_SECONDS = 30
REQUEST_TIMEOUT = 30.0

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing from environment variables")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is missing from environment variables")

if not CHAT_ID:
    raise RuntimeError("CHAT_ID is missing from environment variables")

CHAT_ID = int(CHAT_ID)

dp = Dispatcher()
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo.kenyans_db
collection = db.published_news

http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(REQUEST_TIMEOUT),
    limits=httpx.Limits(
        max_connections=20,
        max_keepalive_connections=10,
    ),
)

news_lock = asyncio.Lock()
tracker_lock = asyncio.Lock()


def strip_unsupported_html(message: str) -> str:
    """Convert API markup to safe plain text for Telegram HTML mode."""
    text = re.sub(r"<[^>]*>", "", str(message))
    return html.escape(html.unescape(text))


async def fetch_json(url: str):
    """Fetch JSON with timeouts and useful error logging."""
    response = await http_client.get(url)
    response.raise_for_status()
    return response.json()


async def is_published(news_id: str) -> bool:
    return await collection.find_one({"_id": news_id}, {"_id": 1}) is not None


async def mark_published(news_id: str) -> None:
    """Record an item after Telegram confirms the send."""
    try:
        await collection.insert_one({"_id": news_id})
    except DuplicateKeyError:
        logger.debug("Already recorded: {}", news_id)


async def post_latest_tracker():
    async with tracker_lock:
        try:
            data = await fetch_json(TRACKER_API_URL)

            for day in reversed(data):
                for item in reversed(day.get("news", [])):
                    news_id = (
                        f"tracker-{day['date']}-{item['time']}"
                        .replace(" ", "")
                        .replace(",", "")
                    )

                    if await is_published(news_id):
                        continue

                    clean_message = strip_unsupported_html(
                        item.get("message", "")
                    )
                    text = (
                        f"<b>{html.escape(str(item['time']))} - "
                        f"{html.escape(str(day['date']))}</b>\n\n"
                        f"{clean_message}"
                    )

                    try:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=text,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to send tracker item {}", news_id
                        )
                        continue

                    await mark_published(news_id)
                    await asyncio.sleep(3)

        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.exception("Tracker fetch or processing failed")


async def post_latest_news():
    async with news_lock:
        try:
            articles = await fetch_json(NEWS_API_URL)
            for article in articles:
                slug = article["link"]
                news_id = f"news-{slug}"

                if await is_published(news_id):
                    continue

                article_url = ARTICLE_API_URL.format(
                    quote(slug, safe="")
                )

                try:
                    full_article = await fetch_json(article_url)
                except (httpx.HTTPError, ValueError):
                    logger.exception(
                        "Failed to fetch article {}", slug
                    )
                    continue

                try:
                    blocks = []

                    blocks.append(
                        InputRichBlockSectionHeading(
                            size=2,
                            text=article["headline"],
                        )
                    )

                    content = full_article.get("content") or ""
                    images = full_article.get("images") or []

                    if images:
                        blocks.append(
                            InputRichBlockPhoto(
                                photo=InputMediaPhoto(media=images[0])
                            )
                        )

                    blocks.append(InputRichBlockDivider())

                    paragraph_blocks = []

                    for paragraph in content.split("\n\n"):
                        paragraph = paragraph.strip()
                        if not paragraph:
                            continue
                        pattern = re.compile(
                            r'<a\s+[^>]*href=["\']([^"\']+)'
                            r'["\'][^>]*>(.*?)</a>',
                            re.IGNORECASE | re.DOTALL,
                        )

                        parts = []
                        last_end = 0

                        for match in pattern.finditer(paragraph):
                            before = paragraph[last_end:match.start()]
                            if before:
                                parts.append(
                                    html.unescape(
                                        re.sub(r"<[^>]*>", "", before)
                                    )
                                )

                            link_url = html.unescape(match.group(1))
                            link_text = html.unescape(
                                re.sub(r"<[^>]*>", "", match.group(2))
                            )

                            if link_url.startswith(("https://", "http://")):
                                parts.append(
                                    RichTextUrl(
                                        text=link_text,
                                        url=link_url,
                                    )
                                )
                            else:
                                parts.append(link_text)

                            last_end = match.end()

                        after = paragraph[last_end:]
                        if after:
                            parts.append(
                                html.unescape(
                                    re.sub(r"<[^>]*>", "", after)
                                )
                            )

                        if not parts:
                            parts = [
                                html.unescape(
                                    re.sub(r"<[^>]*>", "", paragraph)
                                )
                            ]

                        paragraph_blocks.append(
                            InputRichBlockParagraph(text=parts)
                        )
                        paragraph_blocks.append(InputRichBlockDivider())

                    remaining_images = images[1:]
                    slots = list(range(0, len(paragraph_blocks), 2))
                    count = min(len(remaining_images), len(slots))

                    selected_slots = sorted(
                        random.sample(slots, count),
                        reverse=True,
                    )

                    for image_url, index in zip(
                        [remaining_images[i] for i in range(count)],
                        selected_slots,
                    ):
                        paragraph_blocks.insert(
                            index,
                            InputRichBlockPhoto(
                                photo=InputMediaPhoto(media=image_url)
                            ),
                        )
                        paragraph_blocks.insert(
                            index,
                            InputRichBlockDivider(),
                        )

                    blocks.extend(paragraph_blocks)

                    author = html.escape(
                        str(article.get("author") or "Kenyan's")
                    )
                    blocks.append(
                        InputRichBlockFooter(
                            text=f"📰 Original article by {author} "
                                 "on kenyans.co.ke"
                        )
                    )
                    blocks.append(InputRichBlockDivider())

                    full_article_url = (
                        f"https://www.kenyans.co.ke/news/{slug}"
                    )

                    blocks.append(
                        InputRichBlockButtons(
                            buttons=[
                                RichMessageButton(
                                    text="🌐 Read on Website",
                                    url=full_article_url,
                                    style="primary",
                                ),
                                RichMessageButton(
                                    text="📣 Share Channel",
                                    url="tg://share?url="
                                        "https://t.me/yanayojiri",
                                    style="success",
                                ),
                            ]
                        )
                    )

                    await bot.send_rich_message(
                        chat_id=CHAT_ID,
                        rich_message=InputRichMessage(blocks=blocks),
                    )

                    await mark_published(news_id)
                    logger.info("Published article: {}", slug)
                    await asyncio.sleep(3)

                except Exception:
                    logger.exception(
                        "Failed to build or publish article {}", slug
                    )
                    continue

        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.exception("News fetch or processing failed")


async def run_job(name: str, job):
    """Isolate failures so one scheduled job does not stop the other."""
    try:
        logger.info("Running {} job", name)
        await job()
        logger.info("Finished {} job", name)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("{} job crashed", name)


async def scheduler():
    """Run both jobs immediately, then every 30 minutes."""
    while True:
        started_at = asyncio.get_running_loop().time()

        await asyncio.gather(
            run_job("news", post_latest_news),
            run_job("tracker", post_latest_tracker),
        )

        elapsed = asyncio.get_running_loop().time() - started_at
        delay = max(0, INTERVAL_SECONDS - elapsed)

        logger.info(
            "Next scheduled run in {:.1f} minutes",
            delay / 60,
        )
        await asyncio.sleep(delay)


async def main():
    logger.info("Starting Telegram bot and 30-minute scheduler")

    try:
        await asyncio.gather(
            dp.start_polling(bot),
            scheduler(),
        )
    finally:
        await http_client.aclose()
        mongo.close()
        await bot.session.close()
        logger.info("Bot resources closed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
