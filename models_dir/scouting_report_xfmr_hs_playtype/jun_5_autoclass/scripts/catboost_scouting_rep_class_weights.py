"""
CatBoost playtype model with structured HS recruit features plus scouting report
embeddings and scouting evaluator availability flags.
"""

import json
import os
from pathlib import Path

os.environ["USE_TF"] = "0"
os.environ["TRANSFORMERS_NO_TF"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

import duckdb
import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sentence_transformers import SentenceTransformer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
MODEL_DIR = Path(__file__).resolve().parents[1]

DB_PATH = PROJECT_ROOT / "data_dir" / "hs_bv_matched.db"
ARTIFACT_DIR = MODEL_DIR / "artifacts"
TARGET_COL = "bv_role"

BASE_FEATURE_COLS = [
    # hs_year intentionally excluded from model features; still used below for train/valid/test splits.
    "hs_position",
    "hs_height_in",
    "hs_weight",
    "hs_stars",
    "hs_rating",
    "hs_national_rank",
    "hs_position_rank",
]
SCOUTING_REPORT_COL = "scouting_report"
EVALUATOR_COL = "scouting_report_evaluator_name"
SCOUTING_FLAG_COL = "has_scouting_report_text"
EVALUATOR_FLAG_COL = "has_scouting_report_evaluator"
CAT_FEATURES = [
    "hs_position",
    # EVALUATOR_COL,
]

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_PATH = (
    Path.home()
    / ".cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2"
    / "snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
)
EMBEDDING_DIM = 384
N_TRIALS = 50
CLASS_WEIGHT_OPTIONS = ["None", "SqrtBalanced", "Balanced"]


def load_training_df() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(
            f"""
            SELECT
                hs_year,
                hs_player_key AS player_key,
                hs_full_name AS full_name,
                hs_position,
                hs_height_in,
                hs_weight,
                hs_stars,
                hs_rating,
                hs_national_rank,
                hs_position_rank,
                hs_scouting_report AS scouting_report,
                hs_scouting_report_evaluator_name AS scouting_report_evaluator_name,
                {TARGET_COL}
            FROM hs_bv_matched
            WHERE {TARGET_COL} IS NOT NULL
            """
        ).fetchdf()
    finally:
        con.close()


def make_catboost_params(trial: optuna.Trial) -> tuple[dict, str]:
    auto_class_weights = trial.suggest_categorical(
        "auto_class_weights",
        CLASS_WEIGHT_OPTIONS,
    )

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

    if auto_class_weights != "None":
        params["auto_class_weights"] = auto_class_weights

    return params, auto_class_weights


def final_params_from_best(best_params: dict) -> dict:
    final_params = dict(best_params)
    auto_class_weights = final_params.pop("auto_class_weights", "None")

    final_params.update(
        {
            "loss_function": "MultiClass",
            "eval_metric": "MultiClass",
            "random_seed": 42,
            "verbose": False,
            "allow_writing_files": False,
        }
    )

    if auto_class_weights != "None":
        final_params["auto_class_weights"] = auto_class_weights

    return final_params


def add_text_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[SCOUTING_FLAG_COL] = (
        df[SCOUTING_REPORT_COL].notna()
        & df[SCOUTING_REPORT_COL].astype(str).str.strip().ne("")
    )
    df[EVALUATOR_FLAG_COL] = (
        df[EVALUATOR_COL].notna()
        & df[EVALUATOR_COL].astype(str).str.strip().ne("")
    )
    df[EVALUATOR_COL] = df[EVALUATOR_COL].where(df[EVALUATOR_FLAG_COL], "__missing__")
    df["hs_position"] = df["hs_position"].fillna("__missing__")
    df["_embedding_cache_key"] = df["player_key"].astype(str) + "_" + df["hs_year"].astype(str)
    return df


def add_embeddings(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], Path]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe_model_name = EMBEDDING_MODEL_NAME.replace("/", "__")
    embedding_cache_path = ARTIFACT_DIR / f"scouting_embeddings_{safe_model_name}.parquet"
    embedding_cols = [f"scout_emb_{i}" for i in range(EMBEDDING_DIM)]

    if embedding_cache_path.exists():
        print("Loading cached embeddings:", embedding_cache_path, flush=True)
        emb_df = pd.read_parquet(embedding_cache_path)
        merged = df.merge(emb_df, on="_embedding_cache_key", how="left", validate="one_to_one")
        if not merged[embedding_cols].isna().any(axis=1).any():
            return merged, embedding_cols, embedding_cache_path
        print("Cache missing rows. Recomputing full embedding cache.", flush=True)

    print("Generating scouting report embeddings on CPU...", flush=True)
    model = SentenceTransformer(str(EMBEDDING_MODEL_PATH), device="cpu", local_files_only=True)
    embedding_matrix = np.zeros((len(df), EMBEDDING_DIM), dtype=np.float32)
    mask = df[SCOUTING_FLAG_COL].to_numpy()
    texts = df.loc[mask, SCOUTING_REPORT_COL].astype(str).tolist()
    if texts:
        encoded = model.encode(
            texts,
            batch_size=32,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        embedding_matrix[mask] = encoded.astype(np.float32)

    emb_df = pd.DataFrame(embedding_matrix, columns=embedding_cols)
    emb_df["_embedding_cache_key"] = df["_embedding_cache_key"].values
    temp_embedding_cache_path = embedding_cache_path.with_suffix(".tmp.parquet")
    emb_df.to_parquet(temp_embedding_cache_path, index=False)
    temp_embedding_cache_path.replace(embedding_cache_path)
    print("Saved embedding cache:", embedding_cache_path, flush=True)

    df = pd.concat([df.reset_index(drop=True), emb_df[embedding_cols].reset_index(drop=True)], axis=1)
    return df, embedding_cols, embedding_cache_path


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
        "top3_accuracy": top_k_accuracy(y, probs, list(model.classes_), min(3, len(model.classes_))),
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
    frames = [("train", train_df), ("valid", valid_df), ("test", test_df)]
    rows = []
    for split, split_df in frames:
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
    pd.DataFrame(rows).to_csv(artifact_dir / "class_distribution_by_split.csv", index=False)


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

    id_cols = [
        col
        for col in [
            "hs_year",
            "player_key",
            "full_name",
            "hs_position",
            SCOUTING_FLAG_COL,
            EVALUATOR_FLAG_COL,
        ]
        if col in source_df.columns
    ]
    out = source_df[id_cols].reset_index(drop=True).copy()
    out["true_class"] = y.reset_index(drop=True)
    out["pred_class"] = preds
    out["pred_correct"] = out["true_class"] == out["pred_class"]

    top_k = min(3, len(labels))
    top_idx = np.argsort(probs, axis=1)[:, ::-1][:, :top_k]
    for rank in range(top_k):
        out[f"top{rank + 1}_class"] = [labels[idx] for idx in top_idx[:, rank]]
        out[f"top{rank + 1}_prob"] = probs[np.arange(len(probs)), top_idx[:, rank]]

    for idx, label in enumerate(labels):
        out[f"prob_{label}"] = probs[:, idx]

    out.to_csv(artifact_dir / f"{split}_predictions_with_probabilities.csv", index=False)

    pred_dist = pd.Series(preds).value_counts().rename_axis("pred_class").reset_index(name="row_count")
    pred_dist["pct"] = pred_dist["row_count"] / len(preds)
    pred_dist.to_csv(artifact_dir / f"{split}_predicted_class_distribution.csv", index=False)


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
    df = add_text_features(load_training_df())
    print("Rows with label:", len(df), flush=True)
    df, embedding_cols, embedding_cache_path = add_embeddings(df)

    feature_cols = (
        BASE_FEATURE_COLS
        + [
            SCOUTING_FLAG_COL,
            # EVALUATOR_FLAG_COL,
            # EVALUATOR_COL,
        ]
        + embedding_cols
    )

    train_df = df[(df["hs_year"] >= 2009) & (df["hs_year"] < 2022)].copy()
    valid_df = df[(df["hs_year"] >= 2022) & (df["hs_year"] <= 2023)].copy()
    test_df = df[(df["hs_year"] >= 2024) & (df["hs_year"] <= 2025)].copy()

    train_classes = set(train_df[TARGET_COL].dropna().unique())
    valid_df = valid_df[valid_df[TARGET_COL].isin(train_classes)].copy()
    test_df = test_df[test_df[TARGET_COL].isin(train_classes)].copy()

    write_class_distribution_outputs(train_df, valid_df, test_df, ARTIFACT_DIR)

    X_train = train_df[feature_cols]
    y_train = train_df[TARGET_COL]
    X_valid = valid_df[feature_cols]
    y_valid = valid_df[TARGET_COL]
    X_test = test_df[feature_cols]
    y_test = test_df[TARGET_COL]

    train_pool = Pool(X_train, y_train, cat_features=CAT_FEATURES)
    valid_pool = Pool(X_valid, y_valid, cat_features=CAT_FEATURES)
    test_pool = None if test_df.empty else Pool(X_test, y_test, cat_features=CAT_FEATURES)
    iteration_rows = []

    def objective(trial):
        params, auto_class_weights = make_catboost_params(trial)
        model = CatBoostClassifier(**params)
        model.fit(
            train_pool,
            eval_set=valid_pool,
            early_stopping_rounds=100,
            verbose=False,
            use_best_model=True,
        )
        logged_params = {**params, "auto_class_weights_choice": auto_class_weights}
        iteration_rows.extend(evals_to_rows(trial.number, model.get_evals_result(), logged_params))
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

    final_params = final_params_from_best(study.best_params)

    monitor_model = CatBoostClassifier(**final_params)
    eval_sets = [valid_pool] if test_pool is None else [valid_pool, test_pool]
    monitor_model.fit(train_pool, eval_set=eval_sets, verbose=False, use_best_model=False)
    pd.DataFrame(evals_to_rows(-1, monitor_model.get_evals_result(), final_params)).to_csv(
        ARTIFACT_DIR / "final_iteration_metrics.csv",
        index=False,
    )

    train_valid_df = pd.concat([train_df, valid_df], ignore_index=True)
    train_valid_pool = Pool(
        train_valid_df[feature_cols],
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
    for split, X, y, split_df in [
        ("train", X_train, y_train, train_df),
        ("valid", X_valid, y_valid, valid_df),
        ("test", X_test, y_test, test_df),
    ]:
        write_confusion_outputs(final_model, X, y, split, ARTIFACT_DIR)
        write_prediction_outputs(final_model, X, y, split_df, split, ARTIFACT_DIR)

    feature_importance = final_model.get_feature_importance(train_valid_pool)
    pd.DataFrame(
        {"feature": feature_cols, "importance": feature_importance}
    ).sort_values("importance", ascending=False).to_csv(
        ARTIFACT_DIR / "feature_importance.csv",
        index=False,
    )

    test_metric = next(m for m in split_metrics if m["split"] == "test")
    print("Test score:", test_metric["log_loss"], flush=True)

    model_path = ARTIFACT_DIR / "catboost_playtype_with_scouting_embeddings.cbm"
    metadata_path = ARTIFACT_DIR / "catboost_playtype_with_scouting_embeddings_metadata.json"
    final_model.save_model(model_path)

    metadata = {
        "target_col": TARGET_COL,
        "base_feature_cols": BASE_FEATURE_COLS,
        "embedding_cols": embedding_cols,
        "feature_cols": feature_cols,
        "cat_features": CAT_FEATURES,
        "scouting_report_col": SCOUTING_REPORT_COL,
        "scouting_flag_col": SCOUTING_FLAG_COL,
        "evaluator_col": EVALUATOR_COL,
        "evaluator_flag_col_created_but_not_used": EVALUATOR_FLAG_COL,
        "embedding_model_name": EMBEDDING_MODEL_NAME,
        "embedding_model_path": str(EMBEDDING_MODEL_PATH),
        "embedding_dim": EMBEDDING_DIM,
        "embedding_cache_path": str(embedding_cache_path),
        "class_order": [str(class_name) for class_name in final_model.classes_],
        "class_weight_options_searched": CLASS_WEIGHT_OPTIONS,
        "selected_auto_class_weights": study.best_params.get("auto_class_weights", "None"),
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
