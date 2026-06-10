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

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = PROJECT_ROOT / "data_dir" / "table1_with_next_year_bpr.db"
TABLE_NAME = "table1_with_next_year_bpr"

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "catboost_transfer_bpr_dual_inference_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

YEAR_COL = "allyears_year"
INFERENCE_YEAR = 2026

PRED_COL = "pred_next_year_basic_bpr"
MODEL_TYPE_COL = "transfer_bpr_model_type"
DESTINATION_USED_COL = "transfer_bpr_used_destination_feature"

WRITE_PREDICTIONS_TO_DB = False
OUTPUT_TABLE_NAME = "transfer_bpr_2026_predictions"


# ============================================================
# MODEL PATHS
# ============================================================

MODEL_WITH_DESTINATION_PATH = Path(
    "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/models_dir/transfer_bpr/catboost_transfer_bpr_school_no_weight_outputs/catboost_transfer_bpr_no_weight_run_20260607_182627/catboost_transfer_bpr_no_weight_production_train_valid_model.cbm"
)

MODEL_NO_DESTINATION_PATH = Path(
    "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/models_dir/transfer_bpr/catboost_transfer_bpr_no_school_no_weight_outputs/catboost_transfer_bpr_no_weight_run_20260607_183125/catboost_transfer_bpr_no_weight_production_train_valid_model.cbm"
)


# ============================================================
# EXACT FEATURE DEFINITIONS FROM SCHOOL TRAINING SCRIPT
# Do not add features here unless the training script also used them.
# ============================================================

NUMERIC_FEATURES_WITH_DESTINATION = [
    # Previous-year player stats
    "allyears_gp",
    "allyears_min_per",
    "allyears_ortg",
    "allyears_usg",
    "allyears_efg",
    "allyears_ts_per",
    "allyears_orb_per",
    "allyears_drb_per",
    "allyears_ast_per",
    "allyears_to_per",
    "allyears_ft_per",
    "allyears_twop_per",
    "allyears_tp_per",
    "allyears_blk_per",
    "allyears_stl_per",
    "allyears_ftr",
    "allyears_porpag",
    "allyears_adjoe",
    "allyears_pfr",
    "allyears_ast_tov",
    "allyears_drtg",
    "allyears_adrtg",
    "allyears_dporpag",
    "allyears_stops",
    "allyears_bpm",
    "allyears_obpm",
    "allyears_dbpm",
    "allyears_gbpm",
    "allyears_mp",
    "allyears_ogbpm",
    "allyears_dgbpm",
    "allyears_oreb",
    "allyears_dreb",
    "allyears_treb",
    "allyears_ast",
    "allyears_stl",
    "allyears_blk",
    "allyears_pts",
    "allyears_3p_100",

    # Recruiting / 247
    "247_weight",
    "247_stars",
    "247_rating",
    "247_transfer_rating",
    "247_transfer_rank",
    "247_destination_options_count",

    # Previous-year Evan BPR
    "evan_basic_obpr",
    "evan_basic_dbpr",
    "evan_basic_bpr",
    "evan_basic_poss",
    "evan_basic_box_obpr",
    "evan_basic_box_dbpr",
    "evan_basic_box_bpr",
    "evan_basic_adj_team_off_eff",
    "evan_basic_adj_team_def_eff",
    "evan_basic_adj_team_eff_margin",
    "evan_basic_plus_minus",

    # These were in the numeric list in the school training script.
    # Do not move them here unless you retrain.
    "evan_advanced_position",
    "evan_advanced_role",

    # Derived height feature created in script
    "player_height_in",
]

CATEGORICAL_FEATURES_WITH_DESTINATION = [
    # Player context
    "allyears_player_class",
    "allyears_role",

    # Transfer context
    "transfer_old_team",
    "transfer_new_team",
    "transfer_old_team_conf",
    "transfer_new_team_conf",

    # Recruiting / 247
    "247_position",
    "247_position_group",

    # Evan role context
    "evan_advanced_class",
]

FEATURES_WITH_DESTINATION = (
    NUMERIC_FEATURES_WITH_DESTINATION + CATEGORICAL_FEATURES_WITH_DESTINATION
)

