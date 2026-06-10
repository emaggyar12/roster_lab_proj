import json
import re
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from catboost import CatBoostRegressor, Pool


# ============================================================
# USER SETTINGS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# CHANGE THIS
DB_PATH = PROJECT_ROOT / "data_dir" / "hs_complete.db"

# CHANGE THIS
TABLE_NAME = "hs_complete"

# CHANGE THIS to your trained production model path.
# Prefer the production train+valid model if you accepted CatBoost as final.
MODEL_PATH = Path(
    'catboost_bpr_outputs/catboost_run_20260607_141842/catboost_bpr_production_train_valid_model.cbm'
)

OUTPUT_DIR = Path("catboost_bpr_inference_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Optional: output predictions back into DuckDB.
WRITE_PREDICTIONS_TO_DB = False
OUTPUT_TABLE_NAME = "bpr_predictions"

# Optional ID / metadata columns to preserve if they exist in the inference table.
# Add/remove based on your actual table.
OPTIONAL_ID_COLS = [
    "player_id",
    "allyears_pid",
    "player_name",
    "full_name",
    "year",
    "team",
    "school",
    "school_fin",
    "position",
]


# ============================================================
# MODEL FEATURE SETTINGS
# ============================================================

FEATURES = [
    "hs_year",
    "hs_position",
    "hs_weight",
    "hs_stars",
    "hs_rating",
    "hs_national_rank",
    "hs_position_rank",
    "hs_state_rank",
    "hs_height_in",
    "hs_hometown_state",
    "hs_school_fin",
]

NUMERIC_FEATURES = [
    "hs_year",
    "hs_weight",
    "hs_stars",
    "hs_rating",
    "hs_national_rank",
    "hs_position_rank",
    "hs_state_rank",
    "hs_height_in",
]

CATEGORICAL_FEATURES = [
    "hs_position",
    "hs_hometown_state",
    "hs_school_fin",
]

PRED_COL = "predicted_college_basic_bpr"


# ============================================================
# COLUMN MAPPING
# ============================================================
# Inference DB columns do NOT have hs_ prefix.
# Script aliases them back to the trained model feature names.

SOURCE_TO_MODEL_COLS = {
    "year": "hs_year",
    "position": "hs_position",
    "height": "hs_height",
    "height_in": "hs_height_in",
    "weight": "hs_weight",
    "stars": "hs_stars",
    "rating": "hs_rating",
    "national_rank": "hs_national_rank",
    "position_rank": "hs_position_rank",
    "state_rank": "hs_state_rank",
    "hometown_state": "hs_hometown_state",
    "hs_school_fin": "hs_school_fin",
}


# ============================================================
# HELPERS
# ============================================================

def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_table_columns(con, table_name: str) -> list[str]:
    rows = con.execute(f"DESCRIBE {qident(table_name)}").fetchall()
    return [row[0] for row in rows]


def parse_height_to_inches(value):
    """
    Parses common basketball height formats:
    - 6-7
    - 6'7
    - 6' 7"
    - 6 7
    - 79
    Returns height in inches or NaN.
    """
    if pd.isna(value):
        return np.nan

    s = str(value).strip()

    if s == "":
        return np.nan

    try:
        x = float(s)
        if 48 <= x <= 96:
            return x
    except ValueError:
        pass

    s = s.lower()
    s = s.replace("ft", "'")
    s = s.replace("feet", "'")
    s = s.replace("inches", "")
    s = s.replace("inch", "")
    s = s.replace('"', "")
    s = s.replace("’", "'")
    s = s.replace("`", "'")

    match = re.search(r"(\d+)\s*[-'\s]\s*(\d+)", s)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2))
        total = feet * 12 + inches
        if 48 <= total <= 96:
            return float(total)

    return np.nan


def ensure_height_in(df: pd.DataFrame, log=None) -> pd.DataFrame:
    """
    Ensures hs_height_in exists where possible.

    The inference DB should have:
      height
      height_in

    The query aliases those to:
      hs_height
      hs_height_in
    """
    df = df.copy()

    if "hs_height_in" not in df.columns:
        df["hs_height_in"] = np.nan

    if "hs_height" not in df.columns:
        msg = "WARNING: hs_height column not found. Cannot backfill hs_height_in."
        if log:
            log(msg)
        else:
            print(msg)
        return df

    before_missing = df["hs_height_in"].isna().sum()
    parsed_height = df["hs_height"].apply(parse_height_to_inches)

    needs_fill = df["hs_height_in"].isna() & parsed_height.notna()
    df.loc[needs_fill, "hs_height_in"] = parsed_height.loc[needs_fill]

    after_missing = df["hs_height_in"].isna().sum()

    lines = [
        "\nHeight validation:",
        f"Rows with non-null hs_height: {df['hs_height'].notna().sum()}",
        f"Missing hs_height_in before backfill: {before_missing}",
        f"Filled hs_height_in from hs_height: {needs_fill.sum()}",
        f"Missing hs_height_in after backfill: {after_missing}",
    ]

    for line in lines:
        if log:
            log(line)
        else:
            print(line)

    return df


