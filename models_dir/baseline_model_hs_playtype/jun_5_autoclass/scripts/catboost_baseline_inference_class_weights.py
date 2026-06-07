import json
from pathlib import Path

import duckdb
import pandas as pd
from catboost import CatBoostClassifier


PROJECT_ROOT = Path(__file__).resolve().parents[4]
MODEL_DIR = Path(__file__).resolve().parents[1]

DB_PATH = PROJECT_ROOT / "data_dir" / "hs_complete.db"
MODEL_PATH = MODEL_DIR / "artifacts" / "catboost_baseline_playtype_model.cbm"
METADATA_PATH = MODEL_DIR / "artifacts" / "catboost_baseline_playtype_metadata.json"
OUTPUT_DIR = MODEL_DIR / "outputs" / "baseline"
OUTPUT_PATH = OUTPUT_DIR / "catboost_baseline_top3_predictions.csv"


def load_inference_df() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(
            """
            SELECT
                year AS hs_year,
                player_key,
                full_name,
                signed_school,
                enrolled_institution_247,
                COALESCE(signed_school, enrolled_institution_247) AS signed_or_enrolled,
                position AS hs_position,
                height_in AS hs_height_in,
                weight AS hs_weight,
                stars AS hs_stars,
                rating AS hs_rating,
                national_rank AS hs_national_rank,
                position_rank AS hs_position_rank
            FROM hs_complete
            WHERE full_name IS NOT NULL
                AND year = 2026
            """
        ).fetchdf()
    finally:
        con.close()


def add_top_predictions(df: pd.DataFrame, probs, class_order: list[str]) -> pd.DataFrame:
    prob_df = pd.DataFrame(
        probs,
        columns=[f"prob_{role}" for role in class_order],
        index=df.index,
    )

    ranked = probs.argsort(axis=1)[:, ::-1][:, :3]
    top_df = pd.DataFrame(
        {
            "pred_role_1": [class_order[i] for i in ranked[:, 0]],
            "pred_prob_1": probs[df.index, ranked[:, 0]],
            "pred_role_2": [class_order[i] for i in ranked[:, 1]],
            "pred_prob_2": probs[df.index, ranked[:, 1]],
            "pred_role_3": [class_order[i] for i in ranked[:, 2]],
            "pred_prob_3": probs[df.index, ranked[:, 2]],
        },
        index=df.index,
    )

    id_cols = [
        "hs_year",
        "player_key",
        "full_name",
        "signed_or_enrolled",
        "signed_school",
        "enrolled_institution_247",
        "hs_position",
        "hs_height_in",
        "hs_weight",
        "hs_stars",
        "hs_rating",
        "hs_national_rank",
        "hs_position_rank",
    ]
    return pd.concat([df[id_cols], top_df, prob_df], axis=1)


def main() -> None:
    metadata = json.loads(METADATA_PATH.read_text())
    feature_cols = metadata["feature_cols"]
    class_order = metadata["class_order"]

    df = load_inference_df()
    df["hs_position"] = df["hs_position"].fillna("__missing__")

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

    probs = model.predict_proba(X)
    output = add_top_predictions(df, probs, class_order)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False)

    print(f"Rows scored: {len(output)}")
    print(f"Saved predictions: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