# No-school model: same exact feature set, minus only destination-school features.
DESTINATION_FEATURES_TO_REMOVE = {
    "transfer_new_team",
    "transfer_new_team_conf",
}

NUMERIC_FEATURES_NO_DESTINATION = [
    c for c in NUMERIC_FEATURES_WITH_DESTINATION
    if c not in DESTINATION_FEATURES_TO_REMOVE
]

CATEGORICAL_FEATURES_NO_DESTINATION = [
    c for c in CATEGORICAL_FEATURES_WITH_DESTINATION
    if c not in DESTINATION_FEATURES_TO_REMOVE
]

FEATURES_NO_DESTINATION = (
    NUMERIC_FEATURES_NO_DESTINATION + CATEGORICAL_FEATURES_NO_DESTINATION
)


# ============================================================
# OUTPUT COLUMN ORDERING
# Not model features. Only for readable CSV output.
# ============================================================

FRONT_COL_CANDIDATES = [
    "allyears_pid",
    "allyears_player_name",
    "transfer_player_name",
    "allyears_team",
    "transfer_old_team",
    "transfer_new_team",
    "transfer_old_team_conf",
    "transfer_new_team_conf",
    "247_full_name",
    "247_position",
    "247_position_group",
    YEAR_COL,
    "allyears_role",
    "evan_advanced_position",
    "evan_advanced_role",
    "evan_basic_bpr",
    "evan_basic_obpr",
    "evan_basic_dbpr",
    "evan_basic_poss",
]


# ============================================================
# QUERY
# ============================================================

def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


QUERY = f"""
SELECT *
FROM {qident(TABLE_NAME)}
WHERE {qident(YEAR_COL)} = {INFERENCE_YEAR}
;
"""


# ============================================================
# HELPERS
# ============================================================

def parse_height_to_inches(value):
    if pd.isna(value):
        return np.nan

    s = str(value).strip()

    if s == "":
        return np.nan

    if s.startswith("="):
        s = s[1:].strip()

    s = s.strip('"').strip("'").strip()

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
    s = s.replace(" ", "")

    match = re.search(r"(\d+)\D+(\d+)", s)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2))
        total = feet * 12 + inches
        if 48 <= total <= 96:
            return float(total)

    return np.nan


def add_single_height_feature(df: pd.DataFrame, log=None) -> pd.DataFrame:
    df = df.copy()
    df["player_height_in"] = np.nan

    height_priority = [
        "allyears_player_height",
        "transfer_player_height",
        "247_height",
        "allyears_ht",
    ]

    for source_col in height_priority:
        if source_col not in df.columns:
            if log:
                log(f"Height source missing: {source_col}")
            continue

        parsed = df[source_col].apply(parse_height_to_inches)
        needs_fill = df["player_height_in"].isna() & parsed.notna()
        df.loc[needs_fill, "player_height_in"] = parsed.loc[needs_fill]

        if log:
            log(f"\nHeight source used: {source_col}")
            log(f"Rows with non-null {source_col}: {df[source_col].notna().sum():,}")
            log(f"Rows filled from {source_col}: {needs_fill.sum():,}")
            log(f"Remaining missing player_height_in: {df['player_height_in'].isna().sum():,}")

    if log:
        log("\nFinal height feature summary:")
        log(f"Non-null player_height_in: {df['player_height_in'].notna().sum():,}")
        log(f"Missing player_height_in: {df['player_height_in'].isna().sum():,}")

    return df


def has_real_destination_value(series: pd.Series) -> pd.Series:
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
        "UNDECIDED",
        "unknown",
        "Unknown",
        "UNKNOWN",
        "tbd",
        "TBD",
        "tba",
        "Tba",
        "TBA",
    }

    return ~s.isin(bad_values)


def prepare_inference_frame(
    df: pd.DataFrame,
    numeric_features: list[str],
    categorical_features: list[str],
    log=None,
) -> pd.DataFrame:
    df = df.copy()

    # Only create columns that the trained models actually require.
    for col in numeric_features:
        if col not in df.columns:
            df[col] = np.nan
            if log:
                log(f"Created missing numeric model feature as NaN: {col}")

    for col in categorical_features:
        if col not in df.columns:
            df[col] = "__MISSING__"
            if log:
                log(f"Created missing categorical model feature as __MISSING__: {col}")

    for col in numeric_features:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in categorical_features:
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


