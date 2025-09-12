from typing import List, Dict
import os
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from src.utils.browser import get_headless_chrome

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE_URL = "https://www.seloger.com/list.htm?projects=2,5&types=1,2&natures=1,2&price=NaN&surface=NaN&rooms=NaN&places=%5B%7Bci%3A750056%7D%5D&qsVersion=1.0"


def _parse_card(card) -> Dict:
    title = card.select_one("h2")
    title = title.get_text(strip=True) if title else None
    url_tag = card.select_one("a")
    url = ("https://www.seloger.com" + url_tag.get("href")) if url_tag and url_tag.get("href", "").startswith("/") else (url_tag.get("href") if url_tag else None)
    price_el = card.find(attrs={"data-test": "sl.price"})
    price = None
    if price_el:
        digits = "".join(ch for ch in price_el.get_text() if ch.isdigit())
        price = int(digits) if digits else None
    city_el = card.find(attrs={"data-test": "sl.address"})
    city = city_el.get_text(strip=True) if city_el else None
    prop_type = None
    listing_type = None
    rooms = None
    surface = None
    agency_or_private = None
    desc = None
    rid = hashlib.sha1(f"seloger|{url}|{title}".encode("utf-8")).hexdigest() if url or title else None
    return {
        "id": rid,
        "source": "seloger",
        "title": title,
        "url": url,
        "price": price,
        "city": city,
        "postal_code": None,
        "listing_type": listing_type,
        "property_type": prop_type,
        "rooms": rooms,
        "surface": surface,
        "agency_or_private": agency_or_private,
        "description": desc,
    }


def scrape_seloger(limit: int = 30, delay_s: float = 1.0) -> List[Dict]:
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
    cards = list(soup.select("article"))
    cards += soup.find_all(attrs={"data-test": "sl.card"})
    for card in cards:
        out.append(_parse_card(card))
        if len(out) >= limit:
            break
        time.sleep(delay_s)
    return [r for r in out if r.get("title") or r.get("url")]
