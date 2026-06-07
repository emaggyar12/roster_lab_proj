import json
import re
from pathlib import Path

import duckdb
import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = Path(__file__).resolve().parents[0]

DB_PATH = PROJECT_ROOT / "data_dir" / "bv_trans_compl_MAX.db"
ARTIFACT_DIR = MODEL_DIR / "artifacts" / "transfer_role_catboost"

SOURCE_TABLE = "all_years_transfer_matched"

TARGET_COL = "future_role"
YEAR_COL = "allyears_year"

RAW_HEIGHT_COL = "allyears_player_height"
HEIGHT_IN_COL = "allyears_player_height_in"

N_TRIALS = 50
RANDOM_SEED = 42


TRAINING_QUERY = f"""
    SELECT
        future_role,
        allyears_year,

        allyears_gp,
        allyears_min_per,
        allyears_ortg,
        allyears_usg,
        allyears_efg,
        allyears_ts_per,
        allyears_orb_per,
        allyears_drb_per,
        allyears_ast_per,
        allyears_to_per,
        allyears_ftm,
        allyears_fta,
        allyears_ft_per,
        allyears_twopm,
        allyears_twopa,
        allyears_twop_per,
        allyears_tpm,
        allyears_tpa,
        allyears_tp_per,
        allyears_blk_per,
        allyears_stl_per,
        allyears_ftr,
        allyears_porpag,
        allyears_adjoe,
        allyears_ast_tov,
        allyears_rimmade,
        allyears_rimmade_rimmiss,
        allyears_midmade,
        allyears_midmade_midmiss,
        allyears_rimmade_rimmade_rimmiss,
        allyears_midmade_midmade_midmiss,
        allyears_dunksmade,
        allyears_dunksmiss_dunksmade,
        allyears_dunksmade_dunksmade_dunksmiss,
        allyears_drtg,
        allyears_adrtg,
        allyears_dporpag,
        allyears_stops,
        allyears_bpm,
        allyears_obpm,
        allyears_dbpm,
        allyears_gbpm,
        allyears_mp,
        allyears_ogbpm,
        allyears_dgbpm,
        allyears_oreb,
        allyears_dreb,
        allyears_treb,
        allyears_ast,
        allyears_stl,
        allyears_blk,
        allyears_pts,
        allyears_3p_100,
        allyears_player_height,
        allyears_role
    FROM {SOURCE_TABLE}
    WHERE future_role IS NOT NULL
      AND allyears_year IS NOT NULL
"""


NUMERIC_FEATURE_COLS = [
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
    "allyears_ftm",
    "allyears_fta",
    "allyears_ft_per",
    "allyears_twopm",
    "allyears_twopa",
    "allyears_twop_per",
    "allyears_tpm",
    "allyears_tpa",
    "allyears_tp_per",
    "allyears_blk_per",
    "allyears_stl_per",
    "allyears_ftr",
    "allyears_porpag",
    "allyears_adjoe",
    "allyears_ast_tov",
    "allyears_rimmade",
    "allyears_rimmade_rimmiss",
    "allyears_midmade",
    "allyears_midmade_midmiss",
    "allyears_rimmade_rimmade_rimmiss",
    "allyears_midmade_midmade_midmiss",
    "allyears_dunksmade",
    "allyears_dunksmiss_dunksmade",
    "allyears_dunksmade_dunksmade_dunksmiss",
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
    HEIGHT_IN_COL,
]

CAT_FEATURES = [
    "allyears_role",
]

ALL_MODEL_COLS = NUMERIC_FEATURE_COLS + CAT_FEATURES


# def split_training_data(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
#     train_df = df[df[YEAR_COL] <= 2021].copy()
#     valid_df = df[df[YEAR_COL].between(2022, 2023)].copy()
#     test_df = df[df[YEAR_COL].between(2024, 2025)].copy()
#     return train_df, valid_df, test_df

