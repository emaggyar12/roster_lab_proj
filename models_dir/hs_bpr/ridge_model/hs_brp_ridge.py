import json
import re
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


# ============================================================
# USER SETTINGS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = PROJECT_ROOT / 'data_dir' / "hs_to_evan_match.db"
TABLE_NAME = 'hs_to_evan_global_matched'

OUTPUT_DIR = Path("ridge_bpr_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_COL = "college_basic_bpr"
SAMPLE_WEIGHT_COL = "college_basic_poss"

MIN_POSSESSIONS = 150
SAMPLE_WEIGHT_K = 300

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

# Ridge alpha values to try.
# Larger alpha = stronger regularization.
ALPHAS = [
    0.01,
    0.03,
    0.1,
    0.3,
    1.0,
    3.0,
    10.0,
    30.0,
    100.0,
    300.0,
    1000.0,
]

RANDOM_STATE = 42


# ============================================================
# QUERY
# ============================================================

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
FROM {TABLE_NAME}
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

    # Already numeric inches
    try:
        x = float(s)
        if 48 <= x <= 96:
            return x
    except ValueError:
        pass

    # Normalize common separators
    s = s.lower()
    s = s.replace("ft", "'")
    s = s.replace("feet", "'")
    s = s.replace("inches", "")
    s = s.replace("inch", "")
    s = s.replace('"', "")
    s = s.replace("’", "'")
    s = s.replace("`", "'")

    # Match 6-7, 6'7, 6 7
    match = re.search(r"(\d+)\s*[-'\s]\s*(\d+)", s)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2))
        total = feet * 12 + inches
        if 48 <= total <= 96:
            return float(total)

    return np.nan


