import pandas as pd
from sqlalchemy import text
from src.utils.db import get_engine


def export_to_excel(path: str) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        df = pd.read_sql(text("SELECT * FROM listings"), conn)
    df.to_excel(path, index=False)


def import_from_excel(path: str) -> pd.DataFrame:
    return pd.read_excel(path)