def split_training_data(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.sort_values(YEAR_COL, ascending=True).copy()

    year_counts = (
        df[YEAR_COL]
        .value_counts()
        .sort_index()
        .rename_axis(YEAR_COL)
        .reset_index(name="row_count")
    )

    total_rows = len(df)
    year_counts["cum_rows"] = year_counts["row_count"].cumsum()
    year_counts["cum_pct"] = year_counts["cum_rows"] / total_rows

    print(year_counts, flush=True)

    train_cutoff_year = year_counts.loc[
        year_counts["cum_pct"] <= 0.70, YEAR_COL
    ].max()

    valid_cutoff_year = year_counts.loc[
        year_counts["cum_pct"] <= 0.85, YEAR_COL
    ].max()

    train_df = df[df[YEAR_COL] <= train_cutoff_year].copy()
    valid_df = df[
        (df[YEAR_COL] > train_cutoff_year)
        & (df[YEAR_COL] <= valid_cutoff_year)
    ].copy()
    test_df = df[df[YEAR_COL] > valid_cutoff_year].copy()

    return train_df, valid_df, test_df


def height_to_inches(value) -> float:
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.integer, np.floating)):
        value_float = float(value)
        return value_float if value_float > 20 else np.nan

    text = str(value).strip().lower()
    if not text:
        return np.nan

    text = (
        text.replace("feet", "ft")
        .replace("foot", "ft")
        .replace("inches", "in")
        .replace("inch", "in")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("′", "'")
        .replace("″", '"')
    )

    match = re.search(r"^(\d{1,2})\s*-\s*(\d{1,2})$", text)
    if match:
        feet, inches = map(int, match.groups())
        return float(feet * 12 + inches)

    match = re.search(r"(\d{1,2})\s*(?:'|ft)\s*(\d{1,2})?", text)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2) or 0)
        return float(feet * 12 + inches)

    try:
        numeric = float(text)
        return numeric if numeric > 20 else np.nan
    except ValueError:
        return np.nan


def load_training_df() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(TRAINING_QUERY).fetchdf()
    finally:
        con.close()


def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = {
        TARGET_COL,
        YEAR_COL,
        RAW_HEIGHT_COL,
        *[col for col in NUMERIC_FEATURE_COLS if col != HEIGHT_IN_COL],
        *CAT_FEATURES,
    }

    missing = sorted(required_cols - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns from TRAINING_QUERY: {missing}")

    df = df.copy()

    df[HEIGHT_IN_COL] = df[RAW_HEIGHT_COL].apply(height_to_inches)

    df = df[df[TARGET_COL].notna()].copy()

    df[YEAR_COL] = pd.to_numeric(df[YEAR_COL], errors="coerce")
    df = df[df[YEAR_COL].notna()].copy()
    df[YEAR_COL] = df[YEAR_COL].astype(int)

    for col in NUMERIC_FEATURE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in CAT_FEATURES:
        df[col] = df[col].fillna("__MISSING__").astype(str)

    df[TARGET_COL] = df[TARGET_COL].astype(str)

    return df


def make_catboost_params(trial: optuna.Trial) -> dict:
    return {
        "loss_function": "MultiClass",
        "eval_metric": "MultiClass",
        "auto_class_weights": "Balanced",
        "iterations": trial.suggest_int("iterations", 700, 3000),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.12, log=True),
        "depth": trial.suggest_int("depth", 4, 8),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 30.0, log=True),
        "random_strength": trial.suggest_float("random_strength", 0.0, 10.0),
        "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 2.0),
        "rsm": trial.suggest_float("rsm", 0.65, 1.0),
        "border_count": trial.suggest_categorical("border_count", [64, 128, 254]),
        "leaf_estimation_iterations": trial.suggest_int("leaf_estimation_iterations", 1, 10),
        "random_seed": RANDOM_SEED,
        "verbose": False,
        "allow_writing_files": False,
    }


def final_params_from_best(best_params: dict) -> dict:
    final_params = dict(best_params)
    final_params.update(
        {
            "loss_function": "MultiClass",
            "eval_metric": "MultiClass",
            "auto_class_weights": "Balanced",
            "random_seed": RANDOM_SEED,
            "verbose": False,
            "allow_writing_files": False,
        }
    )
    return final_params


def top_k_accuracy(y_true: pd.Series, probs: np.ndarray, classes: list, k: int) -> float:
    class_to_idx = {label: idx for idx, label in enumerate(classes)}
    y_idx = np.array([class_to_idx[label] for label in y_true])
    top = np.argsort(probs, axis=1)[:, ::-1][:, :k]
    return float(np.mean([y_idx[i] in top[i] for i in range(len(y_idx))]))


