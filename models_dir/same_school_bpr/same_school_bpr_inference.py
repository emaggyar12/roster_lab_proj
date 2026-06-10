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

# FILL THESE IN
DB_PATH = PROJECT_ROOT / "data_dir" / "evan_miya_barttorvik_matched.db"
TABLE_NAME = "evan_miya_barttorvik_matched"

MODEL_PATH = Path(
    '/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/models_dir/same_school_bpr/catboost_transfer_bpr_refactored_outputs/catboost_transfer_refactored_run_20260607_195230/catboost_transfer_refactored_production_train_valid_model.cbm'
)

OUTPUT_DIR = Path("catboost_same_school_bpr_inference_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FILTER_YEAR_COL = "year"
INFERENCE_YEAR = 2026

PRED_COL = "pred_next_basic_bpr"


# ============================================================
# EXACT MODEL FEATURE DEFINITIONS FROM TRAINING
# These names stay old_* because the model was trained on old_*.
# ============================================================

MODEL_CATEGORICAL_FEATURES = [
    "old_advanced_class",
    "old_bvt_role",
]

MODEL_NUMERIC_FEATURES = [
    "old_year",
    "old_rank",

    "old_basic_obpr",
    "old_basic_dbpr",
    "old_basic_bpr",
    "old_basic_poss",
    "old_basic_box_obpr",
    "old_basic_box_dbpr",
    "old_basic_box_bpr",
    "old_basic_adj_team_off_eff",
    "old_basic_adj_team_def_eff",
    "old_basic_adj_team_eff_margin",
    "old_basic_plus_minus",

    "old_advanced_position",
    "old_advanced_role",

    "old_bvt_GP",
    "old_bvt_Min_per",
    "old_bvt_ORtg",
    "old_bvt_usg",
    "old_bvt_eFG",
    "old_bvt_TS_per",
    "old_bvt_ORB_per",
    "old_bvt_DRB_per",
    "old_bvt_AST_per",
    "old_bvt_TO_per",
    "old_bvt_FTM",
    "old_bvt_FTA",
    "old_bvt_FT_per",
    "old_bvt_twoPM",
    "old_bvt_twoPA",
    "old_bvt_twoP_per",
    "old_bvt_TPM",
    "old_bvt_TPA",
    "old_bvt_TP_per",
    "old_bvt_blk_per",
    "old_bvt_stl_per",
    "old_bvt_ftr",
    "old_bvt_porpag",
    "old_bvt_adjoe",
    "old_bvt_pfr",

    "old_bvt_Rec Rank",
    "old_bvt_ast/tov",
    "old_bvt_rimmade",
    "old_bvt_rimmade+rimmiss",
    "old_bvt_midmade",
    "old_bvt_midmade+midmiss",
    "old_bvt_rimmade/(rimmade+rimmiss)",
    "old_bvt_midmade/(midmade+midmiss)",
    "old_bvt_dunksmade",
    "old_bvt_dunksmiss+dunksmade",
    "old_bvt_dunksmade/(dunksmade+dunksmiss)",
    "old_bvt_drtg",
    "old_bvt_adrtg",
    "old_bvt_dporpag",
    "old_bvt_stops",
    "old_bvt_bpm",
    "old_bvt_obpm",
    "old_bvt_dbpm",
    "old_bvt_gbpm",
    "old_bvt_mp",
    "old_bvt_ogbpm",
    "old_bvt_dgbpm",
    "old_bvt_oreb",
    "old_bvt_dreb",
    "old_bvt_treb",
    "old_bvt_ast",
    "old_bvt_stl",
    "old_bvt_blk",
    "old_bvt_pts",
    "old_bvt_3p/100?",

    # Engineered feature created below.
    "player_height_in",
]

MODEL_FEATURES = MODEL_NUMERIC_FEATURES + MODEL_CATEGORICAL_FEATURES


# ============================================================
# SOURCE TABLE -> MODEL FEATURE MAP
# Table has no old_ prefixes.
# Model expects old_ prefixes.
# ============================================================

SOURCE_TO_MODEL_COLS = {
    "year": "old_year",
    "rank": "old_rank",

    "basic_obpr": "old_basic_obpr",
    "basic_dbpr": "old_basic_dbpr",
    "basic_bpr": "old_basic_bpr",
    "basic_poss": "old_basic_poss",
    "basic_box_obpr": "old_basic_box_obpr",
    "basic_box_dbpr": "old_basic_box_dbpr",
    "basic_box_bpr": "old_basic_box_bpr",
    "basic_adj_team_off_eff": "old_basic_adj_team_off_eff",
    "basic_adj_team_def_eff": "old_basic_adj_team_def_eff",
    "basic_adj_team_eff_margin": "old_basic_adj_team_eff_margin",
    "basic_plus_minus": "old_basic_plus_minus",

    "advanced_position": "old_advanced_position",
    "advanced_role": "old_advanced_role",
    "advanced_class": "old_advanced_class",

    "bvt_role": "old_bvt_role",
    "bvt_GP": "old_bvt_GP",
    "bvt_Min_per": "old_bvt_Min_per",
    "bvt_ORtg": "old_bvt_ORtg",
    "bvt_usg": "old_bvt_usg",
    "bvt_eFG": "old_bvt_eFG",
    "bvt_TS_per": "old_bvt_TS_per",
    "bvt_ORB_per": "old_bvt_ORB_per",
    "bvt_DRB_per": "old_bvt_DRB_per",
    "bvt_AST_per": "old_bvt_AST_per",
    "bvt_TO_per": "old_bvt_TO_per",
    "bvt_FTM": "old_bvt_FTM",
    "bvt_FTA": "old_bvt_FTA",
    "bvt_FT_per": "old_bvt_FT_per",
    "bvt_twoPM": "old_bvt_twoPM",
    "bvt_twoPA": "old_bvt_twoPA",
    "bvt_twoP_per": "old_bvt_twoP_per",
    "bvt_TPM": "old_bvt_TPM",
    "bvt_TPA": "old_bvt_TPA",
    "bvt_TP_per": "old_bvt_TP_per",
    "bvt_blk_per": "old_bvt_blk_per",
    "bvt_stl_per": "old_bvt_stl_per",
    "bvt_ftr": "old_bvt_ftr",
    "bvt_porpag": "old_bvt_porpag",
    "bvt_adjoe": "old_bvt_adjoe",
    "bvt_pfr": "old_bvt_pfr",

    "bvt_Rec Rank": "old_bvt_Rec Rank",
    "bvt_ast/tov": "old_bvt_ast/tov",
    "bvt_rimmade": "old_bvt_rimmade",
    "bvt_rimmade+rimmiss": "old_bvt_rimmade+rimmiss",
    "bvt_midmade": "old_bvt_midmade",
    "bvt_midmade+midmiss": "old_bvt_midmade+midmiss",
    "bvt_rimmade/(rimmade+rimmiss)": "old_bvt_rimmade/(rimmade+rimmiss)",
    "bvt_midmade/(midmade+midmiss)": "old_bvt_midmade/(midmade+midmiss)",
    "bvt_dunksmade": "old_bvt_dunksmade",
    "bvt_dunksmiss+dunksmade": "old_bvt_dunksmiss+dunksmade",
    "bvt_dunksmade/(dunksmade+dunksmiss)": "old_bvt_dunksmade/(dunksmade+dunksmiss)",
    "bvt_drtg": "old_bvt_drtg",
    "bvt_adrtg": "old_bvt_adrtg",
    "bvt_dporpag": "old_bvt_dporpag",
    "bvt_stops": "old_bvt_stops",
    "bvt_bpm": "old_bvt_bpm",
    "bvt_obpm": "old_bvt_obpm",
    "bvt_dbpm": "old_bvt_dbpm",
    "bvt_gbpm": "old_bvt_gbpm",
    "bvt_mp": "old_bvt_mp",
    "bvt_ogbpm": "old_bvt_ogbpm",
    "bvt_dgbpm": "old_bvt_dgbpm",
    "bvt_oreb": "old_bvt_oreb",
    "bvt_dreb": "old_bvt_dreb",
    "bvt_treb": "old_bvt_treb",
    "bvt_ast": "old_bvt_ast",
    "bvt_stl": "old_bvt_stl",
    "bvt_blk": "old_bvt_blk",
    "bvt_pts": "old_bvt_pts",
    "bvt_3p/100?": "old_bvt_3p/100?",
}

HEIGHT_SOURCE_COLS = [
    "bvt_ht",
    "bvt_player_height",
]


# ============================================================
# QUERY
# ============================================================

def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


QUERY = f"""
SELECT *
FROM {qident(TABLE_NAME)}
WHERE {qident(FILTER_YEAR_COL)} = {int(INFERENCE_YEAR)}
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


def add_single_height_feature_to_model_df(
    raw_df: pd.DataFrame,
    model_df: pd.DataFrame,
    log=None,
) -> pd.DataFrame:
    model_df = model_df.copy()
    model_df["player_height_in"] = np.nan

    for source_col in HEIGHT_SOURCE_COLS:
        if source_col not in raw_df.columns:
            if log:
                log(f"Height source missing: {source_col}")
            continue

        parsed = raw_df[source_col].apply(parse_height_to_inches)

        needs_fill = model_df["player_height_in"].isna() & parsed.notna()
        model_df.loc[needs_fill, "player_height_in"] = parsed.loc[needs_fill]

        if log:
            log(f"\nHeight source used: {source_col}")
            log(f"Rows with non-null {source_col}: {raw_df[source_col].notna().sum():,}")
            log(f"Rows filled from {source_col}: {needs_fill.sum():,}")
            log(f"Remaining missing player_height_in: {model_df['player_height_in'].isna().sum():,}")

    if log:
        log("\nFinal height feature summary:")
        log(f"Non-null player_height_in: {model_df['player_height_in'].notna().sum():,}")
        log(f"Missing player_height_in: {model_df['player_height_in'].isna().sum():,}")

    return model_df


def build_model_frame_from_raw(raw_df: pd.DataFrame, log=None) -> pd.DataFrame:
    """
    Builds the CatBoost input dataframe with the exact feature names used in training.
    Source table columns do not have old_ prefixes.
    Model input columns do have old_ prefixes.
    """
    model_df = pd.DataFrame(index=raw_df.index)

    missing_source_cols = []

    for source_col, model_col in SOURCE_TO_MODEL_COLS.items():
        if source_col not in raw_df.columns:
            missing_source_cols.append(source_col)
            continue

        model_df[model_col] = raw_df[source_col]

    if missing_source_cols:
        raise ValueError(
            "Missing source columns in inference table. "
            f"These are needed to build model features: {missing_source_cols}"
        )

    model_df = add_single_height_feature_to_model_df(
        raw_df=raw_df,
        model_df=model_df,
        log=log,
    )

    missing_model_features = [c for c in MODEL_FEATURES if c not in model_df.columns]

    if missing_model_features:
        raise ValueError(
            "Internal model dataframe is missing trained model features: "
            f"{missing_model_features}"
        )

    model_df = model_df[MODEL_FEATURES].copy()

    return model_df


def prepare_model_frame(model_df: pd.DataFrame) -> pd.DataFrame:
    model_df = model_df.copy()

    for col in MODEL_NUMERIC_FEATURES:
        model_df[col] = pd.to_numeric(model_df[col], errors="coerce")

    for col in MODEL_CATEGORICAL_FEATURES:
        model_df[col] = model_df[col].astype("string").fillna("__MISSING__").astype(str)
        model_df[col] = model_df[col].replace(
            {
                "<NA>": "__MISSING__",
                "nan": "__MISSING__",
                "NaN": "__MISSING__",
                "None": "__MISSING__",
                "": "__MISSING__",
            }
        )

    return model_df


def make_prediction_pool(
    model_df: pd.DataFrame,
    features: list[str],
    categorical_features: list[str],
) -> Pool:
    return Pool(
        data=model_df[features],
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
    run_dir = OUTPUT_DIR / f"catboost_same_school__{INFERENCE_YEAR}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "inference_log.txt"

    def log(msg: str):
        print(msg, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting CatBoost same school BPR inference")
    log(f"Run directory: {run_dir}")
    log(f"DB path: {DB_PATH}")
    log(f"Table name: {TABLE_NAME}")
    log(f"Filter year column: {FILTER_YEAR_COL}")
    log(f"Inference year: {INFERENCE_YEAR}")
    log(f"Model path: {MODEL_PATH}")
    log(f"Prediction column: {PRED_COL}")

    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB_PATH does not exist: {DB_PATH}")

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"MODEL_PATH does not exist: {MODEL_PATH}")

    # ----------------------------
    # Load inference rows
    # ----------------------------

    con = duckdb.connect(str(DB_PATH))
    raw_df = con.execute(QUERY).fetchdf()
    con.close()

    log(f"\nRaw inference rows loaded: {len(raw_df):,}")
    log(f"Raw columns loaded: {len(raw_df.columns):,}")
    log(f"Query:\n{QUERY}")

    if len(raw_df) == 0:
        raise ValueError(
            f"No inference rows found where {FILTER_YEAR_COL} = {INFERENCE_YEAR}."
        )

    if FILTER_YEAR_COL not in raw_df.columns:
        raise ValueError(f"Missing filter year column: {FILTER_YEAR_COL}")

    raw_path = run_dir / f"raw_inference_rows_{INFERENCE_YEAR}.csv"
    raw_df.to_csv(raw_path, index=False)
    log(f"Saved raw inference rows: {raw_path}")

    # ----------------------------
    # Build internal model dataframe
    # ----------------------------

    model_df = build_model_frame_from_raw(raw_df=raw_df, log=log)

    model_raw_path = run_dir / "internal_model_frame_before_dtype_prep.csv"
    model_df.to_csv(model_raw_path, index=False)
    log(f"Saved internal model frame before dtype prep: {model_raw_path}")

    # ----------------------------
    # Prepare exact model features
    # ----------------------------

    model_df = prepare_model_frame(model_df)

    model_prepared_path = run_dir / "internal_model_frame_after_dtype_prep.csv"
    model_df.to_csv(model_prepared_path, index=False)
    log(f"Saved internal model frame after dtype prep: {model_prepared_path}")

    # ----------------------------
    # Missingness report
    # ----------------------------

    missing_report = (
        model_df[MODEL_FEATURES]
        .isna()
        .mean()
        .sort_values(ascending=False)
        .reset_index()
    )
    missing_report.columns = ["feature", "missing_rate"]

    missing_report_path = run_dir / "inference_missingness_report.csv"
    missing_report.to_csv(missing_report_path, index=False)

    log("\nInference missingness report:")
    log(missing_report.to_string(index=False))

    # ----------------------------
    # Load model
    # ----------------------------

    model = load_catboost_model(MODEL_PATH)
    log("\nLoaded CatBoost model.")

    # ----------------------------
    # Predict
    # ----------------------------

    prediction_pool = make_prediction_pool(
        model_df=model_df,
        features=MODEL_FEATURES,
        categorical_features=MODEL_CATEGORICAL_FEATURES,
    )

    preds = model.predict(prediction_pool)

    out_df = raw_df.copy()
    out_df[PRED_COL] = preds

    log("\nPrediction summary:")
    log(f"Rows predicted: {len(out_df):,}")
    log(f"{PRED_COL} mean: {float(np.mean(preds)):.4f}")
    log(f"{PRED_COL} std:  {float(np.std(preds)):.4f}")
    log(f"{PRED_COL} min:  {float(np.min(preds)):.4f}")
    log(f"{PRED_COL} max:  {float(np.max(preds)):.4f}")

    # ----------------------------
    # Save outputs
    # ----------------------------

    output_path = run_dir / f"catboost_same_school_predictions_{INFERENCE_YEAR}.csv"
    out_df.to_csv(output_path, index=False)

    front_col_candidates = [
        "name",
        "player_name",
        "full_name",
        "bvt_pid",
        "team",
        "year",
        "advanced_class",
        "bvt_role",
        "basic_bpr",
        "basic_obpr",
        "basic_dbpr",
        "basic_poss",
        PRED_COL,
    ]

    summary_cols = [c for c in front_col_candidates if c in out_df.columns]

    if PRED_COL not in summary_cols:
        summary_cols.append(PRED_COL)

    summary_df = out_df[summary_cols].copy()
    summary_df = summary_df.sort_values(PRED_COL, ascending=False)

    summary_path = run_dir / f"catboost_same_school_predictions_{INFERENCE_YEAR}_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    log(f"\nSaved full predictions: {output_path}")
    log(f"Saved summary predictions: {summary_path}")

    # ----------------------------
    # Save config
    # ----------------------------

    config = {
        "db_path": str(DB_PATH),
        "table_name": TABLE_NAME,
        "model_path": str(MODEL_PATH),
        "output_dir": str(OUTPUT_DIR),
        "run_dir": str(run_dir),
        "filter_year_col": FILTER_YEAR_COL,
        "inference_year": int(INFERENCE_YEAR),
        "prediction_col": PRED_COL,
        "source_to_model_cols": SOURCE_TO_MODEL_COLS,
        "height_source_cols": HEIGHT_SOURCE_COLS,
        "final_height_feature": "player_height_in",
        "model_features": MODEL_FEATURES,
        "model_numeric_features": MODEL_NUMERIC_FEATURES,
        "model_categorical_features": MODEL_CATEGORICAL_FEATURES,
        "query": QUERY,
        "rows_loaded": int(len(out_df)),
    }

    config_path = run_dir / "inference_config.json"

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(json_safe(config), f, indent=2)

    log(f"Saved inference config: {config_path}")
    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")


if __name__ == "__main__":
    main()