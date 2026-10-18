from __future__ import annotations

from abc import ABC, abstractmethod

from models import Article


class Source(ABC):
    """A news website (or feed) that yields normalized articles."""

    name: str
    interval: int = 60

    @abstractmethod
    async def fetch_new(self) -> list[Article]:
        """Fetch candidates, newest first.

        Already-published items may be included; the publisher filters them.
        """
