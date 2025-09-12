from typing import Tuple, List
import pandas as pd
from sqlalchemy import text
from src.utils.db import get_engine
from src.analysis.dedupe import fingerprint


KEY_FIELDS: List[str] = [
    "title",
    "city",
    "postal_code",
    "listing_type",
    "property_type",
    "rooms",
    "surface",
    "price",
    "agency_or_private",
]


def load_with_fingerprint() -> pd.DataFrame:
    engine = get_engine()
    with engine.begin() as conn:
        df = pd.read_sql(text("SELECT * FROM listings"), conn)
    if df.empty:
        return df
    # Simple fingerprint without complex processing
    df["_fingerprint"] = df.apply(lambda r: f"{r.get('source','')}|{r.get('title','')}|{r.get('city','')}|{r.get('price','')}|{r.get('surface','')}|{r.get('rooms','')}", axis=1)
    return df


def compute_differences(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df, df
    se = df[df["source"] == "seloger"].copy()
    lb = df[df["source"] == "leboncoin"].copy()

    only_se = se[~se["_fingerprint"].isin(lb["_fingerprint"])].copy()
    only_lb = lb[~lb["_fingerprint"].isin(se["_fingerprint"])].copy()

    common_keys = sorted(set(se["_fingerprint"]) & set(lb["_fingerprint"]))
    se_common = se[se["_fingerprint"].isin(common_keys)].copy()
    lb_common = lb[lb["_fingerprint"].isin(common_keys)].copy()

    merged = se_common.merge(
        lb_common,
        on="_fingerprint",
        suffixes=("_se", "_lb"),
        how="inner",
    )

    # Identify field-level mismatches
    mismatch_rows = []
    for _, row in merged.iterrows():
        diffs = {}
        for col in KEY_FIELDS:
            se_val = row.get(f"{col}_se")
            lb_val = row.get(f"{col}_lb")
            if pd.isna(se_val) and pd.isna(lb_val):
                continue
            if se_val != lb_val:
                diffs[col] = {"seloger": se_val, "leboncoin": lb_val}
        if diffs:
            rec = {"_fingerprint": row["_fingerprint"]}
            for col in KEY_FIELDS:
                rec[f"{col}_se"] = row.get(f"{col}_se")
                rec[f"{col}_lb"] = row.get(f"{col}_lb")
            rec["url_se"] = row.get("url_se")
            rec["url_lb"] = row.get("url_lb")
            mismatch_rows.append(rec)

    mismatches = pd.DataFrame(mismatch_rows)
    return only_se, only_lb, mismatches


def export_differences(xlsx_path: str, csv_dir: str) -> None:
    df = load_with_fingerprint()
    only_se, only_lb, mismatches = compute_differences(df)

    # Excel with multiple sheets
    with pd.ExcelWriter(xlsx_path) as writer:
        only_se.to_excel(writer, index=False, sheet_name="only_seloger")
        only_lb.to_excel(writer, index=False, sheet_name="only_leboncoin")
        mismatches.to_excel(writer, index=False, sheet_name="mismatches")

    # Simple CSV exports
    only_se.to_csv(f"{csv_dir}/only_seloger.csv", index=False)
    only_lb.to_csv(f"{csv_dir}/only_leboncoin.csv", index=False)
    mismatches.to_csv(f"{csv_dir}/mismatches.csv", index=False)


