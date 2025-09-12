#!/usr/bin/env python3
import os
from src.analysis.diff import export_differences

DIFF_XLSX = "/home/zeynep/Desktop/joreca/data/source_differences.xlsx"
CSV_DIR = "/home/zeynep/Desktop/joreca/data"


def main():
    os.makedirs(CSV_DIR, exist_ok=True)
    export_differences(DIFF_XLSX, CSV_DIR)
    print(f"Exported differences to: {DIFF_XLSX} and CSVs in {CSV_DIR}")


if __name__ == "__main__":
    main()


