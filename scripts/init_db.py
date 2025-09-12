#!/usr/bin/env python3
from src.utils.db import get_engine, create_tables

if __name__ == "__main__":
    engine = get_engine()
    create_tables(engine)
    print("DB initialized.")
