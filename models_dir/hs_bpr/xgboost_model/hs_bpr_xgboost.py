import json
import re
import pickle
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import optuna
import pandas as pd
import xgboost as xgb

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error,
    root_mean_squared_error,
    r2_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


# ============================================================
# USER SETTINGS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = PROJECT_ROOT / "data_dir" / "hs_to_evan_match.db"
TABLE_NAME = "hs_to_evan_global_matched"

OUTPUT_DIR = Path("xgboost_bpr_outputs")
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

# XGBoost stability settings.
# Set N_JOBS = 1 first on your Mac because XGBoost segfaulted through AutoGluon.
# If stable, you can try 2 or 4 later.
N_JOBS = 1

FINAL_VERBOSE_EVAL = 100
OPTUNA_VERBOSE_EVAL = False


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


def prepare_xgboost_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    XGBoost receives numeric matrix after preprocessing.

    Numeric:
      - converted to float64
      - median imputed later by sklearn preprocessor

    Categorical:
      - missing filled as __MISSING__
      - one-hot encoded later
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


def make_preprocessor() -> ColumnTransformer:
    numeric_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=True,
                ),
            ),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_pipeline, NUMERIC_FEATURES),
            ("cat", categorical_pipeline, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
        sparse_threshold=0.3,
    )

    return preprocessor


def make_dmatrix(X, y=None, weight=None, feature_names=None):
    return xgb.DMatrix(
        data=X,
        label=y,
        weight=weight,
        feature_names=feature_names,
    )


def predict_booster(model: xgb.Booster, dmatrix: xgb.DMatrix):
    best_iteration = getattr(model, "best_iteration", None)

    if best_iteration is not None and best_iteration >= 0:
        return model.predict(dmatrix, iteration_range=(0, best_iteration + 1))

    return model.predict(dmatrix)


def evaluate_split(model, dmatrix, df_split, split_name):
    y = df_split[TARGET_COL]
    w = df_split["sample_weight"]

    preds = predict_booster(model, dmatrix)

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
# MAIN TRAINING LOGIC
# ============================================================

