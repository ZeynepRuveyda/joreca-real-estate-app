import os
import hashlib
from pathlib import Path
from typing import List, Dict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Use a relative path for Streamlit Cloud and local dev
DEFAULT_SQLITE = "sqlite:///data/listings.db"
DB_PATH = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)


def get_engine() -> Engine:
    # Ensure data directory exists for file-based SQLite
    if DB_PATH.startswith("sqlite") and ":memory:" not in DB_PATH:
        data_dir = Path("data")
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return create_engine(DB_PATH, future=True)


def create_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT,
                url TEXT UNIQUE,
                price INTEGER,
                city TEXT,
                postal_code TEXT,
                listing_type TEXT,
                property_type TEXT,
                rooms INTEGER,
                surface FLOAT,
                agency_or_private TEXT,
                description TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        ))


def _stable_id(row: Dict) -> str:
    raw = f"{row.get('source','')}|{row.get('url','')}|{row.get('title','')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def upsert_listings(engine: Engine, rows: List[Dict]) -> None:
    if not rows:
        return
    rows_to_write = []
    for r in rows:
        rid = r.get("id") or _stable_id(r)
        r = {**r, "id": rid}
        rows_to_write.append(r)
    with engine.begin() as conn:
        for row in rows_to_write:
            conn.execute(text(
                """
                INSERT INTO listings (
                    id, source, title, url, price, city, postal_code, listing_type,
                    property_type, rooms, surface, agency_or_private, description
                ) VALUES (
                    :id, :source, :title, :url, :price, :city, :postal_code, :listing_type,
                    :property_type, :rooms, :surface, :agency_or_private, :description
                )
                ON CONFLICT(id) DO UPDATE SET
                    source=excluded.source,
                    title=excluded.title,
                    url=excluded.url,
                    price=excluded.price,
                    city=excluded.city,
                    postal_code=excluded.postal_code,
                    listing_type=excluded.listing_type,
                    property_type=excluded.property_type,
                    rooms=excluded.rooms,
                    surface=excluded.surface,
                    agency_or_private=excluded.agency_or_private,
                    description=excluded.description
                ;
                """
            ), row)