def evaluate_split(
    model: CatBoostClassifier,
    X: pd.DataFrame,
    y: pd.Series,
    split: str,
) -> dict:
    if len(X) == 0:
        return {
            "split": split,
            "rows": 0,
            "log_loss": None,
            "top1_accuracy": None,
            "top2_accuracy": None,
            "top3_accuracy": None,
            "macro_f1": None,
            "weighted_f1": None,
            "balanced_accuracy": None,
        }

    probs = model.predict_proba(X)
    preds = model.classes_[np.argmax(probs, axis=1)]

    return {
        "split": split,
        "rows": int(len(X)),
        "log_loss": float(log_loss(y, probs, labels=model.classes_)),
        "top1_accuracy": float(accuracy_score(y, preds)),
        "top2_accuracy": top_k_accuracy(
            y,
            probs,
            list(model.classes_),
            min(2, len(model.classes_)),
        ),
        "top3_accuracy": top_k_accuracy(
            y,
            probs,
            list(model.classes_),
            min(3, len(model.classes_)),
        ),
        "macro_f1": float(f1_score(y, preds, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y, preds, average="weighted", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y, preds)),
    }


def write_class_distribution_outputs(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    test_df: pd.DataFrame,
    artifact_dir: Path,
) -> None:
    rows = []

    for split, split_df in [
        ("train", train_df),
        ("valid", valid_df),
        ("test", test_df),
    ]:
        counts = split_df[TARGET_COL].value_counts(dropna=False)
        total = len(split_df)

        for class_name, count in counts.items():
            rows.append(
                {
                    "split": split,
                    "class": class_name,
                    "row_count": int(count),
                    "pct": None if total == 0 else float(count / total),
                }
            )

    pd.DataFrame(rows).to_csv(
        artifact_dir / "class_distribution_by_split.csv",
        index=False,
    )


def write_prediction_outputs(
    model: CatBoostClassifier,
    X: pd.DataFrame,
    y: pd.Series,
    source_df: pd.DataFrame,
    split: str,
    artifact_dir: Path,
) -> None:
    if len(X) == 0:
        return

    probs = model.predict_proba(X)
    preds = model.classes_[np.argmax(probs, axis=1)]
    labels = list(model.classes_)

    out = source_df[[YEAR_COL, "allyears_role"]].reset_index(drop=True).copy()
    out["true_class"] = y.reset_index(drop=True)
    out["pred_class"] = preds
    out["pred_correct"] = out["true_class"] == out["pred_class"]

    top_k = min(3, len(labels))
    top_idx = np.argsort(probs, axis=1)[:, ::-1][:, :top_k]

    for rank in range(top_k):
        out[f"top{rank + 1}_class"] = [labels[idx] for idx in top_idx[:, rank]]
        out[f"top{rank + 1}_prob"] = probs[np.arange(len(probs)), top_idx[:, rank]]

    for idx, label in enumerate(labels):
        safe_label = str(label).replace("/", "_").replace(" ", "_")
        out[f"prob_{safe_label}"] = probs[:, idx]

    out.to_csv(
        artifact_dir / f"{split}_predictions_with_probabilities.csv",
        index=False,
    )

    pred_dist = (
        pd.Series(preds)
        .value_counts()
        .rename_axis("pred_class")
        .reset_index(name="row_count")
    )
    pred_dist["pct"] = pred_dist["row_count"] / len(preds)
    pred_dist.to_csv(
        artifact_dir / f"{split}_predicted_class_distribution.csv",
        index=False,
    )


def write_confusion_outputs(
    model: CatBoostClassifier,
    X: pd.DataFrame,
    y: pd.Series,
    split: str,
    artifact_dir: Path,
) -> None:
    if len(X) == 0:
        return

    probs = model.predict_proba(X)
    preds = model.classes_[np.argmax(probs, axis=1)]
    labels = list(model.classes_)

    cm = confusion_matrix(y, preds, labels=labels)
    pd.DataFrame(cm, index=labels, columns=labels).to_csv(
        artifact_dir / f"{split}_confusion_matrix.csv"
    )

    report = classification_report(
        y,
        preds,
        labels=labels,
        output_dict=True,
        zero_division=0,
    )
    pd.DataFrame(report).transpose().to_csv(
        artifact_dir / f"{split}_classification_report.csv"
    )