def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"xgboost_run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "training_log.txt"

    def log(msg: str):
        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting XGBoost BPR training with Optuna")
    log(f"Run directory: {run_dir}")
    log(f"DB path: {DB_PATH}")
    log(f"Table name: {TABLE_NAME}")
    log(f"XGBoost version: {xgb.__version__}")

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

    df = prepare_xgboost_frame(df)

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
    # Preprocessing
    # ----------------------------

    log("\nFitting preprocessing pipeline...")

    preprocessor = make_preprocessor()

    X_train = preprocessor.fit_transform(train_df[FEATURES])
    X_valid = preprocessor.transform(valid_df[FEATURES])
    X_test = preprocessor.transform(test_df[FEATURES]) if len(test_df) > 0 else None

    feature_names = list(preprocessor.get_feature_names_out())

    log(f"Original feature count: {len(FEATURES)}")
    log(f"Transformed feature count: {len(feature_names)}")

    with open(run_dir / "xgboost_feature_names.json", "w", encoding="utf-8") as f:
        json.dump(feature_names, f, indent=2)

    with open(run_dir / "preprocessor.pkl", "wb") as f:
        pickle.dump(preprocessor, f)

    log("Saved preprocessor.pkl")

    # ----------------------------
    # DMatrices
    # ----------------------------

    dtrain = make_dmatrix(
        X_train,
        y=train_df[TARGET_COL],
        weight=train_df["sample_weight"],
        feature_names=feature_names,
    )

    dvalid = make_dmatrix(
        X_valid,
        y=valid_df[TARGET_COL],
        weight=valid_df["sample_weight"],
        feature_names=feature_names,
    )

    dtest = None
    if len(test_df) > 0:
        dtest = make_dmatrix(
            X_test,
            y=test_df[TARGET_COL],
            weight=test_df["sample_weight"],
            feature_names=feature_names,
        )

    # ----------------------------
    # Optuna objective
    # ----------------------------

    def objective(trial: optuna.Trial) -> float:
        num_boost_round = trial.suggest_int("num_boost_round", 300, 3000)
        early_stopping_rounds = trial.suggest_int("early_stopping_rounds", 50, 250)

        params = {
            "objective": "reg:squarederror",
            "eval_metric": "rmse",
            "tree_method": "hist",
            "seed": RANDOM_STATE,
            "nthread": N_JOBS,
            "verbosity": 0,

            # Search space
            "eta": trial.suggest_float("eta", 0.005, 0.12, log=True),
            "max_depth": trial.suggest_int("max_depth", 2, 8),
            "min_child_weight": trial.suggest_float("min_child_weight", 0.1, 30.0, log=True),
            "subsample": trial.suggest_float("subsample", 0.55, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.55, 1.0),
            "lambda": trial.suggest_float("lambda", 0.1, 100.0, log=True),
            "alpha": trial.suggest_float("alpha", 0.0, 20.0),
            "gamma": trial.suggest_float("gamma", 0.0, 20.0),
            "max_bin": trial.suggest_categorical("max_bin", [64, 128, 256, 512]),
        }

        evals = [(dtrain, "train"), (dvalid, "valid")]

        model = xgb.train(
            params=params,
            dtrain=dtrain,
            num_boost_round=num_boost_round,
            evals=evals,
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=OPTUNA_VERBOSE_EVAL,
        )

        valid_preds = predict_booster(model, dvalid)

        valid_rmse = rmse(valid_df[TARGET_COL], valid_preds)
        valid_weighted_rmse = weighted_rmse(
            valid_df[TARGET_COL],
            valid_preds,
            valid_df["sample_weight"],
        )

        score = valid_weighted_rmse if OPTIMIZE_WEIGHTED_RMSE else valid_rmse

        best_iteration = getattr(model, "best_iteration", None)
        best_score = getattr(model, "best_score", None)

        trial.set_user_attr(
            "best_iteration",
            int(best_iteration) if best_iteration is not None else None,
        )
        trial.set_user_attr(
            "best_score_xgb",
            float(best_score) if best_score is not None else None,
        )
        trial.set_user_attr("valid_rmse", float(valid_rmse))
        trial.set_user_attr("valid_weighted_rmse", float(valid_weighted_rmse))
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
    log(f"N_JOBS: {N_JOBS}")
    log(f"Optimization target: {'valid_weighted_rmse' if OPTIMIZE_WEIGHTED_RMSE else 'valid_rmse'}")

    sampler = optuna.samplers.TPESampler(seed=RANDOM_STATE)
    study = optuna.create_study(
        direction="minimize",
        sampler=sampler,
        study_name=f"xgboost_bpr_{run_id}",
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

    final_num_boost_round = int(best_params.pop("num_boost_round"))
    final_early_stopping_rounds = int(best_params.pop("early_stopping_rounds"))

    final_params = {
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "tree_method": "hist",
        "seed": RANDOM_STATE,
        "nthread": N_JOBS,
        "verbosity": 1,
        **best_params,
    }

    log("\nTraining final XGBoost model with best Optuna params...")
    log(json.dumps(json_safe({
        "params": final_params,
        "num_boost_round": final_num_boost_round,
        "early_stopping_rounds": final_early_stopping_rounds,
    }), indent=2))

    final_model = xgb.train(
        params=final_params,
        dtrain=dtrain,
        num_boost_round=final_num_boost_round,
        evals=[(dtrain, "train"), (dvalid, "valid")],
        early_stopping_rounds=final_early_stopping_rounds,
        verbose_eval=FINAL_VERBOSE_EVAL,
    )

    final_best_iteration = getattr(final_model, "best_iteration", None)
    log(f"\nFinal model best iteration: {final_best_iteration}")

    # ----------------------------
    # Evaluate final model
    # ----------------------------

    all_metrics = []

    train_metrics, train_pred_df = evaluate_split(final_model, dtrain, train_df, "train")
    valid_metrics, valid_pred_df = evaluate_split(final_model, dvalid, valid_df, "valid")

    all_metrics.extend([train_metrics, valid_metrics])

    train_pred_df.to_csv(run_dir / "train_predictions.csv", index=False)
    valid_pred_df.to_csv(run_dir / "valid_predictions.csv", index=False)

    if len(test_df) > 0:
        test_metrics, test_pred_df = evaluate_split(final_model, dtest, test_df, "test")
        all_metrics.append(test_metrics)
        test_pred_df.to_csv(run_dir / "test_predictions.csv", index=False)

    metrics_df = pd.DataFrame(all_metrics)
    metrics_df.to_csv(run_dir / "final_metrics.csv", index=False)

    log("\nFinal metrics:")
    log(metrics_df.to_string(index=False))

    # ----------------------------
    # Feature importance
    # ----------------------------

    importance_gain = final_model.get_score(importance_type="gain")
    importance_weight = final_model.get_score(importance_type="weight")
    importance_cover = final_model.get_score(importance_type="cover")

    fi_rows = []
    for feature in feature_names:
        fi_rows.append({
            "feature": feature,
            "gain": importance_gain.get(feature, 0.0),
            "weight": importance_weight.get(feature, 0.0),
            "cover": importance_cover.get(feature, 0.0),
        })

    fi_df = pd.DataFrame(fi_rows).sort_values("gain", ascending=False)
    fi_df.to_csv(run_dir / "xgboost_feature_importance.csv", index=False)

    log("\nFeature importance by gain:")
    log(fi_df.head(50).to_string(index=False))

    # ----------------------------
    # Save model
    # ----------------------------

    json_model_path = run_dir / "xgboost_bpr_model.json"
    pkl_model_path = run_dir / "xgboost_bpr_model.pkl"

    final_model.save_model(str(json_model_path))

    with open(pkl_model_path, "wb") as f:
        pickle.dump(final_model, f)

    log(f"\nSaved XGBoost model: {json_model_path}")
    log(f"Saved pickle model: {pkl_model_path}")

    # ----------------------------
    # Optional production model: train on train + valid
    # ----------------------------
    # This is useful after you have accepted the tuned params.
    # Clean test reporting should use the train-only final_model above.

    train_valid_df = pd.concat([train_df, valid_df], axis=0).copy()

    production_preprocessor = make_preprocessor()
    X_train_valid = production_preprocessor.fit_transform(train_valid_df[FEATURES])

    production_feature_names = list(production_preprocessor.get_feature_names_out())

    dtrain_valid = make_dmatrix(
        X_train_valid,
        y=train_valid_df[TARGET_COL],
        weight=train_valid_df["sample_weight"],
        feature_names=production_feature_names,
    )

    production_num_boost_round = final_best_iteration
    if production_num_boost_round is None or production_num_boost_round <= 0:
        production_num_boost_round = final_num_boost_round
    else:
        production_num_boost_round = int(production_num_boost_round) + 1

    production_params = dict(final_params)

    log("\nTraining production XGBoost model on train + valid...")
    log(json.dumps(json_safe({
        "params": production_params,
        "num_boost_round": production_num_boost_round,
    }), indent=2))

    production_model = xgb.train(
        params=production_params,
        dtrain=dtrain_valid,
        num_boost_round=production_num_boost_round,
        evals=[(dtrain_valid, "train_valid")],
        verbose_eval=FINAL_VERBOSE_EVAL,
    )

    production_json_model_path = run_dir / "xgboost_bpr_production_train_valid_model.json"
    production_pkl_model_path = run_dir / "xgboost_bpr_production_train_valid_model.pkl"
    production_preprocessor_path = run_dir / "production_preprocessor.pkl"

    production_model.save_model(str(production_json_model_path))

    with open(production_pkl_model_path, "wb") as f:
        pickle.dump(production_model, f)

    with open(production_preprocessor_path, "wb") as f:
        pickle.dump(production_preprocessor, f)

    log(f"\nSaved production XGBoost model: {production_json_model_path}")
    log(f"Saved production pickle model: {production_pkl_model_path}")
    log(f"Saved production preprocessor: {production_preprocessor_path}")

    if len(test_df) > 0:
        X_test_prod = production_preprocessor.transform(test_df[FEATURES])

        dtest_prod = make_dmatrix(
            X_test_prod,
            y=test_df[TARGET_COL],
            weight=test_df["sample_weight"],
            feature_names=production_feature_names,
        )

        prod_test_metrics, prod_test_pred_df = evaluate_split(
            production_model,
            dtest_prod,
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
        "n_jobs": int(N_JOBS),
        "best_trial": best_trial_info,
        "final_params": final_params,
        "final_num_boost_round": int(final_num_boost_round),
        "final_early_stopping_rounds": int(final_early_stopping_rounds),
        "production_params": production_params,
        "production_num_boost_round": int(production_num_boost_round),
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