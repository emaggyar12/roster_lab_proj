import json
import re
import pickle
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import optuna
import pandas as pd

from catboost import CatBoostRegressor, Pool
from sklearn.metrics import (
    mean_absolute_error,
    root_mean_squared_error,
    r2_score,
)


# ============================================================
# USER SETTINGS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = PROJECT_ROOT / "data_dir" / "table1_with_next_year_bpr.db"
TABLE_NAME = "table1_with_next_year_bpr"

OUTPUT_DIR = Path("catboost_transfer_bpr_no_school_no_weight_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_COL = "next_year_basic_bpr"
YEAR_COL = "allyears_year"

# Used only for filtering + diagnostic weighted RMSE.
# This is previous/current Evan possessions, not target-year possessions.
POSS_COL = "evan_basic_poss"

MIN_POSSESSIONS = 150

N_OPTUNA_TRIALS = 75
OPTUNA_TIMEOUT_SECONDS = None

RANDOM_STATE = 42

FINAL_VERBOSE = 100
OPTUNA_VERBOSE = False


# ============================================================
# FEATURE DEFINITIONS
# ============================================================

RAW_NUMERIC_FEATURES = [
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
    'evan_advanced_position',
    'evan_advanced_role',

    # Derived height columns created in this script
    'player_height_in'
]

RAW_CATEGORICAL_FEATURES = [
    # Player context
    "allyears_player_class",
    "allyears_role",

    # Transfer context
    "transfer_old_team",
    "transfer_old_team_conf",

    # Recruiting / 247
    "247_position",
    "247_position_group",

    # Evan role context
    "evan_advanced_class",
]


# Columns that should never become features.
LEAKAGE_AND_DEBUG_COLS = [
    TARGET_COL,
    "next_year_bpr_match_name",
    "next_year_bpr_match_year",
    "next_year_bpr_match_team",
    "next_year_bpr_team_fuzzy_score",
    "next_year_bpr_team_match_source",

    "match_key",
    "db247_match_key",
    "name_score",
    "team_score",
    "overall_match_score",
    "match_flag",
    "manual_review_flag",
    "match_status",
    "row_origin",
    "db1_years_agree",
    "match_year",
    "db1_match_key",
    "247_match_year",
    "247_db247_match_key",
    "evan_match_score",
    "evan_name_score",
    "evan_team_score",
    "evan_match_confidence",
    "evan_match_method",

    "allyears_pid",
    "allyears_barttorvik_trid",
    "allyears_barttorvik_player_url",
    "allyears_barttorvik_team_url",
    "allyears_barttorvik_source_url",
    "transfer_barttorvik_trid",
    "transfer_player_url",
    "transfer_old_team_url",
    "transfer_new_team_url",
    "transfer_stats_source_url",
    "transfer_barttorvik_player_url",
    "transfer_barttorvik_old_team_url",
    "transfer_barttorvik_new_team_url",
    "transfer_source_url",
    "transfer_scraped_at_utc",
    "247_player_key",
    "247_source_institution_key",
    "247_destination_institution_key",
    "247_source_school_root_path",
    "247_destination_school_root_path",
    "247_player_profile_url",
    "247_avatar_url",
    "247_profile_url",
    "247_cache_path",
    "247_status_code",
    "247_source",
    "evan_evan_row_id",

    "allyears_player_name",
    "allyears_player_name_corrected",
    "transfer_player_name",
    "247_first_name",
    "247_last_name",
    "247_full_name",
    "evan_name",
    "evan_evan_name",
    "evan_player_name_join",
]


# ============================================================
# QUERY
# ============================================================

def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


QUERY = f"""
SELECT *
FROM {qident(TABLE_NAME)}
WHERE {qident(YEAR_COL)} IS NOT NULL
  AND {qident(YEAR_COL)} != 2026
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

    # Handles Excel-style strings like ="6-7" or ="6'7"
    s = s.strip()
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

    # Handles 6-7, 6'7, 6_7, etc.
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


def make_diagnostic_weights(possessions: pd.Series, k: float = 300) -> pd.Series:
    """
    Only used for reporting weighted_rmse as a diagnostic.
    These weights are NOT used in model training or Optuna selection.
    """
    possessions = pd.to_numeric(possessions, errors="coerce").fillna(0)
    return possessions / (possessions + k)


def rmse(y_true, y_pred):
    return root_mean_squared_error(y_true, y_pred)


def weighted_rmse(y_true, y_pred, sample_weight):
    return root_mean_squared_error(
        y_true,
        y_pred,
        sample_weight=sample_weight,
    )


def safe_corr(y_true, y_pred):
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    if len(y_true) <= 1:
        return np.nan

    if np.std(y_true) == 0 or np.std(y_pred) == 0:
        return np.nan

    return float(np.corrcoef(y_true, y_pred)[0, 1])


def safe_spearman(y_true, y_pred):
    if len(y_true) <= 1:
        return np.nan

    y_true_rank = pd.Series(np.asarray(y_true)).rank(method="average")
    y_pred_rank = pd.Series(np.asarray(y_pred)).rank(method="average")

    if y_true_rank.std() == 0 or y_pred_rank.std() == 0:
        return np.nan

    return float(np.corrcoef(y_true_rank, y_pred_rank)[0, 1])


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


def get_existing_features(
    df: pd.DataFrame,
    numeric_candidates: list[str],
    categorical_candidates: list[str],
    log=None,
) -> tuple[list[str], list[str], list[str]]:
    banned = set(LEAKAGE_AND_DEBUG_COLS)

    numeric_features = [
        c for c in numeric_candidates
        if c in df.columns and c not in banned
    ]

    categorical_features = [
        c for c in categorical_candidates
        if c in df.columns and c not in banned
    ]

    features = numeric_features + categorical_features

    missing_numeric = [c for c in numeric_candidates if c not in df.columns]
    missing_categorical = [c for c in categorical_candidates if c not in df.columns]

    if log:
        log("\nFeature selection:")
        log(f"Numeric features used: {len(numeric_features):,}")
        log(f"Categorical features used: {len(categorical_features):,}")
        log(f"Total features used: {len(features):,}")

        if missing_numeric:
            log("\nNumeric candidates missing from dataframe:")
            log(json.dumps(missing_numeric, indent=2))

        if missing_categorical:
            log("\nCategorical candidates missing from dataframe:")
            log(json.dumps(missing_categorical, indent=2))

    return features, numeric_features, categorical_features


def prepare_catboost_frame(
    df: pd.DataFrame,
    numeric_features: list[str],
    categorical_features: list[str],
) -> pd.DataFrame:
    df = df.copy()

    numeric_cols_to_convert = list(set(numeric_features + [TARGET_COL, YEAR_COL, POSS_COL]))

    for col in numeric_cols_to_convert:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in categorical_features:
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


def make_pool(
    df: pd.DataFrame,
    features: list[str],
    categorical_features: list[str],
) -> Pool:
    """
    No sample weights.
    """
    return Pool(
        data=df[features],
        label=df[TARGET_COL],
        cat_features=categorical_features,
    )


def evaluate_split(
    model,
    df_split: pd.DataFrame,
    split_name: str,
    features: list[str],
) -> tuple[dict, pd.DataFrame]:
    X = df_split[features]
    y = df_split[TARGET_COL]

    preds = model.predict(X)

    if POSS_COL in df_split.columns:
        diagnostic_weight = make_diagnostic_weights(df_split[POSS_COL], k=300)
        weighted_rmse_value = float(weighted_rmse(y, preds, diagnostic_weight))
        diagnostic_weight_mean = float(diagnostic_weight.mean())
        diagnostic_weight_min = float(diagnostic_weight.min())
        diagnostic_weight_max = float(diagnostic_weight.max())
        poss_mean = float(df_split[POSS_COL].mean())
        poss_min = float(df_split[POSS_COL].min())
        poss_max = float(df_split[POSS_COL].max())
    else:
        diagnostic_weight = pd.Series(np.nan, index=df_split.index)
        weighted_rmse_value = np.nan
        diagnostic_weight_mean = np.nan
        diagnostic_weight_min = np.nan
        diagnostic_weight_max = np.nan
        poss_mean = np.nan
        poss_min = np.nan
        poss_max = np.nan

    metrics = {
        "split": split_name,
        "rows": int(len(df_split)),
        "year_min": float(df_split[YEAR_COL].min()) if YEAR_COL in df_split.columns else np.nan,
        "year_max": float(df_split[YEAR_COL].max()) if YEAR_COL in df_split.columns else np.nan,
        "target_mean": float(y.mean()),
        "target_std": float(y.std()),
        "pred_mean": float(np.mean(preds)),
        "pred_std": float(np.std(preds)),
        "mae": float(mean_absolute_error(y, preds)),
        "rmse": float(rmse(y, preds)),
        "weighted_rmse_diagnostic_only": weighted_rmse_value,
        "r2": float(r2_score(y, preds)),
        "corr": safe_corr(y, preds),
        "spearman_corr": safe_spearman(y, preds),
        "diagnostic_weight_mean": diagnostic_weight_mean,
        "diagnostic_weight_min": diagnostic_weight_min,
        "diagnostic_weight_max": diagnostic_weight_max,
        "poss_mean": poss_mean,
        "poss_min": poss_min,
        "poss_max": poss_max,
    }

    pred_df = df_split.copy()
    pred_df["pred_bpr"] = preds
    pred_df["error"] = pred_df[TARGET_COL] - pred_df["pred_bpr"]
    pred_df["abs_error"] = pred_df["error"].abs()
    pred_df["diagnostic_weight"] = diagnostic_weight

    return metrics, pred_df


def split_training_data(
    df: pd.DataFrame,
    year_col: str,
    log=None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.sort_values(year_col, ascending=True).copy()

    year_counts = (
        df[year_col]
        .value_counts()
        .sort_index()
        .rename_axis(year_col)
        .reset_index(name="row_count")
    )

    total_rows = len(df)
    year_counts["cum_rows"] = year_counts["row_count"].cumsum()
    year_counts["cum_pct"] = year_counts["cum_rows"] / total_rows

    valid_cutoff_candidates = year_counts.loc[
        year_counts["cum_pct"] <= 0.85,
        year_col,
    ]

    train_cutoff_candidates = year_counts.loc[
        year_counts["cum_pct"] <= 0.70,
        year_col,
    ]

    if train_cutoff_candidates.empty:
        train_cutoff_year = year_counts.iloc[0][year_col]
    else:
        train_cutoff_year = train_cutoff_candidates.max()

    if valid_cutoff_candidates.empty:
        valid_cutoff_year = year_counts.iloc[min(1, len(year_counts) - 1)][year_col]
    else:
        valid_cutoff_year = valid_cutoff_candidates.max()

    if valid_cutoff_year <= train_cutoff_year:
        years = list(year_counts[year_col])
        train_index = years.index(train_cutoff_year)

        if train_index + 1 < len(years):
            valid_cutoff_year = years[train_index + 1]
        else:
            valid_cutoff_year = train_cutoff_year

    train_df = df[df[year_col] <= train_cutoff_year].copy()

    valid_df = df[
        (df[year_col] > train_cutoff_year)
        & (df[year_col] <= valid_cutoff_year)
    ].copy()

    test_df = df[df[year_col] > valid_cutoff_year].copy()

    if log:
        log("\nChronological year split row counts:")
        log(year_counts.to_string(index=False))
        log(f"\nTrain cutoff year: {train_cutoff_year}")
        log(f"Valid cutoff year: {valid_cutoff_year}")
        log(f"Train rows: {len(train_df):,}")
        log(f"Valid rows: {len(valid_df):,}")
        log(f"Test rows:  {len(test_df):,}")

    return train_df, valid_df, test_df, year_counts


# ============================================================
# MAIN
# ============================================================

def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"catboost_transfer_bpr_no_weight_run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "training_log.txt"

    def log(msg: str):
        print(msg, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting CatBoost transfer BPR training with Optuna")
    log("NO SAMPLE WEIGHTS USED IN TRAINING OR OPTUNA SELECTION")
    log(f"Run directory: {run_dir}")
    log(f"DB path: {DB_PATH}")
    log(f"Table name: {TABLE_NAME}")
    log(f"Target column: {TARGET_COL}")
    log(f"Year column: {YEAR_COL}")
    log(f"Possessions column: {POSS_COL}")

    # ----------------------------
    # Load data
    # ----------------------------

    con = duckdb.connect(str(DB_PATH))
    df = con.execute(QUERY).fetchdf()
    con.close()

    log(f"\nRaw rows loaded: {len(df):,}")
    log(f"Raw columns loaded: {len(df.columns):,}")

    df.to_csv(run_dir / "raw_loaded_data.csv", index=False)

    # ----------------------------
    # Required columns
    # ----------------------------

    required_cols = [TARGET_COL, YEAR_COL]

    if POSS_COL in df.columns:
        required_cols.append(POSS_COL)
    else:
        log(f"\nWARNING: {POSS_COL} not found. Possession filtering and weighted diagnostic metrics disabled.")

    missing_required = [c for c in required_cols if c not in df.columns]
    if missing_required:
        raise ValueError(f"Missing required columns: {missing_required}")

    # ----------------------------
    # Height engineering
    # ----------------------------

    df = add_single_height_feature(df, log=log)
    df.to_csv(run_dir / "loaded_data_after_height_features.csv", index=False)

    # ----------------------------
    # Feature selection
    # ----------------------------

    FEATURES, NUMERIC_FEATURES, CATEGORICAL_FEATURES = get_existing_features(
        df=df,
        numeric_candidates=RAW_NUMERIC_FEATURES,
        categorical_candidates=RAW_CATEGORICAL_FEATURES,
        log=log,
    )

    if not FEATURES:
        raise ValueError("No usable features found.")

    with open(run_dir / "selected_features.json", "w", encoding="utf-8") as f:
        json.dump(
            json_safe(
                {
                    "features": FEATURES,
                    "numeric_features": NUMERIC_FEATURES,
                    "categorical_features": CATEGORICAL_FEATURES,
                    "raw_numeric_candidates": RAW_NUMERIC_FEATURES,
                    "raw_categorical_candidates": RAW_CATEGORICAL_FEATURES,
                    "excluded_columns": LEAKAGE_AND_DEBUG_COLS,
                }
            ),
            f,
            indent=2,
        )

    # ----------------------------
    # Prepare dtypes
    # ----------------------------

    df = prepare_catboost_frame(
        df=df,
        numeric_features=NUMERIC_FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
    )

    before_filter = len(df)

    filter_mask = (
        df[TARGET_COL].notna()
        & df[YEAR_COL].notna()
    )

    if POSS_COL in df.columns:
        filter_mask = filter_mask & df[POSS_COL].notna() & (df[POSS_COL] >= MIN_POSSESSIONS)

    df = df[filter_mask].copy()

    after_filter = len(df)

    log("\nFiltering:")
    log(f"Rows before filter: {before_filter:,}")
    log(f"Rows after target/year/poss filter: {after_filter:,}")
    log(f"MIN_POSSESSIONS: {MIN_POSSESSIONS if POSS_COL in df.columns else 'DISABLED'}")

    if len(df) == 0:
        raise ValueError("No rows left after filtering.")

    df.to_csv(run_dir / "modeling_data_after_filter.csv", index=False)

    # ----------------------------
    # Split chronologically by cumulative row share
    # ----------------------------

    train_df, valid_df, test_df, year_counts = split_training_data(
        df=df,
        year_col=YEAR_COL,
        log=log,
    )

    log("\nRows after chronological split:")
    log(f"Train rows: {len(train_df):,}")
    log(f"Valid rows: {len(valid_df):,}")
    log(f"Test rows:  {len(test_df):,}")
    log(f"Total rows: {len(train_df) + len(valid_df) + len(test_df):,}")

    year_counts.to_csv(run_dir / "year_split_counts.csv", index=False)

    if len(train_df) == 0:
        raise ValueError("Train split is empty.")
    if len(valid_df) == 0:
        raise ValueError("Validation split is empty.")
    if len(test_df) == 0:
        log("WARNING: Test split is empty. Continuing with train/valid only.")

    train_df.to_csv(run_dir / "train_split.csv", index=False)
    valid_df.to_csv(run_dir / "valid_split.csv", index=False)
    test_df.to_csv(run_dir / "test_split.csv", index=False)

    # ----------------------------
    # Missingness report
    # ----------------------------

    report_cols = FEATURES + [TARGET_COL, YEAR_COL]
    if POSS_COL in df.columns:
        report_cols.append(POSS_COL)

    missing_report = (
        df[report_cols]
        .isna()
        .mean()
        .sort_values(ascending=False)
        .reset_index()
    )
    missing_report.columns = ["column", "missing_rate"]

    missing_report.to_csv(run_dir / "missingness_report.csv", index=False)

    log("\nMissingness report:")
    log(missing_report.to_string(index=False))

    # ----------------------------
    # Pools without sample weights
    # ----------------------------

    train_pool = make_pool(
        df=train_df,
        features=FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
    )

    valid_pool = make_pool(
        df=valid_df,
        features=FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
    )

    # ----------------------------
    # Optuna objective
    # ----------------------------

    def objective(trial: optuna.Trial) -> float:
        params = {
            "loss_function": "RMSE",
            "eval_metric": "RMSE",
            "random_seed": RANDOM_STATE,
            "allow_writing_files": False,
            "verbose": False,

            "iterations": trial.suggest_int("iterations", 300, 3000),
            "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.12, log=True),
            "depth": trial.suggest_int("depth", 3, 8),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 50.0, log=True),
            "random_strength": trial.suggest_float("random_strength", 0.0, 10.0),
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 10.0),
            "border_count": trial.suggest_categorical("border_count", [32, 64, 128, 254]),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 1, 40),

            "od_type": "Iter",
            "od_wait": trial.suggest_int("od_wait", 50, 250),
        }

        model = CatBoostRegressor(**params)

        model.fit(
            train_pool,
            eval_set=valid_pool,
            use_best_model=True,
            verbose=OPTUNA_VERBOSE,
        )

        valid_preds = model.predict(valid_df[FEATURES])

        valid_rmse = rmse(valid_df[TARGET_COL], valid_preds)

        trial.set_user_attr("best_iteration", int(model.get_best_iteration()))
        trial.set_user_attr("valid_rmse", float(valid_rmse))
        trial.set_user_attr("valid_mae", float(mean_absolute_error(valid_df[TARGET_COL], valid_preds)))
        trial.set_user_attr("valid_r2", float(r2_score(valid_df[TARGET_COL], valid_preds)))
        trial.set_user_attr("valid_corr", safe_corr(valid_df[TARGET_COL], valid_preds))
        trial.set_user_attr("valid_spearman_corr", safe_spearman(valid_df[TARGET_COL], valid_preds))

        if POSS_COL in valid_df.columns:
            diagnostic_weight = make_diagnostic_weights(valid_df[POSS_COL], k=300)
            trial.set_user_attr(
                "valid_weighted_rmse_diagnostic_only",
                float(weighted_rmse(valid_df[TARGET_COL], valid_preds, diagnostic_weight)),
            )

        return float(valid_rmse)

    # ----------------------------
    # Run Optuna
    # ----------------------------

    log("\nStarting Optuna search...")
    log(f"N_OPTUNA_TRIALS: {N_OPTUNA_TRIALS}")
    log(f"OPTUNA_TIMEOUT_SECONDS: {OPTUNA_TIMEOUT_SECONDS}")
    log("Optimization target: valid_rmse")
    log("Sample weights: DISABLED")

    sampler = optuna.samplers.TPESampler(seed=RANDOM_STATE)

    study = optuna.create_study(
        direction="minimize",
        sampler=sampler,
        study_name=f"catboost_transfer_bpr_no_weight_{run_id}",
    )

    study.optimize(
        objective,
        n_trials=N_OPTUNA_TRIALS,
        timeout=OPTUNA_TIMEOUT_SECONDS,
        show_progress_bar=True,
    )

    log("\nOptuna search complete.")
    log(f"Best trial number: {study.best_trial.number}")
    log(f"Best objective value: {study.best_value}")
    log("Best params:")
    log(json.dumps(study.best_params, indent=2))

    trials_df = study.trials_dataframe(
        attrs=("number", "value", "params", "user_attrs", "state")
    )
    trials_df.to_csv(run_dir / "optuna_trials.csv", index=False)

    best_trial_info = {
        "best_trial_number": study.best_trial.number,
        "best_value": study.best_value,
        "best_params": study.best_params,
        "best_user_attrs": study.best_trial.user_attrs,
    }

    with open(run_dir / "best_trial.json", "w", encoding="utf-8") as f:
        json.dump(json_safe(best_trial_info), f, indent=2)

    # ----------------------------
    # Final model using best params
    # ----------------------------

    best_params = dict(study.best_params)

    final_params = {
        "loss_function": "RMSE",
        "eval_metric": "RMSE",
        "random_seed": RANDOM_STATE,
        "allow_writing_files": False,
        "verbose": FINAL_VERBOSE,
        "use_best_model": True,
        "od_type": "Iter",
        **best_params,
    }

    if "od_wait" not in final_params:
        final_params["od_wait"] = 100

    log("\nTraining final CatBoost model with best Optuna params...")
    log("Sample weights: DISABLED")
    log(json.dumps(json_safe(final_params), indent=2))

    final_model = CatBoostRegressor(**final_params)

    final_model.fit(
        train_pool,
        eval_set=valid_pool,
        use_best_model=True,
        verbose=FINAL_VERBOSE,
    )

    log(f"\nFinal model best iteration: {final_model.get_best_iteration()}")

    # ----------------------------
    # Evaluate final model
    # ----------------------------

    all_metrics = []

    train_metrics, train_pred_df = evaluate_split(
        model=final_model,
        df_split=train_df,
        split_name="train",
        features=FEATURES,
    )

    valid_metrics, valid_pred_df = evaluate_split(
        model=final_model,
        df_split=valid_df,
        split_name="valid",
        features=FEATURES,
    )

    all_metrics.extend([train_metrics, valid_metrics])

    train_pred_df.to_csv(run_dir / "train_predictions.csv", index=False)
    valid_pred_df.to_csv(run_dir / "valid_predictions.csv", index=False)

    if len(test_df) > 0:
        test_metrics, test_pred_df = evaluate_split(
            model=final_model,
            df_split=test_df,
            split_name="test",
            features=FEATURES,
        )
        all_metrics.append(test_metrics)
        test_pred_df.to_csv(run_dir / "test_predictions.csv", index=False)

    metrics_df = pd.DataFrame(all_metrics)
    metrics_df.to_csv(run_dir / "final_metrics.csv", index=False)

    log("\nFinal metrics:")
    log(metrics_df.to_string(index=False))

    # ----------------------------
    # Feature importance
    # ----------------------------

    feature_importance = final_model.get_feature_importance(train_pool)

    fi_df = pd.DataFrame(
        {
            "feature": FEATURES,
            "importance": feature_importance,
        }
    ).sort_values("importance", ascending=False)

    fi_df.to_csv(run_dir / "catboost_feature_importance.csv", index=False)

    log("\nFeature importance:")
    log(fi_df.to_string(index=False))

    # ----------------------------
    # Save final model
    # ----------------------------

    cbm_path = run_dir / "catboost_transfer_bpr_no_weight_model.cbm"
    pkl_path = run_dir / "catboost_transfer_bpr_no_weight_model.pkl"

    final_model.save_model(str(cbm_path))

    with open(pkl_path, "wb") as f:
        pickle.dump(final_model, f)

    log(f"\nSaved CatBoost model: {cbm_path}")
    log(f"Saved pickle model: {pkl_path}")

    # ----------------------------
    # Production model: train on train + valid, no weights
    # ----------------------------

    train_valid_df = pd.concat([train_df, valid_df], axis=0).copy()

    train_valid_pool = make_pool(
        df=train_valid_df,
        features=FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
    )

    production_params = dict(final_params)
    production_params["use_best_model"] = False
    production_params["verbose"] = FINAL_VERBOSE

    best_iter = final_model.get_best_iteration()
    if best_iter is not None and best_iter > 0:
        production_params["iterations"] = int(best_iter)

    log("\nTraining production CatBoost model on train + valid...")
    log("Sample weights: DISABLED")
    log(json.dumps(json_safe(production_params), indent=2))

    production_model = CatBoostRegressor(**production_params)

    production_model.fit(
        train_valid_pool,
        verbose=FINAL_VERBOSE,
    )

    production_cbm_path = run_dir / "catboost_transfer_bpr_no_weight_production_train_valid_model.cbm"
    production_pkl_path = run_dir / "catboost_transfer_bpr_no_weight_production_train_valid_model.pkl"

    production_model.save_model(str(production_cbm_path))

    with open(production_pkl_path, "wb") as f:
        pickle.dump(production_model, f)

    log(f"\nSaved production CatBoost model: {production_cbm_path}")
    log(f"Saved production pickle model: {production_pkl_path}")

    if len(test_df) > 0:
        prod_test_metrics, prod_test_pred_df = evaluate_split(
            model=production_model,
            df_split=test_df,
            split_name="test_production_train_valid",
            features=FEATURES,
        )

        prod_test_pred_df.to_csv(
            run_dir / "test_predictions_production_train_valid.csv",
            index=False,
        )

        with open(run_dir / "production_test_metrics.json", "w", encoding="utf-8") as f:
            json.dump(json_safe(prod_test_metrics), f, indent=2)

        log("\nProduction model test metrics:")
        log(json.dumps(json_safe(prod_test_metrics), indent=2))

    # ----------------------------
    # Save config
    # ----------------------------

    config = {
        "db_path": str(DB_PATH),
        "table_name": TABLE_NAME,
        "output_dir": str(OUTPUT_DIR),
        "run_dir": str(run_dir),
        "target_col": TARGET_COL,
        "year_col": YEAR_COL,
        "poss_col": POSS_COL,
        "min_possessions": int(MIN_POSSESSIONS),
        "sample_weights_used": False,
        "diagnostic_weight_formula": "possessions / (possessions + 300), reporting only",
        "features": list(FEATURES),
        "numeric_features": list(NUMERIC_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "raw_numeric_candidates": list(RAW_NUMERIC_FEATURES),
        "raw_categorical_candidates": list(RAW_CATEGORICAL_FEATURES),
        "leakage_and_debug_cols": list(LEAKAGE_AND_DEBUG_COLS),
        "n_optuna_trials": int(N_OPTUNA_TRIALS),
        "optuna_timeout_seconds": OPTUNA_TIMEOUT_SECONDS,
        "optimization_target": "valid_rmse",
        "random_state": int(RANDOM_STATE),
        "best_trial": best_trial_info,
        "final_params": final_params,
        "production_params": production_params,
        "split": {
            "method": "chronological cumulative row share by year",
            "train": "oldest years until cumulative rows <= 70%",
            "valid": "next years until cumulative rows <= 85%",
            "test": "remaining most recent years",
        },
        "query": QUERY,
    }

    with open(run_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(json_safe(config), f, indent=2)

    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")


if __name__ == "__main__":
    main()