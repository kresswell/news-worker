from __future__ import annotations

import html as html_mod
import re

import httpx
import trafilatura
from bs4 import BeautifulSoup

BOILERPLATE_PATTERNS = [
    re.compile(r"the post .* appeared first on", re.IGNORECASE),
    re.compile(r"^read (also|more)[:.]", re.IGNORECASE),
    re.compile(r"^share this", re.IGNORECASE),
    re.compile(r"^subscribe to", re.IGNORECASE),
    re.compile(r"^leave a (comment|reply)", re.IGNORECASE),
]

JUNK_IMAGE_HINTS = (
    "logo",
    "icon",
    "avatar",
    "sprite",
    ".svg",
    "pixel",
    "tracking",
    "gravatar",
)


def clean_fragment(inner_html: str) -> str:
    """Keep text and <a> links, unwrap every other tag."""
    fragment = BeautifulSoup(f"<div>{inner_html}</div>", "html.parser")
    root = fragment.div
    for tag in root.find_all(True):
        if tag.name == "a":
            href = tag.get("href")
            tag.attrs = {"href": href} if href else {}
            continue
        tag.unwrap()
    return root.decode_contents().strip()


def paragraphs_from_html(raw: str) -> list[str]:
    """Extract paragraph fragments (may contain <a> tags) from article HTML."""
    if not raw:
        return []
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "figcaption",
                              "summary", "aside", "form", "nav", "footer"]):
        tag.decompose()

    paragraphs: list[str] = []
    for element in soup.find_all(["p", "li", "h2", "h3"]):
        fragment = clean_fragment(element.decode_contents())
        text = re.sub(r"<[^>]*>", "", fragment)
        text = html_mod.unescape(text).strip()
        if len(text) < 3:
            continue
        if any(pattern.search(text) for pattern in BOILERPLATE_PATTERNS):
            continue
        if fragment and fragment not in paragraphs:
            paragraphs.append(fragment)
    return paragraphs


def images_from_html(raw: str, limit: int = 6) -> list[str]:
    if not raw:
        return []
    soup = BeautifulSoup(raw, "html.parser")
    images: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        src = html_mod.unescape(src).strip()
        if not src.startswith("http"):
            continue
        lowered = src.lower()
        if any(hint in lowered for hint in JUNK_IMAGE_HINTS):
            continue
        if src not in images:
            images.append(src)
    return images[:limit]


async def extract_page(
    client: httpx.AsyncClient, url: str
) -> tuple[list[str], list[str]]:
    """Fetch an article page and extract paragraphs + images from it."""
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    raw = response.text

    paragraphs: list[str] = []
    extracted = trafilatura.extract(
        raw,
        include_links=True,
        include_images=False,
        output_format="html",
        with_metadata=False,
    )
    if extracted:
        paragraphs = paragraphs_from_html(extracted)

    return paragraphs, images_from_html(raw)
