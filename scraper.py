"""
Ekantipur.com scraper - Audio Bee Data Extraction practical test.

Extracts top 5 entertainment articles and the homepage "Cartoon of the Day".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Browser, Page, sync_playwright

OUTPUT = Path(__file__).resolve().parent / "output.json"
BASE_URL = "https://ekantipur.com"
ENTERTAINMENT_URL = f"{BASE_URL}/entertainment"
CARTOON_URL = f"{BASE_URL}/cartoon"
DEFAULT_CATEGORY = "मनोरञ्जन"
TOP_N = 5


def log(message: str) -> None:
    print(message, flush=True)


def dismiss_modal(page: Page) -> bool:
    """Close the subscription/ad gate so navigation and clicks work."""
    for selector in (
        "#pagegate button.close",
        "#pagegate .close",
        '[data-dismiss="modal"]',
        "#pagegate .btn-close",
    ):
        btn = page.locator(selector).first
        if btn.count():
            try:
                btn.click(timeout=2_000)
                page.wait_for_timeout(400)
                log("  Closed popup modal (#pagegate)")
                return True
            except Exception:
                pass
    page.keyboard.press("Escape")
    return False


def normalize_url(url: str | None) -> str | None:
    if not url or url.startswith("data:"):
        return None
    url = url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(BASE_URL, url)
    return url


def image_url_from_locator(locator) -> str | None:
    """Read thumbnail/post image URL from img or parent anchor."""
    for attr in ("src", "data-src"):
        value = locator.get_attribute(attr)
        if value and "kantipur-logo" not in value:
            return normalize_url(value)
    parent = locator.locator("xpath=ancestor::a[1]")
    if parent.count():
        return normalize_url(parent.first.get_attribute("href"))
    return None


def text_or_none(locator) -> str | None:
    if not locator.count():
        return None
    text = (locator.text_content() or "").strip()
    return text or None


def category_from_article(browser: Browser, article_url: str) -> str:
    """Article pages expose section label in .category-name."""
    detail = browser.new_page()
    try:
        log(f"    Fetching category from article page...")
        detail.goto(article_url, wait_until="domcontentloaded", timeout=60_000)
        detail.wait_for_timeout(1_500)
        dismiss_modal(detail)
        label = text_or_none(detail.locator(".category-name").first)
        category = label or DEFAULT_CATEGORY
        log(f"    Category: {category}")
        return category
    except Exception as exc:
        log(f"    Category lookup failed ({exc}); using default: {DEFAULT_CATEGORY}")
        return DEFAULT_CATEGORY
    finally:
        detail.close()


def parse_cartoon_author(description: str) -> str | None:
    """Parse 'गजब छ बा! - अविन' -> 'अविन'."""
    if " - " not in description:
        return None
    author = description.split(" - ", 1)[1].strip()
    return author or None


def cartoon_author_from_archive(browser: Browser) -> str | None:
    """Latest cartoon on /cartoon lists cartoonist after 'title - author'."""
    detail = browser.new_page()
    try:
        log(f"  Checking cartoonist on {CARTOON_URL} ...")
        detail.goto(CARTOON_URL, wait_until="domcontentloaded", timeout=60_000)
        detail.wait_for_timeout(2_000)
        dismiss_modal(detail)
        desc = text_or_none(
            detail.locator(".cartoon-wrapper").first.locator(".cartoon-description p").first
        )
        author = parse_cartoon_author(desc) if desc else None
        if author:
            log(f"  Cartoonist found: {author}")
        else:
            log("  No cartoonist name on latest /cartoon entry (author = null)")
        return author
    except Exception as exc:
        log(f"  Cartoonist lookup failed: {exc}")
        return None
    finally:
        detail.close()


def extract_entertainment(browser: Browser, page: Page) -> list[dict]:
    log(f"\n[Task 1] Entertainment news — loading {ENTERTAINMENT_URL}")
    page.goto(ENTERTAINMENT_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_selector(".category-inner-wrapper", timeout=30_000)
    page.wait_for_timeout(2_000)
    dismiss_modal(page)
    log("  Page loaded; article cards found")

    articles: list[dict] = []
    wrappers = page.locator(".category-inner-wrapper").all()[:TOP_N]
    log(f"  Extracting top {len(wrappers)} articles...\n")

    for index, card in enumerate(wrappers, start=1):
        title_link = card.locator("h2 a").first
        title = text_or_none(title_link)
        if not title:
            log(f"  [{index}/{TOP_N}] Skipped — no title found")
            continue

        log(f"  [{index}/{TOP_N}] {title}")

        article_url = normalize_url(title_link.get_attribute("href"))
        author = text_or_none(card.locator(".author-name a").first)
        log(f"    Author: {author or 'null'}")

        img = card.locator(".category-image img").first
        image_url = image_url_from_locator(img) if img.count() else None
        log(f"    Image: {'OK' if image_url else 'missing'}")

        category = DEFAULT_CATEGORY
        if article_url:
            category = category_from_article(browser, article_url)

        articles.append(
            {
                "title": title,
                "image_url": image_url,
                "category": category,
                "author": author,
            }
        )
        log(f"    Article {index} saved.\n")

    log(f"[Task 1] Done — {len(articles)} entertainment articles fetched successfully")
    return articles


def extract_cartoon_of_the_day(browser: Browser, page: Page) -> dict:
    log(f"\n[Task 2] Cartoon of the day — loading {BASE_URL}")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_selector(".cartoon-slider", timeout=30_000)
    page.wait_for_timeout(3_000)
    dismiss_modal(page)
    log("  Homepage loaded; cartoon slider ready")

    slide = page.locator(".cartoon-slider .swiper-slide-active").first
    if not slide.count():
        slide = page.locator(".cartoon-slider .swiper-slide").first
        log("  Using first slide (active slide not found)")

    img = slide.locator("img").first
    title = (img.get_attribute("alt") if img.count() else None) or ""
    title = title.strip() or None

    image_url = None
    if img.count():
        image_url = image_url_from_locator(img)
    if not image_url:
        image_url = normalize_url(slide.locator("a").first.get_attribute("href"))

    log(f"  Title: {title or 'null'}")
    log(f"  Image: {'OK' if image_url else 'missing'}")

    author = cartoon_author_from_archive(browser)

    log("[Task 2] Done — cartoon of the day fetched successfully")
    return {
        "title": title,
        "image_url": image_url,
        "author": author,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    log("=" * 50)
    log("Ekantipur scraper started")
    log("=" * 50)

    data = {
        "entertainment_news": [],
        "cartoon_of_the_day": {
            "title": None,
            "image_url": None,
            "author": None,
        },
    }

    with sync_playwright() as playwright:
        log("\nLaunching Chromium (headless)...")
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(60_000)
            log("Browser ready\n")

            data["entertainment_news"] = extract_entertainment(browser, page)
            data["cartoon_of_the_day"] = extract_cartoon_of_the_day(browser, page)
        finally:
            browser.close()
            log("\nBrowser closed")

    log(f"\nWriting results to {OUTPUT} ...")
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log("=" * 50)
    log("All tasks completed successfully")
    log(f"  Entertainment articles: {len(data['entertainment_news'])}")
    log(f"  Cartoon title: {data['cartoon_of_the_day']['title'] or 'null'}")
    log(f"  Output file: {OUTPUT}")
    log("=" * 50)


if __name__ == "__main__":
    main()