def make_prediction_pool(
    df: pd.DataFrame,
    features: list[str],
    categorical_features: list[str],
) -> Pool:
    missing_features = [c for c in features if c not in df.columns]
    if missing_features:
        raise ValueError(f"Missing model features before prediction: {missing_features}")

    return Pool(
        data=df[features],
        cat_features=categorical_features,
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
    run_dir = OUTPUT_DIR / f"dual_transfer_bpr_inference_{INFERENCE_YEAR}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "inference_log.txt"

    def log(msg: str):
        print(msg, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting dual CatBoost transfer BPR inference")
    log(f"Run directory: {run_dir}")
    log(f"DB path: {DB_PATH}")
    log(f"Table name: {TABLE_NAME}")
    log(f"Year column: {YEAR_COL}")
    log(f"Inference year: {INFERENCE_YEAR}")
    log(f"Model with destination path: {MODEL_WITH_DESTINATION_PATH}")
    log(f"Model no destination path: {MODEL_NO_DESTINATION_PATH}")

    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB_PATH does not exist: {DB_PATH}")

    if not MODEL_WITH_DESTINATION_PATH.exists():
        raise FileNotFoundError(
            f"MODEL_WITH_DESTINATION_PATH does not exist: {MODEL_WITH_DESTINATION_PATH}"
        )

    if not MODEL_NO_DESTINATION_PATH.exists():
        raise FileNotFoundError(
            f"MODEL_NO_DESTINATION_PATH does not exist: {MODEL_NO_DESTINATION_PATH}"
        )

    # ----------------------------
    # Load 2026 inference data
    # ----------------------------

    con = duckdb.connect(str(DB_PATH))
    df = con.execute(QUERY).fetchdf()

    log(f"\nRaw inference rows loaded: {len(df):,}")
    log(f"Raw columns loaded: {len(df.columns):,}")
    log(f"Query:\n{QUERY}")

    if len(df) == 0:
        con.close()
        raise ValueError(f"No rows found where {YEAR_COL} = {INFERENCE_YEAR}.")

    df.to_csv(run_dir / f"raw_transfer_inference_rows_{INFERENCE_YEAR}.csv", index=False)

    if YEAR_COL not in df.columns:
        con.close()
        raise ValueError(f"Missing required YEAR_COL: {YEAR_COL}")

    # ----------------------------
    # Height engineering
    # ----------------------------

    df = add_single_height_feature(df, log=log)
    df.to_csv(run_dir / "inference_data_after_height_features.csv", index=False)

    # ----------------------------
    # Prepare only model-required features
    # School model has the largest feature set.
    # No-school model uses subset at prediction time.
    # ----------------------------

    df = prepare_inference_frame(
        df=df,
        numeric_features=NUMERIC_FEATURES_WITH_DESTINATION,
        categorical_features=CATEGORICAL_FEATURES_WITH_DESTINATION,
        log=log,
    )

    # ----------------------------
    # Route committed vs uncommitted transfers
    # ----------------------------

    if "transfer_new_team" not in df.columns:
        df["transfer_new_team"] = "__MISSING__"
        log("\nWARNING: transfer_new_team missing. All rows will route to no-destination model.")

    committed_mask = has_real_destination_value(df["transfer_new_team"])
    uncommitted_mask = ~committed_mask

    log("\nRouting summary:")
    log(f"Rows with real transfer_new_team: {int(committed_mask.sum()):,}")
    log(f"Rows with missing/uncommitted transfer_new_team: {int(uncommitted_mask.sum()):,}")
    log(f"Total routed rows: {int(committed_mask.sum() + uncommitted_mask.sum()):,}")

    routing_df = pd.DataFrame(
        {
            "route": [
                "destination_adjusted_with_new_team",
                "neutral_no_destination",
            ],
            "rows": [
                int(committed_mask.sum()),
                int(uncommitted_mask.sum()),
            ],
        }
    )
    routing_df.to_csv(run_dir / "routing_summary.csv", index=False)

    # ----------------------------
    # Feature count sanity check
    # ----------------------------

    log("\nFeature count sanity check:")
    log(f"With-destination features: {len(FEATURES_WITH_DESTINATION):,}")
    log(f"No-destination features:   {len(FEATURES_NO_DESTINATION):,}")
    log(f"Removed for no-destination: {sorted(DESTINATION_FEATURES_TO_REMOVE)}")

    with open(run_dir / "dual_inference_features.json", "w", encoding="utf-8") as f:
        json.dump(
            json_safe(
                {
                    "features_with_destination": FEATURES_WITH_DESTINATION,
                    "numeric_features_with_destination": NUMERIC_FEATURES_WITH_DESTINATION,
                    "categorical_features_with_destination": CATEGORICAL_FEATURES_WITH_DESTINATION,
                    "features_no_destination": FEATURES_NO_DESTINATION,
                    "numeric_features_no_destination": NUMERIC_FEATURES_NO_DESTINATION,
                    "categorical_features_no_destination": CATEGORICAL_FEATURES_NO_DESTINATION,
                    "destination_features_removed_for_no_destination": sorted(
                        DESTINATION_FEATURES_TO_REMOVE
                    ),
                }
            ),
            f,
            indent=2,
        )

    # ----------------------------
    # Missingness reports by route
    # ----------------------------

    if committed_mask.sum() > 0:
        miss_with_destination = (
            df.loc[committed_mask, FEATURES_WITH_DESTINATION]
            .isna()
            .mean()
            .sort_values(ascending=False)
            .reset_index()
        )
        miss_with_destination.columns = ["feature", "missing_rate"]
        miss_with_destination.to_csv(
            run_dir / "missingness_with_destination_rows.csv",
            index=False,
        )

        log("\nMissingness for destination-routed rows:")
        log(miss_with_destination.to_string(index=False))

    if uncommitted_mask.sum() > 0:
        miss_no_destination = (
            df.loc[uncommitted_mask, FEATURES_NO_DESTINATION]
            .isna()
            .mean()
            .sort_values(ascending=False)
            .reset_index()
        )
        miss_no_destination.columns = ["feature", "missing_rate"]
        miss_no_destination.to_csv(
            run_dir / "missingness_no_destination_rows.csv",
            index=False,
        )

        log("\nMissingness for no-destination-routed rows:")
        log(miss_no_destination.to_string(index=False))

    # ----------------------------
    # Load models
    # ----------------------------

    model_with_destination = load_catboost_model(MODEL_WITH_DESTINATION_PATH)
    model_no_destination = load_catboost_model(MODEL_NO_DESTINATION_PATH)

    log("\nLoaded both CatBoost models.")

    # ----------------------------
    # Predict separately
    # ----------------------------

    out_df = df.copy()
    out_df[PRED_COL] = np.nan
    out_df[MODEL_TYPE_COL] = ""
    out_df[DESTINATION_USED_COL] = False

    if committed_mask.sum() > 0:
        with_destination_pool = make_prediction_pool(
            df=out_df.loc[committed_mask],
            features=FEATURES_WITH_DESTINATION,
            categorical_features=CATEGORICAL_FEATURES_WITH_DESTINATION,
        )

        with_destination_preds = model_with_destination.predict(with_destination_pool)

        out_df.loc[committed_mask, PRED_COL] = with_destination_preds
        out_df.loc[committed_mask, MODEL_TYPE_COL] = "destination_adjusted_with_new_team"
        out_df.loc[committed_mask, DESTINATION_USED_COL] = True

    if uncommitted_mask.sum() > 0:
        no_destination_pool = make_prediction_pool(
            df=out_df.loc[uncommitted_mask],
            features=FEATURES_NO_DESTINATION,
            categorical_features=CATEGORICAL_FEATURES_NO_DESTINATION,
        )

        no_destination_preds = model_no_destination.predict(no_destination_pool)

        out_df.loc[uncommitted_mask, PRED_COL] = no_destination_preds
        out_df.loc[uncommitted_mask, MODEL_TYPE_COL] = "neutral_no_destination"
        out_df.loc[uncommitted_mask, DESTINATION_USED_COL] = False

    # ----------------------------
    # Output formatting
    # ----------------------------

    front_cols = []

    for col in FRONT_COL_CANDIDATES:
        if col in out_df.columns and col not in front_cols:
            front_cols.append(col)

    for col in [PRED_COL, MODEL_TYPE_COL, DESTINATION_USED_COL]:
        if col in out_df.columns and col not in front_cols:
            front_cols.append(col)

    remaining_cols = [c for c in out_df.columns if c not in front_cols]
    out_df = out_df[front_cols + remaining_cols]

    # ----------------------------
    # Save outputs
    # ----------------------------

    output_csv_path = run_dir / f"dual_transfer_bpr_predictions_{INFERENCE_YEAR}.csv"
    out_df.to_csv(output_csv_path, index=False)

    destination_output_path = (
        run_dir / f"destination_adjusted_transfer_predictions_{INFERENCE_YEAR}.csv"
    )
    no_destination_output_path = (
        run_dir / f"neutral_no_destination_transfer_predictions_{INFERENCE_YEAR}.csv"
    )

    out_df[out_df[MODEL_TYPE_COL] == "destination_adjusted_with_new_team"].to_csv(
        destination_output_path,
        index=False,
    )

    out_df[out_df[MODEL_TYPE_COL] == "neutral_no_destination"].to_csv(
        no_destination_output_path,
        index=False,
    )

    log(f"\nSaved full predictions CSV: {output_csv_path}")
    log(f"Saved destination-adjusted predictions: {destination_output_path}")
    log(f"Saved no-destination predictions: {no_destination_output_path}")

    summary_cols = [
        c for c in (
            FRONT_COL_CANDIDATES + [PRED_COL, MODEL_TYPE_COL, DESTINATION_USED_COL]
        )
        if c in out_df.columns
    ]

    summary_df = out_df[summary_cols].copy()
    summary_df = summary_df.sort_values(PRED_COL, ascending=False)

    summary_path = run_dir / f"dual_transfer_bpr_predictions_{INFERENCE_YEAR}_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    log(f"Saved summary predictions CSV: {summary_path}")

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
        "year_col": YEAR_COL,
        "inference_year": INFERENCE_YEAR,
        "output_dir": str(OUTPUT_DIR),
        "run_dir": str(run_dir),
        "model_with_destination_path": str(MODEL_WITH_DESTINATION_PATH),
        "model_no_destination_path": str(MODEL_NO_DESTINATION_PATH),
        "prediction_col": PRED_COL,
        "model_type_col": MODEL_TYPE_COL,
        "destination_used_col": DESTINATION_USED_COL,
        "features_with_destination": FEATURES_WITH_DESTINATION,
        "numeric_features_with_destination": NUMERIC_FEATURES_WITH_DESTINATION,
        "categorical_features_with_destination": CATEGORICAL_FEATURES_WITH_DESTINATION,
        "features_no_destination": FEATURES_NO_DESTINATION,
        "numeric_features_no_destination": NUMERIC_FEATURES_NO_DESTINATION,
        "categorical_features_no_destination": CATEGORICAL_FEATURES_NO_DESTINATION,
        "destination_features_removed_for_no_destination": sorted(
            DESTINATION_FEATURES_TO_REMOVE
        ),
        "write_predictions_to_db": WRITE_PREDICTIONS_TO_DB,
        "output_table_name": OUTPUT_TABLE_NAME if WRITE_PREDICTIONS_TO_DB else None,
        "query": QUERY,
        "model_routing_rule": (
            "Rows with real transfer_new_team use destination_adjusted_with_new_team model. "
            "Rows with empty/missing/uncommitted/unknown transfer_new_team use neutral_no_destination model."
        ),
    }

    with open(run_dir / "dual_transfer_inference_config.json", "w", encoding="utf-8") as f:
        json.dump(json_safe(config), f, indent=2)

    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")


if __name__ == "__main__":
    main()