def prepare_catboost_inference_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Match training-time dtypes:
    - numeric features converted to numeric
    - categorical features filled and cast to string
    """
    df = df.copy()

    for col in NUMERIC_FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in CATEGORICAL_FEATURES:
        if col in df.columns:
            df[col] = df[col].astype("string").fillna("__MISSING__").astype(str)
            df[col] = df[col].replace(
                {
                    "<NA>": "__MISSING__",
                    "nan": "__MISSING__",
                    "None": "__MISSING__",
                    "": "__MISSING__",
                }
            )

    return df


def make_prediction_pool(df: pd.DataFrame) -> Pool:
    return Pool(
        data=df[FEATURES],
        cat_features=CATEGORICAL_FEATURES,
    )


def build_inference_query(existing_cols: list[str]) -> str:
    """
    Builds SELECT query using source columns without hs_ prefix,
    aliasing them back to hs_* model columns.

    Example:
      year AS hs_year
      position AS hs_position
      school_fin AS hs_school_fin
    """
    select_parts = []

    # Preserve optional ID / metadata columns if available.
    for col in OPTIONAL_ID_COLS:
        if col in existing_cols:
            select_parts.append(f"{qident(col)} AS {qident(col)}")

    # Required model columns from prefixless source columns.
    missing_source_cols = []

    for source_col, model_col in SOURCE_TO_MODEL_COLS.items():
        if source_col in existing_cols:
            select_parts.append(f"{qident(source_col)} AS {qident(model_col)}")
        else:
            missing_source_cols.append(source_col)

    if missing_source_cols:
        raise ValueError(
            "Missing required source columns in inference table: "
            + ", ".join(missing_source_cols)
        )

    query = f"""
    SELECT
        {", ".join(select_parts)}
    FROM {qident(TABLE_NAME)}
    WHERE year = 2026
    ;
    """

    return query


def json_safe(obj):
    if isinstance(obj, Path):
        return str(obj)

    if isinstance(obj, (np.integer,)):
        return int(obj)

    if isinstance(obj, (np.floating,)):
        return float(obj)

    if isinstance(obj, np.ndarray):
        return obj.tolist()

    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [json_safe(v) for v in obj]

    return obj


# ============================================================
# MAIN
# ============================================================

def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"catboost_bpr_inference_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "inference_log.txt"

    def log(msg: str):
        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting CatBoost BPR inference")
    log(f"Run directory: {run_dir}")
    log(f"DB path: {DB_PATH}")
    log(f"Table name: {TABLE_NAME}")
    log(f"Model path: {MODEL_PATH}")

    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB_PATH does not exist: {DB_PATH}")

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"MODEL_PATH does not exist: {MODEL_PATH}")

    # ----------------------------
    # Load inference data
    # ----------------------------

    con = duckdb.connect(str(DB_PATH))
    existing_cols = get_table_columns(con, TABLE_NAME)

    log("\nExisting table columns:")
    log(str(existing_cols))

    query = build_inference_query(existing_cols)

    log("\nInference query:")
    log(query)

    df = con.execute(query).fetchdf()

    log(f"\nRows loaded for inference: {len(df):,}")
    log(f"Columns loaded: {list(df.columns)}")

    raw_loaded_path = run_dir / "loaded_inference_rows.csv"
    df.to_csv(raw_loaded_path, index=False)
    log(f"Saved loaded rows: {raw_loaded_path}")

    # ----------------------------
    # Validate / prepare features
    # ----------------------------

    df = ensure_height_in(df, log=log)
    df = prepare_catboost_inference_frame(df)

    missing_model_features = [c for c in FEATURES if c not in df.columns]
    if missing_model_features:
        raise ValueError(f"Missing model features after preparation: {missing_model_features}")

    feature_null_report = (
        df[FEATURES]
        .isna()
        .mean()
        .sort_values(ascending=False)
        .reset_index()
    )
    feature_null_report.columns = ["feature", "missing_rate"]

    feature_null_report_path = run_dir / "inference_feature_missingness.csv"
    feature_null_report.to_csv(feature_null_report_path, index=False)

    log("\nInference feature missingness:")
    log(feature_null_report.to_string(index=False))

    # ----------------------------
    # Load model
    # ----------------------------

    model = CatBoostRegressor()
    model.load_model(str(MODEL_PATH))

    log("\nLoaded CatBoost model.")

    # ----------------------------
    # Predict
    # ----------------------------

    pred_pool = make_prediction_pool(df)
    preds = model.predict(pred_pool)

    out_df = df.copy()
    out_df[PRED_COL] = preds

    # Put prediction column near front.
    front_cols = []

    for col in OPTIONAL_ID_COLS:
        if col in out_df.columns and col not in front_cols:
            front_cols.append(col)

    front_cols.append(PRED_COL)

    remaining_cols = [c for c in out_df.columns if c not in front_cols]
    out_df = out_df[front_cols + remaining_cols]

    output_csv_path = run_dir / "bpr_predictions.csv"
    out_df.to_csv(output_csv_path, index=False)

    log(f"\nSaved predictions CSV: {output_csv_path}")

    log("\nPrediction summary:")
    log(out_df[PRED_COL].describe().to_string())

    # ----------------------------
    # Optional: write predictions to DuckDB
    # ----------------------------

    if WRITE_PREDICTIONS_TO_DB:
        con.register("predictions_df", out_df)
        con.execute(f"CREATE OR REPLACE TABLE {qident(OUTPUT_TABLE_NAME)} AS SELECT * FROM predictions_df")
        con.unregister("predictions_df")

        log(f"\nWrote predictions to DuckDB table: {OUTPUT_TABLE_NAME}")

    con.close()

    # ----------------------------
    # Save config
    # ----------------------------

    config = {
        "db_path": str(DB_PATH),
        "table_name": TABLE_NAME,
        "model_path": str(MODEL_PATH),
        "output_dir": str(OUTPUT_DIR),
        "run_dir": str(run_dir),
        "output_table_name": OUTPUT_TABLE_NAME if WRITE_PREDICTIONS_TO_DB else None,
        "prediction_col": PRED_COL,
        "features": FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "source_to_model_cols": SOURCE_TO_MODEL_COLS,
        "optional_id_cols": OPTIONAL_ID_COLS,
        "query": query,
    }

    with open(run_dir / "inference_config.json", "w", encoding="utf-8") as f:
        json.dump(json_safe(config), f, indent=2)

    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")


if __name__ == "__main__":
    main()