def evals_to_rows(
    trial_number: int,
    evals_result: dict,
    params: dict,
) -> list[dict]:
    rows = []

    for dataset_name, metric_dict in evals_result.items():
        for metric_name, values in metric_dict.items():
            for iteration, value in enumerate(values):
                row = {
                    "trial_number": trial_number,
                    "dataset": dataset_name,
                    "metric": metric_name,
                    "iteration": iteration,
                    "value": float(value),
                }
                row.update({f"param_{key}": value for key, value in params.items()})
                rows.append(row)

    return rows


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    df = prepare_df(load_training_df())
    print("Rows with label:", len(df), flush=True)

    train_df, valid_df, test_df = split_training_data(df)

    train_classes = set(train_df[TARGET_COL].dropna().unique())
    valid_df = valid_df[valid_df[TARGET_COL].isin(train_classes)].copy()
    test_df = test_df[test_df[TARGET_COL].isin(train_classes)].copy()

    print("Train rows:", len(train_df), flush=True)
    print("Valid rows:", len(valid_df), flush=True)
    print("Test rows:", len(test_df), flush=True)

    if train_df.empty or valid_df.empty:
        raise ValueError(
            "Train and valid splits must both be non-empty. "
            "Check YEAR_COL and split_training_data()."
        )

    write_class_distribution_outputs(train_df, valid_df, test_df, ARTIFACT_DIR)

    X_train = train_df[ALL_MODEL_COLS]
    y_train = train_df[TARGET_COL]

    X_valid = valid_df[ALL_MODEL_COLS]
    y_valid = valid_df[TARGET_COL]

    X_test = test_df[ALL_MODEL_COLS]
    y_test = test_df[TARGET_COL]

    train_pool = Pool(X_train, y_train, cat_features=CAT_FEATURES)
    valid_pool = Pool(X_valid, y_valid, cat_features=CAT_FEATURES)
    test_pool = None if test_df.empty else Pool(X_test, y_test, cat_features=CAT_FEATURES)

    iteration_rows = []

    def objective(trial: optuna.Trial) -> float:
        params = make_catboost_params(trial)

        model = CatBoostClassifier(**params)
        model.fit(
            train_pool,
            eval_set=valid_pool,
            early_stopping_rounds=150,
            verbose=False,
            use_best_model=True,
        )

        iteration_rows.extend(
            evals_to_rows(
                trial_number=trial.number,
                evals_result=model.get_evals_result(),
                params=params,
            )
        )

        valid_probs = model.predict_proba(X_valid)
        loss = log_loss(y_valid, valid_probs, labels=model.classes_)

        trial.set_user_attr("best_iteration", int(model.get_best_iteration() or 0))
        trial.set_user_attr("class_order", [str(class_name) for class_name in model.classes_])

        return float(loss)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=N_TRIALS)

    print("Best score:", study.best_value, flush=True)
    print("Best params:", flush=True)
    print(study.best_params, flush=True)

    trials_df = study.trials_dataframe(
        attrs=("number", "value", "params", "state", "user_attrs")
    )
    trials_df.to_csv(ARTIFACT_DIR / "optuna_trials.csv", index=False)

    pd.DataFrame(iteration_rows).to_csv(
        ARTIFACT_DIR / "optuna_iteration_metrics.csv",
        index=False,
    )

    final_params = final_params_from_best(study.best_params)

    monitor_model = CatBoostClassifier(**final_params)
    eval_sets = [valid_pool] if test_pool is None else [valid_pool, test_pool]

    monitor_model.fit(
        train_pool,
        eval_set=eval_sets,
        verbose=False,
        use_best_model=False,
    )

    pd.DataFrame(
        evals_to_rows(
            trial_number=-1,
            evals_result=monitor_model.get_evals_result(),
            params=final_params,
        )
    ).to_csv(
        ARTIFACT_DIR / "final_iteration_metrics.csv",
        index=False,
    )

    train_valid_df = pd.concat([train_df, valid_df], ignore_index=True)

    train_valid_pool = Pool(
        train_valid_df[ALL_MODEL_COLS],
        train_valid_df[TARGET_COL],
        cat_features=CAT_FEATURES,
    )

    final_model = CatBoostClassifier(**final_params)
    final_model.fit(train_valid_pool, verbose=False)

    split_metrics = [
        evaluate_split(final_model, X_train, y_train, "train"),
        evaluate_split(final_model, X_valid, y_valid, "valid"),
        evaluate_split(final_model, X_test, y_test, "test"),
    ]

    pd.DataFrame(split_metrics).to_csv(
        ARTIFACT_DIR / "metrics_by_split.csv",
        index=False,
    )

    for split, X, y, split_df in [
        ("train", X_train, y_train, train_df),
        ("valid", X_valid, y_valid, valid_df),
        ("test", X_test, y_test, test_df),
    ]:
        write_confusion_outputs(final_model, X, y, split, ARTIFACT_DIR)
        write_prediction_outputs(final_model, X, y, split_df, split, ARTIFACT_DIR)

    feature_importance = final_model.get_feature_importance(train_valid_pool)

    pd.DataFrame(
        {
            "feature": ALL_MODEL_COLS,
            "importance": feature_importance,
        }
    ).sort_values(
        "importance",
        ascending=False,
    ).to_csv(
        ARTIFACT_DIR / "feature_importance.csv",
        index=False,
    )

    test_metric = next(metric for metric in split_metrics if metric["split"] == "test")
    print("Test score:", test_metric["log_loss"], flush=True)

    model_path = ARTIFACT_DIR / "catboost_transfer_role_model.cbm"
    metadata_path = ARTIFACT_DIR / "catboost_transfer_role_metadata.json"

    final_model.save_model(model_path)

    metadata = {
        "target_col": TARGET_COL,
        "year_col": YEAR_COL,
        "numeric_feature_cols": NUMERIC_FEATURE_COLS,
        "cat_features": CAT_FEATURES,
        "all_model_cols": ALL_MODEL_COLS,
        "raw_height_col": RAW_HEIGHT_COL,
        "height_in_col": HEIGHT_IN_COL,
        "class_order": [str(class_name) for class_name in final_model.classes_],
        "auto_class_weights": "Balanced",
        "best_valid_log_loss": float(study.best_value),
        "test_log_loss": test_metric["log_loss"],
        "best_params": study.best_params,
        "final_params": final_params,
        "train_year_range": [
            int(train_df[YEAR_COL].min()),
            int(train_df[YEAR_COL].max()),
        ],
        "valid_year_range": [
            int(valid_df[YEAR_COL].min()),
            int(valid_df[YEAR_COL].max()),
        ],
        "test_year_range": None
        if test_df.empty
        else [
            int(test_df[YEAR_COL].min()),
            int(test_df[YEAR_COL].max()),
        ],
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "test_rows": int(len(test_df)),
        "metrics_by_split": split_metrics,
        "artifact_files": {
            "optuna_trials": "optuna_trials.csv",
            "optuna_iteration_metrics": "optuna_iteration_metrics.csv",
            "final_iteration_metrics": "final_iteration_metrics.csv",
            "metrics_by_split": "metrics_by_split.csv",
            "class_distribution_by_split": "class_distribution_by_split.csv",
            "feature_importance": "feature_importance.csv",
            "prediction_probability_files": [
                "train_predictions_with_probabilities.csv",
                "valid_predictions_with_probabilities.csv",
                "test_predictions_with_probabilities.csv",
            ],
            "predicted_class_distributions": [
                "train_predicted_class_distribution.csv",
                "valid_predicted_class_distribution.csv",
                "test_predicted_class_distribution.csv",
            ],
            "confusion_matrices": [
                "train_confusion_matrix.csv",
                "valid_confusion_matrix.csv",
                "test_confusion_matrix.csv",
            ],
        },
    }

    metadata_path.write_text(json.dumps(metadata, indent=2))
    (ARTIFACT_DIR / "metrics_summary.json").write_text(json.dumps(metadata, indent=2))

    print("Saved model:", model_path, flush=True)
    print("Saved metadata:", metadata_path, flush=True)


if __name__ == "__main__":
    main()