import json
from pathlib import Path

import duckdb
import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, log_loss


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = Path(__file__).resolve().parents[1]

DB_PATH = PROJECT_ROOT / "data_dir" / "hs_bv_matched.db"
ARTIFACT_DIR = MODEL_DIR / "artifacts"
TARGET_COL = "bv_role"
N_TRIALS = 50

FEATURE_COLS = [
    "hs_position",
    "hs_height_in",
    "hs_weight",
    "hs_stars",
    "hs_rating",
    "hs_national_rank",
    "hs_position_rank",
]
CAT_FEATURES = ["hs_position"]


def load_training_df() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(
            f"""
            SELECT *
            FROM hs_bv_matched
            WHERE {TARGET_COL} IS NOT NULL
            """
        ).fetchdf()
    finally:
        con.close()


def top_k_accuracy(y_true: pd.Series, probs: np.ndarray, classes: list, k: int) -> float:
    class_to_idx = {label: idx for idx, label in enumerate(classes)}
    y_idx = np.array([class_to_idx[label] for label in y_true])
    top = np.argsort(probs, axis=1)[:, ::-1][:, :k]
    return float(np.mean([y_idx[i] in top[i] for i in range(len(y_idx))]))


def evaluate_split(model: CatBoostClassifier, X: pd.DataFrame, y: pd.Series, split: str) -> dict:
    if len(X) == 0:
        return {
            "split": split,
            "rows": 0,
            "log_loss": None,
            "top1_accuracy": None,
            "top3_accuracy": None,
        }
    probs = model.predict_proba(X)
    preds = model.classes_[np.argmax(probs, axis=1)]
    return {
        "split": split,
        "rows": int(len(X)),
        "log_loss": float(log_loss(y, probs, labels=model.classes_)),
        "top1_accuracy": float(accuracy_score(y, preds)),
        "top3_accuracy": top_k_accuracy(y, probs, list(model.classes_), min(3, len(model.classes_))),
    }


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
    report = classification_report(y, preds, labels=labels, output_dict=True, zero_division=0)
    pd.DataFrame(report).transpose().to_csv(artifact_dir / f"{split}_classification_report.csv")


def evals_to_rows(trial_number: int, evals_result: dict, params: dict) -> list[dict]:
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
                row.update({f"param_{k}": v for k, v in params.items()})
                rows.append(row)
    return rows


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_training_df()
    print("Rows with label:", len(df), flush=True)

    train_df = df[(df["hs_year"] >= 2009) & (df["hs_year"] < 2022)].copy()
    valid_df = df[(df["hs_year"] >= 2022) & (df["hs_year"] <= 2023)].copy()
    test_df = df[(df["hs_year"] >= 2024) & (df["hs_year"] <= 2025)].copy()

    train_classes = set(train_df[TARGET_COL].dropna().unique())
    valid_df = valid_df[valid_df[TARGET_COL].isin(train_classes)].copy()
    test_df = test_df[test_df[TARGET_COL].isin(train_classes)].copy()

    X_train = train_df[FEATURE_COLS]
    y_train = train_df[TARGET_COL]
    X_valid = valid_df[FEATURE_COLS]
    y_valid = valid_df[TARGET_COL]
    X_test = test_df[FEATURE_COLS]
    y_test = test_df[TARGET_COL]

    train_pool = Pool(X_train, y_train, cat_features=CAT_FEATURES)
    valid_pool = Pool(X_valid, y_valid, cat_features=CAT_FEATURES)
    test_pool = None if test_df.empty else Pool(X_test, y_test, cat_features=CAT_FEATURES)
    iteration_rows = []

    def objective(trial):
        params = {
            "loss_function": "MultiClass",
            "eval_metric": "MultiClass",
            "iterations": trial.suggest_int("iterations", 500, 2500),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "depth": trial.suggest_int("depth", 4, 8),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 15.0, log=True),
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 1.0),
            "random_seed": 42,
            "verbose": False,
            "allow_writing_files": False,
        }
        model = CatBoostClassifier(**params)
        model.fit(
            train_pool,
            eval_set=valid_pool,
            early_stopping_rounds=100,
            verbose=False,
            use_best_model=True,
        )
        iteration_rows.extend(evals_to_rows(trial.number, model.get_evals_result(), params))
        valid_probs = model.predict_proba(X_valid)
        loss = log_loss(y_valid, valid_probs, labels=model.classes_)
        trial.set_user_attr("best_iteration", int(model.get_best_iteration() or 0))
        trial.set_user_attr("class_order", [str(c) for c in model.classes_])
        return loss

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=N_TRIALS)

    print("Best score:", study.best_value, flush=True)
    print("Best params:", flush=True)
    print(study.best_params, flush=True)

    trials_df = study.trials_dataframe(attrs=("number", "value", "params", "state", "user_attrs"))
    trials_df.to_csv(ARTIFACT_DIR / "optuna_trials.csv", index=False)
    pd.DataFrame(iteration_rows).to_csv(ARTIFACT_DIR / "optuna_iteration_metrics.csv", index=False)

    final_params = {
        **study.best_params,
        "loss_function": "MultiClass",
        "eval_metric": "MultiClass",
        "random_seed": 42,
        "verbose": False,
        "allow_writing_files": False,
    }

    monitor_model = CatBoostClassifier(**final_params)
    eval_sets = [valid_pool] if test_pool is None else [valid_pool, test_pool]
    monitor_model.fit(train_pool, eval_set=eval_sets, verbose=False, use_best_model=False)
    pd.DataFrame(evals_to_rows(-1, monitor_model.get_evals_result(), final_params)).to_csv(
        ARTIFACT_DIR / "final_iteration_metrics.csv",
        index=False,
    )

    train_valid_df = pd.concat([train_df, valid_df], ignore_index=True)
    train_valid_pool = Pool(
        train_valid_df[FEATURE_COLS],
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
    pd.DataFrame(split_metrics).to_csv(ARTIFACT_DIR / "metrics_by_split.csv", index=False)
    for split, X, y in [("train", X_train, y_train), ("valid", X_valid, y_valid), ("test", X_test, y_test)]:
        write_confusion_outputs(final_model, X, y, split, ARTIFACT_DIR)

    test_metric = next(m for m in split_metrics if m["split"] == "test")
    print("Test score:", test_metric["log_loss"], flush=True)

    model_path = ARTIFACT_DIR / "catboost_baseline_playtype_model.cbm"
    metadata_path = ARTIFACT_DIR / "catboost_baseline_playtype_metadata.json"
    final_model.save_model(model_path)

    metadata = {
        "target_col": TARGET_COL,
        "feature_cols": FEATURE_COLS,
        "cat_features": CAT_FEATURES,
        "class_order": [str(class_name) for class_name in final_model.classes_],
        "best_valid_log_loss": float(study.best_value),
        "test_log_loss": test_metric["log_loss"],
        "best_params": study.best_params,
        "final_params": final_params,
        "train_hs_year_range": [int(train_df["hs_year"].min()), int(train_df["hs_year"].max())],
        "valid_hs_year_range": [int(valid_df["hs_year"].min()), int(valid_df["hs_year"].max())],
        "test_hs_year_range": None
        if test_df.empty
        else [int(test_df["hs_year"].min()), int(test_df["hs_year"].max())],
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "test_rows": int(len(test_df)),
        "metrics_by_split": split_metrics,
        "artifact_files": {
            "optuna_trials": "optuna_trials.csv",
            "optuna_iteration_metrics": "optuna_iteration_metrics.csv",
            "final_iteration_metrics": "final_iteration_metrics.csv",
            "metrics_by_split": "metrics_by_split.csv",
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
