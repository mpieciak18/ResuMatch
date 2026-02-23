import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Minimum characters of meaningful text to consider a static scrape successful
MIN_CONTENT_LENGTH = 100

# Maximum characters to return (keeps Gemini token usage reasonable)
MAX_CONTENT_LENGTH = 50_000

STATIC_TIMEOUT = 15.0  # seconds
PLAYWRIGHT_TIMEOUT = 30_000  # milliseconds

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning(
        "Playwright not installed; JS-heavy page scraping will be unavailable"
    )


class ScrapeError(Exception):
    """Raised when scraping fails completely."""


def _validate_url(url: str) -> str:
    """Validate and normalise the URL. Returns cleaned URL or raises ScrapeError."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ScrapeError(
            "Invalid URL. Please provide a valid HTTP or HTTPS URL."
        )
    if not parsed.netloc:
        raise ScrapeError(
            "Invalid URL. Please provide a valid HTTP or HTTPS URL."
        )
    return url


def _extract_text_from_html(html: str) -> str:
    """Parse HTML with BeautifulSoup, strip boilerplate, return text."""
    soup = BeautifulSoup(html, "lxml")

    # Remove elements that are unlikely to contain job description content
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Collapse runs of blank lines into a single newline
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text[:MAX_CONTENT_LENGTH]


async def _fetch_static(url: str) -> str:
    """Fetch URL with httpx, parse with BeautifulSoup, return extracted text."""
    async with httpx.AsyncClient(
        timeout=STATIC_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

    return _extract_text_from_html(response.text)


async def _fetch_with_playwright(url: str) -> str:
    """Fetch URL with Playwright (headless Chromium), return extracted text."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent=_USER_AGENT)
            await page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT)
            html = await page.content()
        finally:
            await browser.close()

    return _extract_text_from_html(html)


async def scrape_job_listing(url: str) -> str:
    """Scrape a job listing URL.

    Tries a static fetch first, then falls back to Playwright for JS-heavy
    pages.  Raises ``ScrapeError`` if both approaches fail.
    """
    url = _validate_url(url)

    # --- Attempt 1: static fetch ---
    try:
        text = await _fetch_static(url)
        if len(text.strip()) >= MIN_CONTENT_LENGTH:
            logger.info("Static scrape succeeded for %s (%d chars)", url, len(text))
            return text
        logger.info("Static scrape returned insufficient content, trying Playwright")
    except ScrapeError:
        raise  # validation errors should not be retried
    except Exception as exc:
        logger.warning("Static fetch failed for %s: %s", url, exc)

    # --- Attempt 2: Playwright ---
    if not PLAYWRIGHT_AVAILABLE:
        raise ScrapeError(
            "Could not fetch enough content from the provided URL and "
            "Playwright is not installed for JS-heavy page support. "
            "Please paste the job description manually instead."
        )

    try:
        text = await _fetch_with_playwright(url)
        if len(text.strip()) >= MIN_CONTENT_LENGTH:
            logger.info("Playwright scrape succeeded for %s (%d chars)", url, len(text))
            return text
        raise ScrapeError(
            "The page did not contain enough text content to identify a job listing. "
            "Please paste the job description manually instead."
        )
    except ScrapeError:
        raise
    except Exception as exc:
        logger.error("Playwright fetch also failed for %s: %s", url, exc)
        raise ScrapeError(
            "Could not fetch job listing from the provided URL. "
            "Please paste the job description manually instead."
        ) from exc
