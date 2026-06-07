import json
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = Path(__file__).resolve().parent

DB_PATH = PROJECT_ROOT / "data_dir" / "bv_trans_compl_MAX.db"
MODEL_PATH = MODEL_DIR / "artifacts" / "transfer_role_catboost" / "catboost_transfer_role_model.cbm"
METADATA_PATH = MODEL_DIR / "artifacts" / "transfer_role_catboost" / "catboost_transfer_role_metadata.json"
OUTPUT_DIR = MODEL_DIR / "outputs" / "transfer_role_catboost"
OUTPUT_PATH = OUTPUT_DIR / "catboost_transfer_role_future_top3_predictions.csv"

TARGET_COL = "future_role"
YEAR_COL = "allyears_year"
RAW_HEIGHT_COL = "allyears_player_height"
HEIGHT_IN_COL = "allyears_player_height_in"


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


def load_inference_df() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(
            f"""
            SELECT *
            FROM all_years_transfer_matched
            WHERE {YEAR_COL} = 2026
              AND (
                    {TARGET_COL} IS NULL
                    OR TRIM(COALESCE(CAST({TARGET_COL} AS VARCHAR), '')) = ''
                  )
            ORDER BY transfer_row_number, allyears_barttorvik_trid
            """
        ).fetchdf()
    finally:
        con.close()


def prepare_df(df: pd.DataFrame, metadata: dict) -> pd.DataFrame:
    df = df.copy()

    feature_cols = metadata["all_model_cols"]
    cat_features = metadata["cat_features"]

    required_cols = set(feature_cols) - {HEIGHT_IN_COL}
    required_cols.add(RAW_HEIGHT_COL)
    missing = sorted(required_cols - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns from inference source: {missing}")

    df[HEIGHT_IN_COL] = df[RAW_HEIGHT_COL].apply(height_to_inches)

    for col in feature_cols:
        if col == HEIGHT_IN_COL:
            continue
        if col in cat_features:
            df[col] = (
                df[col]
                .fillna("__MISSING__")
                .replace("", "__MISSING__")
                .astype(str)
            )
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df[TARGET_COL] = df[TARGET_COL].replace("", np.nan)

    return df


def add_top_predictions(df: pd.DataFrame, probs, class_order: list[str]) -> pd.DataFrame:
    prob_df = pd.DataFrame(
        probs,
        columns=[f"prob_{str(role).replace('/', '_').replace(' ', '_')}" for role in class_order],
        index=df.index,
    )

    ranked = np.argsort(probs, axis=1)[:, ::-1][:, :3]
    top_df = pd.DataFrame(
        {
            "pred_role_1": [class_order[i] for i in ranked[:, 0]],
            "pred_prob_1": probs[np.arange(len(probs)), ranked[:, 0]],
            "pred_role_2": [class_order[i] for i in ranked[:, 1]],
            "pred_prob_2": probs[np.arange(len(probs)), ranked[:, 1]],
            "pred_role_3": [class_order[i] for i in ranked[:, 2]],
            "pred_prob_3": probs[np.arange(len(probs)), ranked[:, 2]],
        },
        index=df.index,
    )

    return pd.concat([df.reset_index(drop=True), top_df, prob_df], axis=1)


def main() -> None:
    metadata = json.loads(METADATA_PATH.read_text())
    feature_cols = metadata["all_model_cols"]
    cat_features = metadata["cat_features"]
    class_order = metadata["class_order"]

    df = prepare_df(load_inference_df(), metadata)

    missing_features = sorted(set(feature_cols) - set(df.columns))
    if missing_features:
        raise RuntimeError(f"Inference dataframe is missing required features: {missing_features}")

    X = df[feature_cols]

    model = CatBoostClassifier()
    model.load_model(str(MODEL_PATH))

    model_class_order = [str(role) for role in model.classes_]
    if model_class_order != class_order:
        raise RuntimeError(
            f"Metadata class order {class_order} does not match model class order {model_class_order}"
        )

    pool = Pool(X, cat_features=cat_features)
    probs = model.predict_proba(pool)
    output = add_top_predictions(df, probs, class_order)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False)

    print(f"Rows scored: {len(output)}")
    print(f"Saved predictions: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
