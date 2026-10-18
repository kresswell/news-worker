from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Article:
    """Normalized article produced by every source, regardless of website."""

    source: str
    dedup_id: str
    url: str = ""
    headline: str = ""
    author: str | None = None
    credit: str = ""
    paragraphs: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    style: str = "article"
    brief_html: str = ""

    @property
    def total_text_length(self) -> int:
        return sum(len(p) for p in self.paragraphs)
