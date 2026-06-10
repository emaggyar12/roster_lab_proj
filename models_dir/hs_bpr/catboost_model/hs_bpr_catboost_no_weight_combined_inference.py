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

DB_PATH = PROJECT_ROOT / "data_dir" / "hs_complete.db"
TABLE_NAME = "hs_complete"

MODEL_WITH_SCHOOL_PATH = Path(
    "catboost_bpr_no_weight_outputs/catboost_no_weight_run_20260607_151800/catboost_bpr_no_weight_production_train_valid_model.cbm"
)

MODEL_NO_SCHOOL_PATH = Path(
    "catboost_bpr_no_weight_outputs/catboost_no_weight_run_20260607_152617/catboost_bpr_no_weight_production_train_valid_model.cbm"
)

OUTPUT_DIR = Path("catboost_dual_bpr_inference_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INFERENCE_YEAR = 2026

WRITE_PREDICTIONS_TO_DB = False
OUTPUT_TABLE_NAME = "bpr_predictions"

PRED_COL = "predicted_college_basic_bpr"
MODEL_TYPE_COL = "bpr_model_type"
SCHOOL_USED_COL = "bpr_used_school_feature"


# ============================================================
# FEATURE SETTINGS
# ============================================================

FEATURES_WITH_SCHOOL = [
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

FEATURES_NO_SCHOOL = [
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

CATEGORICAL_FEATURES_WITH_SCHOOL = [
    "hs_position",
    "hs_hometown_state",
    "hs_school_fin",
]

CATEGORICAL_FEATURES_NO_SCHOOL = [
    "hs_position",
    "hs_hometown_state",
]

OPTIONAL_ID_COLS = [
    "player_id",
    "allyears_pid",
    "player_key",
    "full_name",
    "player_name",
    "first_name",
    "last_name",
    "year",
    "team",
    "school",
    "school_fin",
    "hs_school_fin",
    "position",
]

FRONT_COL_CANDIDATES = [
    "player_id",
    "allyears_pid",
    "player_key",
    "full_name",
    "player_name",
    "first_name",
    "last_name",
    "year",
    "hs_year",
    "position",
    "hs_position",
    "school",
    "school_fin",
    "hs_school_fin",
]


# ============================================================
# SOURCE -> MODEL COLUMN ALIASES
# ============================================================

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
    "school_fin": "hs_school_fin",
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


def build_inference_query(existing_cols: list[str]) -> str:
    """
    Builds a minimal SELECT instead of SELECT *.

    It preserves optional ID/metadata columns and aliases only the required
    source columns into the hs_* model feature names.
    """
    select_parts = []
    selected_output_names = set()

    # Preserve optional ID / metadata columns if available.
    for col in OPTIONAL_ID_COLS:
        if col in existing_cols and col not in selected_output_names:
            select_parts.append(f"{qident(col)} AS {qident(col)}")
            selected_output_names.add(col)

    # Required model columns.
    # If both school_fin and hs_school_fin exist, prefer hs_school_fin because
    # that is already the model-facing name.
    ordered_source_cols = [
        "year",
        "position",
        "height",
        "height_in",
        "weight",
        "stars",
        "rating",
        "national_rank",
        "position_rank",
        "state_rank",
        "hometown_state",
    ]

    for source_col in ordered_source_cols:
        model_col = SOURCE_TO_MODEL_COLS[source_col]

        if source_col not in existing_cols:
            raise ValueError(f"Missing required source column: {source_col}")

        if model_col not in selected_output_names:
            select_parts.append(f"{qident(source_col)} AS {qident(model_col)}")
            selected_output_names.add(model_col)

    # School feature can be either hs_school_fin or school_fin.
    if "hs_school_fin" in existing_cols:
        if "hs_school_fin" not in selected_output_names:
            select_parts.append(f'{qident("hs_school_fin")} AS {qident("hs_school_fin")}')
            selected_output_names.add("hs_school_fin")
    elif "school_fin" in existing_cols:
        if "hs_school_fin" not in selected_output_names:
            select_parts.append(f'{qident("school_fin")} AS {qident("hs_school_fin")}')
            selected_output_names.add("hs_school_fin")
    else:
        raise ValueError("Missing required school column: expected hs_school_fin or school_fin")

    query = f"""
    SELECT
        {", ".join(select_parts)}
    FROM {qident(TABLE_NAME)}
    WHERE year = {int(INFERENCE_YEAR)}
    ;
    """

    return query


def ensure_height_in(df: pd.DataFrame, log=None) -> pd.DataFrame:
    df = df.copy()

    if "hs_height_in" not in df.columns:
        df["hs_height_in"] = np.nan

    if "hs_height" not in df.columns:
        msg = "WARNING: hs_height not found. Cannot backfill hs_height_in."
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


def prepare_inference_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in NUMERIC_FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    all_cat_cols = sorted(
        set(CATEGORICAL_FEATURES_WITH_SCHOOL + CATEGORICAL_FEATURES_NO_SCHOOL)
    )

    for col in all_cat_cols:
        if col in df.columns:
            df[col] = df[col].astype("string").fillna("__MISSING__").astype(str)
            df[col] = df[col].replace(
                {
                    "<NA>": "__MISSING__",
                    "nan": "__MISSING__",
                    "NaN": "__MISSING__",
                    "None": "__MISSING__",
                    "": "__MISSING__",
                }
            )

    return df


def has_real_school_value(series: pd.Series) -> pd.Series:
    s = series.astype("string").fillna("").str.strip()

    bad_values = {
        "",
        "__MISSING__",
        "nan",
        "NaN",
        "None",
        "none",
        "NULL",
        "null",
        "-",
        "'-",
        "uncommitted",
        "Uncommitted",
        "UNCOMMITTED",
        "undecided",
        "Undecided",
        "unknown",
        "Unknown",
    }

    return ~s.isin(bad_values)


def make_prediction_pool(
    df: pd.DataFrame,
    features: list[str],
    cat_features: list[str],
) -> Pool:
    return Pool(
        data=df[features],
        cat_features=cat_features,
    )


def load_catboost_model(model_path: Path) -> CatBoostRegressor:
    model = CatBoostRegressor()
    model.load_model(str(model_path))
    return model


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
    run_dir = OUTPUT_DIR / f"dual_bpr_inference_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "inference_log.txt"

    def log(msg: str):
        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting dual CatBoost BPR inference")
    log(f"Run directory: {run_dir}")
    log(f"DB path: {DB_PATH}")
    log(f"Table name: {TABLE_NAME}")
    log(f"Inference year: {INFERENCE_YEAR}")
    log(f"Model with school path: {MODEL_WITH_SCHOOL_PATH}")
    log(f"Model no school path: {MODEL_NO_SCHOOL_PATH}")

    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB_PATH does not exist: {DB_PATH}")

    if not MODEL_WITH_SCHOOL_PATH.exists():
        raise FileNotFoundError(f"MODEL_WITH_SCHOOL_PATH does not exist: {MODEL_WITH_SCHOOL_PATH}")

    if not MODEL_NO_SCHOOL_PATH.exists():
        raise FileNotFoundError(f"MODEL_NO_SCHOOL_PATH does not exist: {MODEL_NO_SCHOOL_PATH}")

    # ----------------------------
    # Load minimal inference data
    # ----------------------------

    con = duckdb.connect(str(DB_PATH))

    existing_cols = get_table_columns(con, TABLE_NAME)

    log("\nExisting table columns:")
    log(str(existing_cols))

    query = build_inference_query(existing_cols)

    log("\nInference query:")
    log(query)

    df = con.execute(query).fetchdf()

    log(f"\nRows loaded: {len(df):,}")
    log(f"Columns loaded: {list(df.columns)}")

    raw_path = run_dir / "loaded_inference_rows.csv"
    df.to_csv(raw_path, index=False)
    log(f"Saved loaded rows: {raw_path}")

    if len(df) == 0:
        log("\nNo rows found. Exiting.")
        con.close()
        return

    # ----------------------------
    # Validate / prepare features
    # ----------------------------

    df = ensure_height_in(df, log=log)
    df = prepare_inference_frame(df)

    missing_with_school = [c for c in FEATURES_WITH_SCHOOL if c not in df.columns]
    missing_no_school = [c for c in FEATURES_NO_SCHOOL if c not in df.columns]

    if missing_with_school:
        raise ValueError(f"Missing with-school model features: {missing_with_school}")

    if missing_no_school:
        raise ValueError(f"Missing no-school model features: {missing_no_school}")

    # ----------------------------
    # Split committed vs uncommitted
    # ----------------------------

    committed_mask = has_real_school_value(df["hs_school_fin"])
    uncommitted_mask = ~committed_mask

    log("\nRouting summary:")
    log(f"Rows with real hs_school_fin: {int(committed_mask.sum()):,}")
    log(f"Rows with empty/missing/uncommitted hs_school_fin: {int(uncommitted_mask.sum()):,}")

    route_df = pd.DataFrame(
        {
            "route": [
                "destination_adjusted_with_school",
                "neutral_no_school",
            ],
            "rows": [
                int(committed_mask.sum()),
                int(uncommitted_mask.sum()),
            ],
        }
    )
    route_df.to_csv(run_dir / "routing_summary.csv", index=False)

    # ----------------------------
    # Missingness reports by route
    # ----------------------------

    if committed_mask.sum() > 0:
        miss_with_school = (
            df.loc[committed_mask, FEATURES_WITH_SCHOOL]
            .isna()
            .mean()
            .sort_values(ascending=False)
            .reset_index()
        )
        miss_with_school.columns = ["feature", "missing_rate"]
        miss_with_school.to_csv(run_dir / "missingness_with_school_rows.csv", index=False)

        log("\nMissingness for with-school routed rows:")
        log(miss_with_school.to_string(index=False))

    if uncommitted_mask.sum() > 0:
        miss_no_school = (
            df.loc[uncommitted_mask, FEATURES_NO_SCHOOL]
            .isna()
            .mean()
            .sort_values(ascending=False)
            .reset_index()
        )
        miss_no_school.columns = ["feature", "missing_rate"]
        miss_no_school.to_csv(run_dir / "missingness_no_school_rows.csv", index=False)

        log("\nMissingness for no-school routed rows:")
        log(miss_no_school.to_string(index=False))

    # ----------------------------
    # Load models
    # ----------------------------

    model_with_school = load_catboost_model(MODEL_WITH_SCHOOL_PATH)
    model_no_school = load_catboost_model(MODEL_NO_SCHOOL_PATH)

    log("\nLoaded both CatBoost models.")

    # ----------------------------
    # Predict separately
    # ----------------------------

    out_df = df.copy()
    out_df[PRED_COL] = np.nan
    out_df[MODEL_TYPE_COL] = ""
    out_df[SCHOOL_USED_COL] = False

    if committed_mask.sum() > 0:
        with_school_pool = make_prediction_pool(
            out_df.loc[committed_mask],
            FEATURES_WITH_SCHOOL,
            CATEGORICAL_FEATURES_WITH_SCHOOL,
        )

        with_school_preds = model_with_school.predict(with_school_pool)

        out_df.loc[committed_mask, PRED_COL] = with_school_preds
        out_df.loc[committed_mask, MODEL_TYPE_COL] = "destination_adjusted_with_school"
        out_df.loc[committed_mask, SCHOOL_USED_COL] = True

    if uncommitted_mask.sum() > 0:
        no_school_pool = make_prediction_pool(
            out_df.loc[uncommitted_mask],
            FEATURES_NO_SCHOOL,
            CATEGORICAL_FEATURES_NO_SCHOOL,
        )

        no_school_preds = model_no_school.predict(no_school_pool)

        out_df.loc[uncommitted_mask, PRED_COL] = no_school_preds
        out_df.loc[uncommitted_mask, MODEL_TYPE_COL] = "neutral_no_school"
        out_df.loc[uncommitted_mask, SCHOOL_USED_COL] = False

    # ----------------------------
    # Output formatting
    # ----------------------------

    front_cols = []

    for col in FRONT_COL_CANDIDATES:
        if col in out_df.columns and col not in front_cols:
            front_cols.append(col)

    for col in [PRED_COL, MODEL_TYPE_COL, SCHOOL_USED_COL]:
        if col not in front_cols:
            front_cols.append(col)

    remaining_cols = [c for c in out_df.columns if c not in front_cols]
    out_df = out_df[front_cols + remaining_cols]

    output_csv_path = run_dir / "dual_bpr_predictions.csv"
    out_df.to_csv(output_csv_path, index=False)

    log(f"\nSaved predictions CSV: {output_csv_path}")

    committed_output_path = run_dir / "destination_adjusted_with_school_predictions.csv"
    uncommitted_output_path = run_dir / "neutral_no_school_predictions.csv"

    out_df[out_df[MODEL_TYPE_COL] == "destination_adjusted_with_school"].to_csv(
        committed_output_path,
        index=False,
    )
    out_df[out_df[MODEL_TYPE_COL] == "neutral_no_school"].to_csv(
        uncommitted_output_path,
        index=False,
    )

    log(f"Saved committed/with-school predictions: {committed_output_path}")
    log(f"Saved uncommitted/no-school predictions: {uncommitted_output_path}")

    # ----------------------------
    # Prediction summaries
    # ----------------------------

    log("\nOverall prediction summary:")
    log(out_df[PRED_COL].describe().to_string())

    by_model_summary = (
        out_df
        .groupby(MODEL_TYPE_COL)[PRED_COL]
        .describe()
        .reset_index()
    )

    by_model_summary_path = run_dir / "prediction_summary_by_model_type.csv"
    by_model_summary.to_csv(by_model_summary_path, index=False)

    log("\nPrediction summary by model type:")
    log(by_model_summary.to_string(index=False))

    # ----------------------------
    # Optional DB write
    # ----------------------------

    if WRITE_PREDICTIONS_TO_DB:
        con.register("predictions_df", out_df)
        con.execute(
            f"""
            CREATE OR REPLACE TABLE {qident(OUTPUT_TABLE_NAME)} AS
            SELECT * FROM predictions_df
            """
        )
        con.unregister("predictions_df")

        log(f"\nWrote predictions to DuckDB table: {OUTPUT_TABLE_NAME}")

    con.close()

    # ----------------------------
    # Save config
    # ----------------------------

    config = {
        "db_path": str(DB_PATH),
        "table_name": TABLE_NAME,
        "inference_year": INFERENCE_YEAR,
        "output_dir": str(OUTPUT_DIR),
        "run_dir": str(run_dir),
        "model_with_school_path": str(MODEL_WITH_SCHOOL_PATH),
        "model_no_school_path": str(MODEL_NO_SCHOOL_PATH),
        "prediction_col": PRED_COL,
        "model_type_col": MODEL_TYPE_COL,
        "school_used_col": SCHOOL_USED_COL,
        "features_with_school": FEATURES_WITH_SCHOOL,
        "features_no_school": FEATURES_NO_SCHOOL,
        "categorical_features_with_school": CATEGORICAL_FEATURES_WITH_SCHOOL,
        "categorical_features_no_school": CATEGORICAL_FEATURES_NO_SCHOOL,
        "source_to_model_cols": SOURCE_TO_MODEL_COLS,
        "optional_id_cols": OPTIONAL_ID_COLS,
        "write_predictions_to_db": WRITE_PREDICTIONS_TO_DB,
        "output_table_name": OUTPUT_TABLE_NAME if WRITE_PREDICTIONS_TO_DB else None,
        "query": query,
        "model_routing_rule": (
            "Rows with real hs_school_fin use destination_adjusted_with_school model. "
            "Rows with empty/missing/uncommitted hs_school_fin use neutral_no_school model."
        ),
    }

    with open(run_dir / "dual_inference_config.json", "w", encoding="utf-8") as f:
        json.dump(json_safe(config), f, indent=2)

    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")


if __name__ == "__main__":
    main()