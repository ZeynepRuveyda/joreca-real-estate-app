from typing import List, Dict
import os
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from src.utils.browser import get_headless_chrome

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE_URL = "https://www.leboncoin.fr/recherche?category=10&locations=Paris_75000"


def _parse_card(card) -> Dict:
    title_el = card.select_one("p[data-qa-id=aditem_title]") or card.select_one("h2")
    title = title_el.get_text(strip=True) if title_el else None
    url_tag = card.select_one("a")
    href = url_tag.get("href") if url_tag else None
    url = ("https://www.leboncoin.fr" + href) if href and href.startswith("/") else href
    price_el = card.select_one("span[data-qa-id=aditem_price]")
    price = None
    if price_el:
        digits = "".join(ch for ch in price_el.get_text() if ch.isdigit())
        price = int(digits) if digits else None
    city_el = card.select_one("p[data-qa-id=aditem_location]")
    city = city_el.get_text(strip=True) if city_el else None
    agency_or_private = None
    desc = None
    rid = hashlib.sha1(f"leboncoin|{url}|{title}".encode("utf-8")).hexdigest() if url or title else None
    return {
        "id": rid,
        "source": "leboncoin",
        "title": title,
        "url": url,
        "price": price,
        "city": city,
        "postal_code": None,
        "listing_type": None,
        "property_type": None,
        "rooms": None,
        "surface": None,
        "agency_or_private": agency_or_private,
        "description": desc,
    }


def scrape_leboncoin(limit: int = 30, delay_s: float = 1.0) -> List[Dict]:
    out: List[Dict] = []
    use_browser = os.environ.get("USE_BROWSER", "0") == "1"
    if use_browser:
        try:
            driver = get_headless_chrome()
            driver.get(BASE_URL)
            time.sleep(3)
            html = driver.page_source
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    else:
        try:
            resp = requests.get(BASE_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            html = resp.text
        except Exception:
            return out
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("a[data-qa-id=aditem_container], article, li[data-qa-id=aditem]")
    for card in cards:
        out.append(_parse_card(card))
        if len(out) >= limit:
            break
        time.sleep(delay_s)
    return [r for r in out if r.get("title") or r.get("url")]
