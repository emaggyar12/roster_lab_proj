from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

try:
    from cache_247_transfer_profiles import CACHE_BASE_ROOT, PROJECT_ROOT, run_for_year
except ModuleNotFoundError:
    from .cache_247_transfer_profiles import CACHE_BASE_ROOT, PROJECT_ROOT, run_for_year


YEARS = list(range(2018, 2027))
OUTPUT_DB = PROJECT_ROOT / "data_dir" / "247_transfer.db"


def main() -> None:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        print(f"Running transfer profile cache for {year}", flush=True)
        frame = run_for_year(year)
        frame["year"] = year
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    OUTPUT_DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(OUTPUT_DB))
    try:
        con.execute("DROP TABLE IF EXISTS transfer_profile_cache")
        con.register("combined_df", combined)
        con.execute("CREATE TABLE transfer_profile_cache AS SELECT * FROM combined_df")
        con.execute("CHECKPOINT")
    finally:
        con.close()

    combined_csv = CACHE_BASE_ROOT / "transfer_profile_cache_2018_2026.csv"
    combined.to_csv(combined_csv, index=False)
    print(f"Wrote {OUTPUT_DB}")
    print(f"Wrote {combined_csv}")
    print(f"Rows: {len(combined)}")


if __name__ == "__main__":
    main()
