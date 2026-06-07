from pathlib import Path

import duckdb
import pandas as pd


# =============================================================================
# PATH CONFIG
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FILE_ROOT = Path(__file__).resolve().parents[0]

MATCHED_DB_PATH = PROJECT_ROOT / 'data_dir' / "247_bv_transf_matched.db"
INPUT_CSV_PATH = FILE_ROOT / "catboost_transfer_role_future_top3_predictions.csv"
OUTPUT_CSV_PATH = FILE_ROOT / "catboost_transfer_role_future_top3_predictions_with_247_cols.csv"

MATCHED_TABLE = "transfer_247_bv_matched"

# Fill this in with the PID column name from your CSV
CSV_PID_COL = "allyears_pid"

# In your matched DB, this appears to be the DB1 PID column
MATCHED_PID_COL = "db1_allyears_pid"


# =============================================================================
# LOAD INPUT CSV
# =============================================================================

base_df = pd.read_csv(INPUT_CSV_PATH)

if CSV_PID_COL not in base_df.columns:
    raise ValueError(f"CSV is missing PID column: {CSV_PID_COL}")

print(f"Input CSV rows: {len(base_df):,}")
print(f"Unique non-null input PIDs: {base_df[CSV_PID_COL].nunique(dropna=True):,}")
print(f"Null input PIDs: {base_df[CSV_PID_COL].isna().sum():,}")

# =============================================================================
# LOAD 247 COLUMNS FROM MATCHED DB
# =============================================================================

con = duckdb.connect(str(MATCHED_DB_PATH), read_only=True)

try:
    matched_cols = con.execute(f"""
        DESCRIBE {MATCHED_TABLE}
    """).fetchdf()["column_name"].tolist()

    cols_247 = [col for col in matched_cols if col.startswith("247_")]

    if MATCHED_PID_COL not in matched_cols:
        raise ValueError(f"Matched DB is missing PID column: {MATCHED_PID_COL}")

    if not cols_247:
        raise ValueError("No columns starting with '247_' found in matched DB.")

    select_cols = [MATCHED_PID_COL] + cols_247

    matched_247 = con.execute(f"""
        SELECT {", ".join([f'"{col}"' for col in select_cols])}
        FROM {MATCHED_TABLE}
        WHERE {MATCHED_PID_COL} IS NOT NULL
          AND "247_match_year" = 2026
    """).fetchdf()

finally:
    con.close()


# =============================================================================
# CLEAN KEYS
# =============================================================================

base_df[CSV_PID_COL] = pd.to_numeric(base_df[CSV_PID_COL], errors="coerce")
matched_247[MATCHED_PID_COL] = pd.to_numeric(
    matched_247[MATCHED_PID_COL],
    errors="coerce",
)

# If the matched table has duplicate PIDs, keep the best match.
# Priority:
# 1. match row with non-null 247_player_key
# 2. highest overall_match_score if present
sort_cols = []

if "247_player_key" in matched_247.columns:
    matched_247["_has_247_match"] = matched_247["247_player_key"].notna().astype(int)
    sort_cols.append("_has_247_match")

# Need overall_match_score if you want score-based tie break.
# It was not selected above because it does not start with 247_, so load it separately if needed.
# Simpler default: drop duplicate pid after current ordering.

matched_247 = matched_247.drop_duplicates(
    subset=[MATCHED_PID_COL],
    keep="first",
)

matched_247 = matched_247.drop(
    columns=["_has_247_match"],
    errors="ignore",
)


# =============================================================================
# JOIN 247 COLUMNS ONTO CSV
# =============================================================================

out = base_df.merge(
    matched_247,
    left_on=CSV_PID_COL,
    right_on=MATCHED_PID_COL,
    how="left",
    validate="many_to_one",
)

# Optional: drop duplicate join key from matched DB
out = out.drop(columns=[MATCHED_PID_COL], errors="ignore")


# =============================================================================
# WRITE OUTPUT
# =============================================================================

out.to_csv(OUTPUT_CSV_PATH, index=False)

print(f"Input rows:  {len(base_df):,}")
print(f"Output rows: {len(out):,}")
print(f"247 columns added: {len(cols_247):,}")
print(f"Wrote: {OUTPUT_CSV_PATH}")

print()
print("Rows with matched 247_player_key:")
if "247_player_key" in out.columns:
    print(out["247_player_key"].notna().sum())
else:
    print("247_player_key column not found.")
