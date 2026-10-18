from __future__ import annotations

import asyncio
import os
import sys

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorClient

from publisher import Publisher
from sources import build_sources
from sources.base import Source

load_dotenv()

REQUEST_TIMEOUT = 30.0
DEFAULT_SEND_DELAY = 2.0

dp = Dispatcher()


def make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
        ),
        headers={"User-Agent": "Mozilla/5.0 (compatible; news-worker/1.0)"},
        follow_redirects=True,
    )


async def run_source(source: Source, publisher: Publisher) -> None:
    """Run one source on its own loop; failures never stop other sources."""
    logger.info(
        "Starting source {} (every {}s)", source.name, source.interval
    )
    while True:
        started_at = asyncio.get_running_loop().time()
        try:
            articles = await source.fetch_new()
            for article in articles:
                try:
                    await publisher.publish(article)
                except Exception:
                    logger.exception(
                        "Failed to publish {} {}", source.name,
                        article.dedup_id,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Source {} fetch failed", source.name)

        elapsed = asyncio.get_running_loop().time() - started_at
        delay = max(0.0, source.interval - elapsed)
        await asyncio.sleep(delay)


async def dry_run() -> None:
    """Fetch every source once and print what would be published."""
    http = make_http_client()
    try:
        sources = build_sources(http)
        for source in sources:
            try:
                articles = await source.fetch_new()
            except Exception:
                logger.exception("Source {} fetch failed", source.name)
                continue
            logger.info(
                "[dry-run] {}: {} articles", source.name, len(articles)
            )
            for article in articles:
                preview = article.headline or article.brief_html[:80]
                logger.info(
                    "[dry-run]   {} | {} paragraphs | {} images | {}",
                    article.dedup_id,
                    len(article.paragraphs),
                    len(article.images),
                    preview,
                )
    finally:
        await http.aclose()


async def main() -> None:
    bot_token = os.getenv("BOT_TOKEN")
    mongo_uri = os.getenv("MONGO_URI")
    chat_id = os.getenv("CHAT_ID")

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is missing from environment variables")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI is missing from environment variables")
    if not chat_id:
        raise RuntimeError("CHAT_ID is missing from environment variables")

    send_delay = float(
        os.getenv("SEND_DELAY_SECONDS", str(DEFAULT_SEND_DELAY))
    )

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    mongo = AsyncIOMotorClient(mongo_uri)
    collection = mongo.kenyans_db.published_news
    http = make_http_client()
    publisher = Publisher(
        bot=bot, collection=collection, chat_id=int(chat_id),
        send_delay=send_delay,
    )

    sources = build_sources(http)
    logger.info(
        "Starting bot with sources: {}",
        ", ".join(source.name for source in sources),
    )

    try:
        await asyncio.gather(
            dp.start_polling(bot),
            *[run_source(source, publisher) for source in sources],
        )
    finally:
        await http.aclose()
        mongo.close()
        await bot.session.close()
        logger.info("Bot resources closed")


if __name__ == "__main__":
    try:
        if "--dry-run" in sys.argv:
            asyncio.run(dry_run())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
