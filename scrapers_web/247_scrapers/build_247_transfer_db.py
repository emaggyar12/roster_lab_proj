from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "scrapers_web" / "247_scrapers" / "outputs"
CACHE_ROOT = PROJECT_ROOT / "scrapers_web" / "cache" / "transfers"
OUTPUT_DB = PROJECT_ROOT / "data_dir" / "247_transfer.db"


def load_year(year: int) -> pd.DataFrame:
    enriched_csv = OUT_DIR / f"transfers_247_enriched_{year}.csv"
    summary_csv = CACHE_ROOT / str(year) / f"transfer_profile_cache_summary_{year}.csv"
    if not enriched_csv.exists():
        raise FileNotFoundError(f"Missing enriched CSV: {enriched_csv}")
    if not summary_csv.exists():
        raise FileNotFoundError(f"Missing cache summary CSV: {summary_csv}")

    enriched = pd.read_csv(enriched_csv)
    cache = pd.read_csv(summary_csv)
    merged = enriched.merge(cache, on=["year", "player_key"], how="left", suffixes=("", "_cache"))
    return merged


def build_db(years: list[int]) -> pd.DataFrame:
    frames = [load_year(year) for year in years]
    combined = pd.concat(frames, ignore_index=True)
    OUTPUT_DB.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(OUTPUT_DB))
    try:
        con.execute("DROP TABLE IF EXISTS transfer_profile_cache")
        con.execute("DROP TABLE IF EXISTS transfer_profiles")
        con.register("combined_df", combined)
        con.execute("CREATE TABLE transfer_profile_cache AS SELECT * FROM combined_df")
        con.execute("CREATE TABLE transfer_profiles AS SELECT * FROM combined_df")
        con.execute("CHECKPOINT")
    finally:
        con.close()

    combined_csv = CACHE_ROOT / "transfer_profile_cache_2018_2026.csv"
    combined.to_csv(combined_csv, index=False)
    print(f"Wrote {OUTPUT_DB}")
    print(f"Wrote {combined_csv}")
    print(f"Rows: {len(combined)}")
    return combined


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()
    years = list(range(args.start_year, args.end_year + 1))
    build_db(years)


if __name__ == "__main__":
    main()