def ensure_height_in(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensures hs_height_in exists where possible.

    If hs_height_in is null but hs_height is non-null, this fills hs_height_in
    using parsed hs_height.
    """
    df = df.copy()

    if "hs_height_in" not in df.columns:
        df["hs_height_in"] = np.nan

    if "hs_height" not in df.columns:
        print("WARNING: hs_height column not found. Cannot backfill hs_height_in.")
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

    print("\nHeight validation:")
    print(f"Rows with non-null hs_height: {nonnull_hs_height}")
    print(f"Missing hs_height_in before backfill: {before_missing}")
    print(f"Filled hs_height_in from hs_height: {needs_fill.sum()}")
    print(f"Missing hs_height_in after backfill: {after_missing}")
    print(f"Rows with hs_height present but hs_height_in still missing: {still_missing_with_height}")

    if still_missing_with_height > 0:
        examples = df.loc[
            df["hs_height"].notna() & df["hs_height_in"].isna(),
            ["hs_height", "hs_height_in"]
        ].head(20)

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
        "corr": float(np.corrcoef(y, preds)[0, 1]) if len(df_split) > 1 else np.nan,
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


def build_ridge_pipeline(alpha: float) -> Pipeline:
    numeric_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
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
    )

    model = Ridge(alpha=alpha, random_state=RANDOM_STATE)

    pipe = Pipeline(
        steps=[
            ("preprocess", preprocessor),
            ("model", model),
        ]
    )

    return pipe


# ============================================================
# MAIN TRAINING LOGIC
# ============================================================

def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"ridge_run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "training_log.txt"

    def log(msg: str):
        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")

    log("Starting Ridge BPR training")
    log(f"Run directory: {run_dir}")
    log(f"DB path: {DB_PATH}")

    # ----------------------------
    # Load data
    # ----------------------------

    con = duckdb.connect(DB_PATH)
    df = con.execute(QUERY).fetchdf()
    con.close()

    log(f"\nRaw rows loaded: {len(df):,}")
    log(f"Raw columns: {list(df.columns)}")

    # ----------------------------
    # Height validation/backfill
    # ----------------------------

    df = ensure_height_in(df)

    # Save post-height-validation raw data snapshot
    df.to_csv(run_dir / "loaded_data_after_height_validation.csv", index=False)

    # ----------------------------
    # Basic filtering
    # ----------------------------

    required_cols = FEATURES + [TARGET_COL, SAMPLE_WEIGHT_COL]

    missing_required = [c for c in required_cols if c not in df.columns]
    if missing_required:
        raise ValueError(f"Missing required columns: {missing_required}")

    before_filter = len(df)

    df = df[
        df[TARGET_COL].notna()
        & df[SAMPLE_WEIGHT_COL].notna()
        & (df[SAMPLE_WEIGHT_COL] >= MIN_POSSESSIONS)
    ].copy()

    after_target_poss_filter = len(df)

    log("\nFiltering:")
    log(f"Rows before filter: {before_filter:,}")
    log(f"Rows after target/poss/min_poss filter: {after_target_poss_filter:,}")
    log(f"MIN_POSSESSIONS: {MIN_POSSESSIONS}")

    # ----------------------------
    # Coerce numeric columns
    # ----------------------------

    for col in NUMERIC_FEATURES + [TARGET_COL, SAMPLE_WEIGHT_COL]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    before_numeric_drop = len(df)

    df = df[
        df[TARGET_COL].notna()
        & df[SAMPLE_WEIGHT_COL].notna()
        & df["hs_year"].notna()
    ].copy()

    after_numeric_drop = len(df)

    log(f"Rows before numeric coercion drop: {before_numeric_drop:,}")
    log(f"Rows after numeric coercion drop: {after_numeric_drop:,}")

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

    # Save splits
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
    # Train alpha sweep
    # ----------------------------

    X_train = train_df[FEATURES]
    y_train = train_df[TARGET_COL]
    w_train = train_df["sample_weight"]

    alpha_results = []

    log("\nTraining Ridge alpha sweep...")

    for alpha in ALPHAS:
        log(f"\nTraining alpha={alpha}")

        model = build_ridge_pipeline(alpha=alpha)

        model.fit(
            X_train,
            y_train,
            model__sample_weight=w_train,
        )

        train_metrics, _ = evaluate_split(model, train_df, "train")
        valid_metrics, _ = evaluate_split(model, valid_df, "valid")

        row = {
            "alpha": alpha,
            "train_rmse": train_metrics["rmse"],
            "train_weighted_rmse": train_metrics["weighted_rmse"],
            "train_mae": train_metrics["mae"],
            "train_r2": train_metrics["r2"],
            "train_corr": train_metrics["corr"],
            "valid_rmse": valid_metrics["rmse"],
            "valid_weighted_rmse": valid_metrics["weighted_rmse"],
            "valid_mae": valid_metrics["mae"],
            "valid_r2": valid_metrics["r2"],
            "valid_corr": valid_metrics["corr"],
        }

        alpha_results.append(row)

        log(json.dumps(row, indent=2))

    alpha_results_df = pd.DataFrame(alpha_results)
    alpha_results_df = alpha_results_df.sort_values("valid_weighted_rmse")

    alpha_results_df.to_csv(run_dir / "alpha_results.csv", index=False)

    best_alpha = float(alpha_results_df.iloc[0]["alpha"])

    log("\nBest alpha selected by validation weighted RMSE:")
    log(f"best_alpha = {best_alpha}")

    # ----------------------------
    # Final model
    # ----------------------------

    final_model = build_ridge_pipeline(alpha=best_alpha)

    final_model.fit(
        X_train,
        y_train,
        model__sample_weight=w_train,
    )

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
    # Coefficients
    # ----------------------------

    preprocessor = final_model.named_steps["preprocess"]
    ridge_model = final_model.named_steps["model"]

    feature_names = preprocessor.get_feature_names_out()
    coefficients = ridge_model.coef_

    coef_df = pd.DataFrame(
        {
            "feature": feature_names,
            "coefficient": coefficients,
            "abs_coefficient": np.abs(coefficients),
        }
    ).sort_values("abs_coefficient", ascending=False)

    coef_df.to_csv(run_dir / "ridge_coefficients.csv", index=False)

    log("\nTop Ridge coefficients by absolute value:")
    log(coef_df.head(50).to_string(index=False))

    # ----------------------------
    # Save config
    # ----------------------------

    config = {
        "db_path": str(DB_PATH),
        "target_col": TARGET_COL,
        "sample_weight_col": SAMPLE_WEIGHT_COL,
        "min_possessions": MIN_POSSESSIONS,
        "sample_weight_k": SAMPLE_WEIGHT_K,
        "features": FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "alphas": ALPHAS,
        "best_alpha": best_alpha,
        "split": {
            "train": "2009 <= hs_year < 2022",
            "valid": "2022 <= hs_year <= 2023",
            "test": "2024 <= hs_year <= 2025",
        },
        "query": QUERY,
    }

    with open(run_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    log("\nDone.")
    log(f"Outputs saved to: {run_dir}")


if __name__ == "__main__":
    main()