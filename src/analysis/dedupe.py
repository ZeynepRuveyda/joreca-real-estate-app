import re
import hashlib
import pandas as pd


def normalize_title(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fingerprint(row: dict) -> str:
    # Safely extract and convert all values to strings
    title = str(row.get("title") or "")
    city = str(row.get("city") or "")
    price = str(row.get("price") or "")
    surface = str(row.get("surface") or "")
    rooms = str(row.get("rooms") or "")
    
    # Join all parts safely
    combined = f"{title}|{city}|{price}|{surface}|{rooms}"
    norm = normalize_title(combined)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def mark_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["_fingerprint"] = df.apply(lambda r: fingerprint(r.to_dict()), axis=1)
    df["is_duplicate"] = df.duplicated(subset=["_fingerprint"], keep="first")
    return df
