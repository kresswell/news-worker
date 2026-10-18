from __future__ import annotations

import os

from loguru import logger

from sources.base import Source
from sources import citizen, ghafla, nation, standard, kbc
from sources.kenyans import KenyansNewsSource, KenyansTrackerSource

import httpx


def build_sources(client: httpx.AsyncClient) -> list[Source]:
    """Instantiate every source, then keep only the enabled ones."""
    sources: list[Source] = [
        KenyansNewsSource(client),
        KenyansTrackerSource(client),
        citizen.build(client),
        ghafla.build(client),
        nation.build(client),
        standard.build(client),
        kbc.build(client),
    ]

    enabled = os.getenv("ENABLED_SOURCES", "").strip()
    if not enabled:
        return sources

    allowed = {name.strip() for name in enabled.split(",") if name.strip()}
    selected = [source for source in sources if source.name in allowed]

    unknown = allowed - {source.name for source in sources}
    if unknown:
        logger.warning("Unknown source names in ENABLED_SOURCES: {}", unknown)

    return selected
