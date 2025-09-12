import random
import hashlib
from typing import List, Dict


_CITIES = [
    ("Paris", "75000"), ("Lyon", "69000"), ("Marseille", "13000"),
    ("Toulouse", "31000"), ("Bordeaux", "33000"), ("Lille", "59000"),
]
_PROP_TYPES = ["apartment", "house", "studio"]
_LISTING_TYPES = ["rent", "sale"]
_AGENCY_FLAGS = ["agency", "private"]


def _stable_id(row: Dict) -> str:
    raw = f"{row.get('source','')}|{row.get('title','')}|{row.get('city','')}|{row.get('price','')}|{row.get('surface','')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _random_listing(source: str) -> Dict:
    city, postal = random.choice(_CITIES)
    prop = random.choice(_PROP_TYPES)
    listing_type = random.choice(_LISTING_TYPES)
    rooms = random.randint(1, 5)
    surface = random.randint(18, 140)
    if listing_type == "rent":
        price = random.randint(400, 3500)
    else:
        price = random.randint(80000, 1200000)
    title = f"{prop.title()} {rooms} rooms {surface}m2 in {city}"
    agency_or_private = random.choices(_AGENCY_FLAGS, weights=[0.6, 0.4])[0]
    row = {
        "id": None,
        "source": source,
        "title": title,
        "url": None,
        "price": price,
        "city": city,
        "postal_code": postal,
        "listing_type": listing_type,
        "property_type": prop,
        "rooms": rooms,
        "surface": float(surface),
        "agency_or_private": agency_or_private,
        "description": None,
    }
    row["id"] = _stable_id(row)
    return row


def generate_mock_rows(total: int = 40, duplicate_ratio: float = 0.25) -> List[Dict]:
    if total <= 0:
        return []
    base: List[Dict] = []
    # Half from each source initially
    for _ in range(max(1, total // 2)):
        base.append(_random_listing("seloger"))
    for _ in range(total - len(base)):
        base.append(_random_listing("leboncoin"))

    # Create cross-source duplicates for a subset
    num_dups = max(0, int(len(base) * duplicate_ratio))
    dups: List[Dict] = []
    for i in range(num_dups):
        src = "seloger" if base[i]["source"] == "leboncoin" else "leboncoin"
        clone = {**base[i], "source": src}
        clone["id"] = _stable_id(clone)
        dups.append(clone)

    rows = base + dups
    random.shuffle(rows)
    return rows[:total]


def generate_enhanced_duplicates(total: int = 300, duplicate_ratio: float = 0.4) -> List[Dict]:
    """Generate more realistic data with higher duplicate ratio"""
    if total <= 0:
        return []
    
    # Create base listings
    base: List[Dict] = []
    for _ in range(max(1, total // 2)):
        base.append(_random_listing("seloger"))
    for _ in range(total - len(base)):
        base.append(_random_listing("leboncoin"))

    # Create more cross-source duplicates
    num_dups = max(0, int(len(base) * duplicate_ratio))
    dups: List[Dict] = []
    
    # Create multiple duplicates of the same property
    for i in range(num_dups):
        # Original property
        original = base[i]
        
        # Create 1-2 duplicates of the same property on different sites
        for dup_count in range(random.randint(1, 2)):
            src = "seloger" if original["source"] == "leboncoin" else "leboncoin"
            clone = {**original, "source": src}
            
            # Add slight variations to make it more realistic
            if random.random() < 0.3:  # 30% chance of price variation
                price_diff = random.randint(-50, 50)
                clone["price"] = max(0, clone["price"] + price_diff)
            
            if random.random() < 0.2:  # 20% chance of missing some fields
                missing_field = random.choice(["surface", "rooms", "agency_or_private"])
                clone[missing_field] = None
            
            clone["id"] = _stable_id(clone)
            dups.append(clone)

    rows = base + dups
    random.shuffle(rows)
    return rows[:total]


def generate_curated_duplicates(num_pairs: int = 4) -> List[Dict]:
    pairs: List[Dict] = []
    for i in range(num_pairs):
        city, postal = random.choice(_CITIES)
        prop = random.choice(_PROP_TYPES)
        rooms = random.randint(1, 4)
        surface = random.choice([42, 55, 68, 75, 90])
        price_base = random.choice([950, 1200, 185000, 320000, 540000])
        listing_type = random.choice(_LISTING_TYPES)
        title = f"{prop.title()} {rooms} rooms {surface}m2 in {city}"

        a = {
            "id": None,
            "source": "seloger",
            "title": title,
            "url": None,
            "price": price_base,
            "city": city,
            "postal_code": postal,
            "listing_type": listing_type,
            "property_type": prop,
            "rooms": rooms,
            "surface": float(surface),
            "agency_or_private": "agency",
            "description": None,
        }
        a["id"] = _stable_id(a)

        # Same home on the other site, but with some missing or slightly different info
        b = {
            **a,
            "source": "leboncoin",
            # introduce minor variations and missing fields
            "price": price_base + random.choice([0, 10, 50, -10, -50]),
            "agency_or_private": "private" if random.random() < 0.3 else a["agency_or_private"],
        }
        # Randomly drop a field to simulate missing info
        drop_field = random.choice(["price", "surface", "rooms", "postal_code", "title"])
        b[drop_field] = None
        b["id"] = _stable_id(b)

        pairs.extend([a, b])
    return pairs


