import json
import re
import pickle
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from autogluon.tabular import TabularPredictor
from sklearn.metrics import (
    mean_absolute_error,
    root_mean_squared_error,
    r2_score,
)


# ============================================================
# USER SETTINGS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = PROJECT_ROOT / "data_dir" / "hs_to_evan_match.db"
TABLE_NAME = "hs_to_evan_global_matched"

OUTPUT_DIR = Path("autogluon_bpr_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_COL = "college_basic_bpr"
SAMPLE_WEIGHT_COL = "college_basic_poss"

MIN_POSSESSIONS = 150
SAMPLE_WEIGHT_K = 300

RANDOM_STATE = 42

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

# AutoGluon settings
AG_PRESETS = "good_quality"
AG_TIME_LIMIT = None  # seconds. Use None for no limit.
AG_EVAL_METRIC = "root_mean_squared_error"

AG_HYPERPARAMETERS = {
    "CAT": {},   # CatBoost
    "XGB": {},   # XGBoost
    "RF": {},    # RandomForest
    "XT": {},    # ExtraTrees
}

# If True, AutoGluon uses college possessions-derived sample weights.
USE_SAMPLE_WEIGHTS = True

# AutoGluon model storage can get large.
# This keeps the run self-contained inside the output folder.
SAVE_SPACE_AFTER_TRAINING = False


# ============================================================
# QUERY
# ============================================================

def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


QUERY = f"""
SELECT
    hs_year,
    hs_position,
    hs_height,
    hs_height_in,
    hs_weight,
    hs_stars,
    hs_rating,
    hs_national_rank,
    hs_position_rank,
    hs_state_rank,
    hs_hometown_state,
    hs_school_fin,

    college_basic_bpr,
    college_basic_poss
FROM {qident(TABLE_NAME)}
WHERE college_basic_bpr IS NOT NULL
  AND college_basic_poss IS NOT NULL
;
"""


# ============================================================
# HELPER FUNCTIONS
# ============================================================

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

    If hs_height_in is null but hs_height is non-null, this fills hs_height_in
    using parsed hs_height.
    """
    df = df.copy()

    if "hs_height_in" not in df.columns:
        df["hs_height_in"] = np.nan

    if "hs_height" not in df.columns:
        msg = "WARNING: hs_height column not found. Cannot backfill hs_height_in."
        print(msg)
        if log:
            log(msg)
        return df

    before_missing = df["hs_height_in"].isna().sum()

    parsed_height = df["hs_height"].apply(parse_height_to_inches)

    needs_fill = df["hs_height_in"].isna() & parsed_height.notna()
    df.loc[needs_fill, "hs_height_in"] = parsed_height.loc[needs_fill]

    after_missing = df["hs_height_in"].isna().sum()

    nonnull_hs_height = df["hs_height"].notna().sum()
    still_missing_with_height = (
        df["hs_height"].notna() & df["hs_height_in"].isna()
    ).sum()

    lines = [
        "\nHeight validation:",
        f"Rows with non-null hs_height: {nonnull_hs_height}",
        f"Missing hs_height_in before backfill: {before_missing}",
        f"Filled hs_height_in from hs_height: {needs_fill.sum()}",
        f"Missing hs_height_in after backfill: {after_missing}",
        f"Rows with hs_height present but hs_height_in still missing: {still_missing_with_height}",
    ]

    for line in lines:
        if log:
            log(line)
        else:
            print(line)

    if still_missing_with_height > 0:
        examples = df.loc[
            df["hs_height"].notna() & df["hs_height_in"].isna(),
            ["hs_height", "hs_height_in"],
        ].head(20)

        if log:
            log("\nExamples where hs_height could not be parsed:")
            log(examples.to_string(index=False))
        else:
            print("\nExamples where hs_height could not be parsed:")
            print(examples.to_string(index=False))

    return df


def make_sample_weights(possessions: pd.Series, k: float = 300) -> pd.Series:
    """
    Possession-based sample weight.

    More possessions = more reliable BPR label.
    Formula:
        weight = possessions / (possessions + k)
    """
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
    """
    Spearman rank correlation without pandas index alignment issues.
    """
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

    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")

    if isinstance(obj, pd.Series):
        return obj.to_dict()

    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [json_safe(v) for v in obj]

    return obj


def prepare_autogluon_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    AutoGluon can handle missing values, but this cleans dtypes enough to
    avoid obvious type weirdness.
    """
    df = df.copy()

    for col in NUMERIC_FEATURES + [TARGET_COL, SAMPLE_WEIGHT_COL]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    for col in CATEGORICAL_FEATURES:
        if col in df.columns:
            df[col] = df[col].astype("string").fillna("__MISSING__").astype(str)
            df[col] = df[col].replace({"<NA>": "__MISSING__", "nan": "__MISSING__"})

    return df


def evaluate_split(predictor: TabularPredictor, df_split: pd.DataFrame, split_name: str):
    y = df_split[TARGET_COL]
    w = df_split["sample_weight"]

    preds = predictor.predict(df_split[FEATURES])

    metrics = {
        "split": split_name,
        "rows": int(len(df_split)),
        "target_mean": float(y.mean()),
        "target_std": float(y.std()),
        "pred_mean": float(np.mean(preds)),
        "pred_std": float(np.std(preds)),
        "mae": float(mean_absolute_error(y, preds)),
        "rmse": float(rmse(y, preds)),
        "weighted_rmse": float(weighted_rmse(y, preds, w)),
        "r2": float(r2_score(y, preds)),
        "corr": safe_corr(y, preds),
        "spearman_corr": safe_spearman(y, preds),
        "sample_weight_mean": float(w.mean()),
        "sample_weight_min": float(w.min()),
        "sample_weight_max": float(w.max()),
        "poss_mean": float(df_split[SAMPLE_WEIGHT_COL].mean()),
        "poss_min": float(df_split[SAMPLE_WEIGHT_COL].min()),
        "poss_max": float(df_split[SAMPLE_WEIGHT_COL].max()),
    }

    pred_df = df_split.copy()
    pred_df["pred_bpr"] = preds
    pred_df["error"] = pred_df[TARGET_COL] - pred_df["pred_bpr"]
    pred_df["abs_error"] = pred_df["error"].abs()

    return metrics, pred_df


# ============================================================
# MAIN TRAINING LOGIC
# ============================================================

def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"autogluon_run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    ag_model_dir = run_dir / "ag_models"
    log_path = run_dir / "training_log.txt"

    def log(msg: str):
        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting AutoGluon BPR training")
    log(f"Run directory: {run_dir}")
    log(f"AutoGluon model directory: {ag_model_dir}")
    log(f"DB path: {DB_PATH}")
    log(f"Table name: {TABLE_NAME}")

    # ----------------------------
    # Load data
    # ----------------------------

    con = duckdb.connect(str(DB_PATH))
    df = con.execute(QUERY).fetchdf()
    con.close()

    log(f"\nRaw rows loaded: {len(df):,}")
    log(f"Raw columns: {list(df.columns)}")

    # ----------------------------
    # Height validation/backfill
    # ----------------------------

    df = ensure_height_in(df, log=log)

    df.to_csv(run_dir / "loaded_data_after_height_validation.csv", index=False)

    # ----------------------------
    # Required columns
    # ----------------------------

    required_cols = FEATURES + [TARGET_COL, SAMPLE_WEIGHT_COL]

    missing_required = [c for c in required_cols if c not in df.columns]
    if missing_required:
        raise ValueError(f"Missing required columns: {missing_required}")

    # ----------------------------
    # Prepare dtypes
    # ----------------------------

    df = prepare_autogluon_frame(df)

    before_filter = len(df)

    df = df[
        df[TARGET_COL].notna()
        & df[SAMPLE_WEIGHT_COL].notna()
        & (df[SAMPLE_WEIGHT_COL] >= MIN_POSSESSIONS)
        & df["hs_year"].notna()
    ].copy()

    after_filter = len(df)

    log("\nFiltering:")
    log(f"Rows before filter: {before_filter:,}")
    log(f"Rows after target/poss/min_poss/hs_year filter: {after_filter:,}")
    log(f"MIN_POSSESSIONS: {MIN_POSSESSIONS}")

    # ----------------------------
    # Sample weights
    # ----------------------------

    df["sample_weight"] = make_sample_weights(
        df[SAMPLE_WEIGHT_COL],
        k=SAMPLE_WEIGHT_K,
    )

    log("\nSample weight summary:")
    log(df["sample_weight"].describe().to_string())

    # ----------------------------
    # Split
    # ----------------------------

    train_df = df[(df["hs_year"] >= 2009) & (df["hs_year"] < 2022)].copy()
    valid_df = df[(df["hs_year"] >= 2022) & (df["hs_year"] <= 2023)].copy()
    test_df = df[(df["hs_year"] >= 2024) & (df["hs_year"] <= 2025)].copy()

    log("\nSplit sizes:")
    log(f"Train rows: {len(train_df):,}")
    log(f"Valid rows: {len(valid_df):,}")
    log(f"Test rows:  {len(test_df):,}")

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

    missing_report = (
        df[FEATURES + [TARGET_COL, SAMPLE_WEIGHT_COL]]
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
    # AutoGluon train frames
    # ----------------------------

    if USE_SAMPLE_WEIGHTS:
        ag_train_cols = FEATURES + [TARGET_COL, "sample_weight"]
        ag_valid_cols = FEATURES + [TARGET_COL, "sample_weight"]
        sample_weight_arg = "sample_weight"
    else:
        ag_train_cols = FEATURES + [TARGET_COL]
        ag_valid_cols = FEATURES + [TARGET_COL]
        sample_weight_arg = None

    ag_train_data = train_df[ag_train_cols].copy()
    ag_valid_data = valid_df[ag_valid_cols].copy()

    log("\nAutoGluon settings:")
    log(f"AG_PRESETS: {AG_PRESETS}")
    log(f"AG_TIME_LIMIT: {AG_TIME_LIMIT}")
    log(f"AG_EVAL_METRIC: {AG_EVAL_METRIC}")
    log(f"USE_SAMPLE_WEIGHTS: {USE_SAMPLE_WEIGHTS}")
    log(f"sample_weight_arg: {sample_weight_arg}")

    # ----------------------------
    # Train AutoGluon
    # ----------------------------

    predictor = TabularPredictor(
        label=TARGET_COL,
        path=str(ag_model_dir),
        problem_type="regression",
        eval_metric=AG_EVAL_METRIC,
        sample_weight=sample_weight_arg,
        verbosity=2,
    )

    predictor.fit(
        train_data=ag_train_data,
        tuning_data=ag_valid_data,
        presets=AG_PRESETS,
        time_limit=AG_TIME_LIMIT,
        hyperparameters=AG_HYPERPARAMETERS,
        num_bag_folds=0,
        num_stack_levels=0,
        dynamic_stacking=False,
        ag_args_fit={
            "random_seed": RANDOM_STATE,
        },
    )

    log("\nAutoGluon training complete.")

    # ----------------------------
    # Leaderboard
    # ----------------------------

    leaderboard_valid = predictor.leaderboard(
        valid_df[FEATURES + [TARGET_COL]],
        silent=True,
    )

    leaderboard_valid.to_csv(run_dir / "leaderboard_valid.csv", index=False)

    log("\nValidation leaderboard:")
    log(leaderboard_valid.to_string(index=False))

    if len(test_df) > 0:
        leaderboard_test = predictor.leaderboard(
            test_df[FEATURES + [TARGET_COL]],
            silent=True,
        )
        leaderboard_test.to_csv(run_dir / "leaderboard_test.csv", index=False)

        log("\nTest leaderboard:")
        log(leaderboard_test.to_string(index=False))

    # ----------------------------
    # Evaluate final AutoGluon predictor
    # ----------------------------

    all_metrics = []

    train_metrics, train_pred_df = evaluate_split(predictor, train_df, "train")
    valid_metrics, valid_pred_df = evaluate_split(predictor, valid_df, "valid")

    all_metrics.extend([train_metrics, valid_metrics])

    train_pred_df.to_csv(run_dir / "train_predictions.csv", index=False)
    valid_pred_df.to_csv(run_dir / "valid_predictions.csv", index=False)

    if len(test_df) > 0:
        test_metrics, test_pred_df = evaluate_split(predictor, test_df, "test")
        all_metrics.append(test_metrics)
        test_pred_df.to_csv(run_dir / "test_predictions.csv", index=False)

    metrics_df = pd.DataFrame(all_metrics)
    metrics_df.to_csv(run_dir / "final_metrics.csv", index=False)

    log("\nFinal metrics:")
    log(metrics_df.to_string(index=False))

    # ----------------------------
    # Feature importance
    # ----------------------------

    try:
        fi_valid = predictor.feature_importance(
            data=valid_df[FEATURES + [TARGET_COL]],
            time_limit=300,
        )

        fi_valid.to_csv(run_dir / "feature_importance_valid.csv")

        log("\nFeature importance on validation:")
        log(fi_valid.to_string())

    except Exception as e:
        log("\nWARNING: Feature importance failed.")
        log(str(e))

    # ----------------------------
    # Save predictor object reference
    # ----------------------------

    # AutoGluon saves the full predictor to ag_model_dir automatically.
    # This pickle just stores the loaded predictor object reference if needed.
    try:
        with open(run_dir / "autogluon_predictor_reference.pkl", "wb") as f:
            pickle.dump(predictor, f)
    except Exception as e:
        log("\nWARNING: Pickle save failed. AutoGluon model directory is still saved.")
        log(str(e))

    # ----------------------------
    # Optional refit full / train+valid model
    # ----------------------------
    # AutoGluon can refit selected models on full data. This is useful for production,
    # but the clean test metrics above should be the main reported result.

    try:
        log("\nRunning AutoGluon refit_full...")
        refit_map = predictor.refit_full()
        log("refit_full complete.")
        log(json.dumps(json_safe(refit_map), indent=2))

        with open(run_dir / "refit_full_map.json", "w", encoding="utf-8") as f:
            json.dump(json_safe(refit_map), f, indent=2)

        if len(test_df) > 0:
            refit_model_name = predictor.model_best
            log(f"\nBest model after refit_full: {refit_model_name}")

            refit_preds = predictor.predict(
                test_df[FEATURES],
                model=refit_model_name,
            )

            y = test_df[TARGET_COL]
            w = test_df["sample_weight"]

            refit_test_metrics = {
                "split": "test_refit_full",
                "model": refit_model_name,
                "rows": int(len(test_df)),
                "target_mean": float(y.mean()),
                "target_std": float(y.std()),
                "pred_mean": float(np.mean(refit_preds)),
                "pred_std": float(np.std(refit_preds)),
                "mae": float(mean_absolute_error(y, refit_preds)),
                "rmse": float(rmse(y, refit_preds)),
                "weighted_rmse": float(weighted_rmse(y, refit_preds, w)),
                "r2": float(r2_score(y, refit_preds)),
                "corr": safe_corr(y, refit_preds),
                "spearman_corr": safe_spearman(y, refit_preds),
            }

            refit_test_pred_df = test_df.copy()
            refit_test_pred_df["pred_bpr"] = refit_preds
            refit_test_pred_df["error"] = (
                refit_test_pred_df[TARGET_COL] - refit_test_pred_df["pred_bpr"]
            )
            refit_test_pred_df["abs_error"] = refit_test_pred_df["error"].abs()

            refit_test_pred_df.to_csv(
                run_dir / "test_predictions_refit_full.csv",
                index=False,
            )

            with open(run_dir / "refit_full_test_metrics.json", "w", encoding="utf-8") as f:
                json.dump(json_safe(refit_test_metrics), f, indent=2)

            log("\nRefit full test metrics:")
            log(json.dumps(json_safe(refit_test_metrics), indent=2))

    except Exception as e:
        log("\nWARNING: refit_full failed.")
        log(str(e))

    # ----------------------------
    # Save config
    # ----------------------------

    config = {
        "db_path": str(DB_PATH),
        "table_name": TABLE_NAME,
        "output_dir": str(OUTPUT_DIR),
        "run_dir": str(run_dir),
        "ag_model_dir": str(ag_model_dir),
        "target_col": TARGET_COL,
        "sample_weight_col": SAMPLE_WEIGHT_COL,
        "min_possessions": int(MIN_POSSESSIONS),
        "sample_weight_k": float(SAMPLE_WEIGHT_K),
        "features": list(FEATURES),
        "numeric_features": list(NUMERIC_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "ag_presets": AG_PRESETS,
        "ag_time_limit": AG_TIME_LIMIT,
        "ag_eval_metric": AG_EVAL_METRIC,
        "use_sample_weights": bool(USE_SAMPLE_WEIGHTS),
        "random_state": int(RANDOM_STATE),
        "split": {
            "train": "2009 <= hs_year < 2022",
            "valid": "2022 <= hs_year <= 2023",
            "test": "2024 <= hs_year <= 2025",
        },
        "query": QUERY,
        "ag_hyperparameters": AG_HYPERPARAMETERS
    }

    with open(run_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(json_safe(config), f, indent=2)

    if SAVE_SPACE_AFTER_TRAINING:
        try:
            log("\nSaving space via predictor.save_space()...")
            predictor.save_space()
        except Exception as e:
            log("\nWARNING: save_space failed.")
            log(str(e))

    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")
    log(f"AutoGluon model saved to: {ag_model_dir}")


if __name__ == "__main__":
    main()