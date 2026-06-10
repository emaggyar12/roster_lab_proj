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

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = PROJECT_ROOT / "data_dir" / "hs_to_evan_match.db"
TABLE_NAME = "hs_to_evan_global_matched"

OUTPUT_DIR = Path("catboost_bpr_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_COL = "college_basic_bpr"
SAMPLE_WEIGHT_COL = "college_basic_poss"

MIN_POSSESSIONS = 150
SAMPLE_WEIGHT_K = 300

N_OPTUNA_TRIALS = 75
OPTUNA_TIMEOUT_SECONDS = None  # example: 1800 for 30 minutes; None = no time limit

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

# If True, Optuna selects best params by validation weighted RMSE.
# If False, selects by ordinary validation RMSE.
OPTIMIZE_WEIGHTED_RMSE = True

# CatBoost final training settings
FINAL_VERBOSE = 100
OPTUNA_VERBOSE = False


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
        print(line)
        if log:
            log(line)

    if still_missing_with_height > 0:
        examples = df.loc[
            df["hs_height"].notna() & df["hs_height_in"].isna(),
            ["hs_height", "hs_height_in"],
        ].head(20)

        print("\nExamples where hs_height could not be parsed:")
        print(examples.to_string(index=False))

        if log:
            log("\nExamples where hs_height could not be parsed:")
            log(examples.to_string(index=False))

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
    if len(y_true) <= 1:
        return np.nan

    if np.std(y_true) == 0 or np.std(y_pred) == 0:
        return np.nan

    return float(np.corrcoef(y_true, y_pred)[0, 1])


def safe_spearman(y_true, y_pred):
    if len(y_true) <= 1:
        return np.nan

    s1 = pd.Series(y_true).rank(method="average")
    s2 = pd.Series(y_pred).rank(method="average")

    if s1.std() == 0 or s2.std() == 0:
        return np.nan

    return float(s1.corr(s2))


def prepare_catboost_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    CatBoost can handle numeric NaNs, but categorical missing values should be
    filled and cast to string.
    """
    df = df.copy()

    for col in NUMERIC_FEATURES + [TARGET_COL, SAMPLE_WEIGHT_COL]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in CATEGORICAL_FEATURES:
        if col in df.columns:
            df[col] = df[col].astype("string").fillna("__MISSING__").astype(str)
            df[col] = df[col].replace({"<NA>": "__MISSING__", "nan": "__MISSING__"})

    return df


def evaluate_split(model, df_split, split_name):
    X = df_split[FEATURES]
    y = df_split[TARGET_COL]
    w = df_split["sample_weight"]

    preds = model.predict(X)

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


def make_pool(df: pd.DataFrame) -> Pool:
    return Pool(
        data=df[FEATURES],
        label=df[TARGET_COL],
        weight=df["sample_weight"],
        cat_features=CATEGORICAL_FEATURES,
    )


def make_prediction_pool(df: pd.DataFrame) -> Pool:
    return Pool(
        data=df[FEATURES],
        cat_features=CATEGORICAL_FEATURES,
    )


def json_safe(obj):
    """
    Converts common non-JSON-safe objects into JSON-safe versions.
    """
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
# MAIN TRAINING LOGIC
# ============================================================

def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"catboost_run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "training_log.txt"

    def log(msg: str):
        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting CatBoost BPR training with Optuna")
    log(f"Run directory: {run_dir}")
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

    df = prepare_catboost_frame(df)

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
    # Pools
    # ----------------------------

    train_pool = make_pool(train_df)
    valid_pool = make_pool(valid_df)

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

            # Search space
            "iterations": trial.suggest_int("iterations", 300, 3000),
            "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.12, log=True),
            "depth": trial.suggest_int("depth", 3, 8),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 50.0, log=True),
            "random_strength": trial.suggest_float("random_strength", 0.0, 10.0),
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 10.0),
            "border_count": trial.suggest_categorical("border_count", [32, 64, 128, 254]),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 1, 40),

            # Overfitting control
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

        if OPTIMIZE_WEIGHTED_RMSE:
            score = weighted_rmse(
                valid_df[TARGET_COL],
                valid_preds,
                valid_df["sample_weight"],
            )
        else:
            score = rmse(valid_df[TARGET_COL], valid_preds)

        trial.set_user_attr("best_iteration", int(model.get_best_iteration()))
        trial.set_user_attr("valid_rmse", float(rmse(valid_df[TARGET_COL], valid_preds)))
        trial.set_user_attr(
            "valid_weighted_rmse",
            float(weighted_rmse(valid_df[TARGET_COL], valid_preds, valid_df["sample_weight"])),
        )
        trial.set_user_attr("valid_mae", float(mean_absolute_error(valid_df[TARGET_COL], valid_preds)))
        trial.set_user_attr("valid_r2", float(r2_score(valid_df[TARGET_COL], valid_preds)))
        trial.set_user_attr("valid_corr", safe_corr(valid_df[TARGET_COL], valid_preds))
        trial.set_user_attr("valid_spearman_corr", safe_spearman(valid_df[TARGET_COL], valid_preds))

        return float(score)

    # ----------------------------
    # Run Optuna
    # ----------------------------

    log("\nStarting Optuna search...")
    log(f"N_OPTUNA_TRIALS: {N_OPTUNA_TRIALS}")
    log(f"OPTUNA_TIMEOUT_SECONDS: {OPTUNA_TIMEOUT_SECONDS}")
    log(f"Optimization target: {'valid_weighted_rmse' if OPTIMIZE_WEIGHTED_RMSE else 'valid_rmse'}")

    sampler = optuna.samplers.TPESampler(seed=RANDOM_STATE)
    study = optuna.create_study(
        direction="minimize",
        sampler=sampler,
        study_name=f"catboost_bpr_{run_id}",
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

    # Save Optuna trials
    trials_df = study.trials_dataframe(attrs=("number", "value", "params", "user_attrs", "state"))
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

    # If Optuna did not include od_wait for some reason, set a default.
    if "od_wait" not in final_params:
        final_params["od_wait"] = 100

    log("\nTraining final CatBoost model with best Optuna params...")
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

    train_metrics, train_pred_df = evaluate_split(final_model, train_df, "train")
    valid_metrics, valid_pred_df = evaluate_split(final_model, valid_df, "valid")

    all_metrics.extend([train_metrics, valid_metrics])

    train_pred_df.to_csv(run_dir / "train_predictions.csv", index=False)
    valid_pred_df.to_csv(run_dir / "valid_predictions.csv", index=False)

    if len(test_df) > 0:
        test_metrics, test_pred_df = evaluate_split(final_model, test_df, "test")
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
    # Save model
    # ----------------------------

    cbm_path = run_dir / "catboost_bpr_model.cbm"
    pkl_path = run_dir / "catboost_bpr_model.pkl"

    final_model.save_model(str(cbm_path))

    with open(pkl_path, "wb") as f:
        pickle.dump(final_model, f)

    log(f"\nSaved CatBoost model: {cbm_path}")
    log(f"Saved pickle model: {pkl_path}")

    # ----------------------------
    # Optional production model: train on train + valid
    # ----------------------------
    # This is useful after you have accepted the tuned params.
    # The test metrics above are from the model trained on train only and validated on valid.
    # This production model uses more data, so do not use it for clean test reporting.

    train_valid_df = pd.concat([train_df, valid_df], axis=0).copy()
    train_valid_pool = make_pool(train_valid_df)

    production_params = dict(final_params)
    production_params["use_best_model"] = False
    production_params["verbose"] = FINAL_VERBOSE

    # Use best iteration from validation-tuned model if available.
    best_iter = final_model.get_best_iteration()
    if best_iter is not None and best_iter > 0:
        production_params["iterations"] = int(best_iter)

    log("\nTraining production CatBoost model on train + valid...")
    log(json.dumps(json_safe(production_params), indent=2))

    production_model = CatBoostRegressor(**production_params)
    production_model.fit(
        train_valid_pool,
        verbose=FINAL_VERBOSE,
    )

    production_cbm_path = run_dir / "catboost_bpr_production_train_valid_model.cbm"
    production_pkl_path = run_dir / "catboost_bpr_production_train_valid_model.pkl"

    production_model.save_model(str(production_cbm_path))

    with open(production_pkl_path, "wb") as f:
        pickle.dump(production_model, f)

    log(f"\nSaved production CatBoost model: {production_cbm_path}")
    log(f"Saved production pickle model: {production_pkl_path}")

    if len(test_df) > 0:
        prod_test_metrics, prod_test_pred_df = evaluate_split(
            production_model,
            test_df,
            "test_production_train_valid",
        )
        prod_test_pred_df.to_csv(run_dir / "test_predictions_production_train_valid.csv", index=False)

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
        "sample_weight_col": SAMPLE_WEIGHT_COL,
        "min_possessions": int(MIN_POSSESSIONS),
        "sample_weight_k": float(SAMPLE_WEIGHT_K),
        "features": list(FEATURES),
        "numeric_features": list(NUMERIC_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "n_optuna_trials": int(N_OPTUNA_TRIALS),
        "optuna_timeout_seconds": OPTUNA_TIMEOUT_SECONDS,
        "optimize_weighted_rmse": bool(OPTIMIZE_WEIGHTED_RMSE),
        "random_state": int(RANDOM_STATE),
        "best_trial": best_trial_info,
        "final_params": final_params,
        "production_params": production_params,
        "split": {
            "train": "2009 <= hs_year < 2022",
            "valid": "2022 <= hs_year <= 2023",
            "test": "2024 <= hs_year <= 2025",
        },
        "query": QUERY,
    }

    with open(run_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(json_safe(config), f, indent=2)

    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")


if __name__ == "__main__":
    main()