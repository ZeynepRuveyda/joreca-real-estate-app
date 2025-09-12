#!/usr/bin/env python3
import os
import pandas as pd
from src.scrapers import scrape_seloger, scrape_leboncoin
from src.utils.db import get_engine, create_tables, upsert_listings
from src.utils.io import export_to_excel
from src.analysis.dedupe import mark_duplicates
from src.analysis.visualize import plot_overview
from src.utils.mock_data import generate_mock_rows

LIMIT = int(os.environ.get("SCRAPE_LIMIT", "30"))
USE_MOCK = os.environ.get("USE_MOCK", "0") == "1"
EXCEL_PATH = "/home/zeynep/Desktop/joreca/data/listings.xlsx"
FIGDIR = "/home/zeynep/Desktop/joreca/data/figures"


def main():
    engine = get_engine()
    create_tables(engine)

    if USE_MOCK:
        rows = generate_mock_rows(total=LIMIT * 2, duplicate_ratio=0.3)
    else:
        se_rows = scrape_seloger(limit=LIMIT)
        lb_rows = scrape_leboncoin(limit=LIMIT)
        rows = se_rows + lb_rows
    upsert_listings(engine, rows)

    export_to_excel(EXCEL_PATH)
    df = pd.read_excel(EXCEL_PATH)
    df = mark_duplicates(df)
    df.to_excel(EXCEL_PATH, index=False)

    os.makedirs(FIGDIR, exist_ok=True)
    plot_overview(df, FIGDIR)
    print(f"Done. Rows: {len(df)} | Excel: {EXCEL_PATH} | Figures: {FIGDIR}")


if __name__ == "__main__":
    main()
