from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend_site"
PLAYTYPE_PREDICTIONS = ROOT / "models_dir/baseline_model_hs_playtype/jun_5_autoclass/outputs/baseline/catboost_baseline_top3_predictions.csv"
BPR_PREDICTIONS = ROOT / "models_dir/hs_bpr/catboost_model/catboost_dual_bpr_inference_outputs/dual_bpr_inference_THISONE/dual_bpr_predictions.csv"
HS_SKILL_PERCENTILES = ROOT / "data_dir/player_percentile/hs_freshman_prior_percentile_outputs/hs_2026_projected_skill_percentiles.csv"
HS_COMPLETE_DB = ROOT / "data_dir/hs_complete.db"
PROFILE_CACHE_DIRS = [
    ROOT / "scrapers_web/cache/hs/2026/profiles",
    ROOT / "scrapers_web/cache/hs_recruiting_profiles/2026",
]
OUTPUT = FRONTEND / "data/hsRecruits.ts"

ROLE_COLUMNS = [
    "prob_C",
    "prob_Combo G",
    "prob_PF/C",
    "prob_Pure PG",
    "prob_Scoring PG",
    "prob_Stretch 4",
    "prob_Wing F",
    "prob_Wing G",
]

SKILL_PERCENTILE_COLUMNS = [
    "spacing_percentile",
    "facilitating_percentile",
    "rim_protection_percentile",
    "defense_percentile",
    "finishing_percentile",
]

EXCLUDED_HS_PLAYER_KEYS = {46128489}


def clean_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def height_from_inches(value) -> str:
    value = clean_value(value)
    if value is None:
        return "N/A"
    inches = int(round(float(value)))
    return f"{inches // 12}-{inches % 12}"


def optional_number(value):
    value = clean_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def json_literal(value) -> str:
    return json.dumps(value, ensure_ascii=False)


NULLISH_SCHOOLS = {"", "nan", "none", "null", "uncommitted", "n/a", "na", "--", "-"}

SCHOOL_ALIASES = {
    "uconn": "connecticut",
    "unc": "north carolina",
    "nc state": "north carolina state",
    "ole miss": "mississippi",
    "miami fl": "miami florida",
    "miami oh": "miami ohio",
    "st johns": "st johns",
    "saint johns": "st johns",
    "st josephs": "st josephs",
    "saint josephs": "st josephs",
    "st marys": "st marys",
    "saint marys": "st marys",
}


def normalize_school(value) -> str:
    value = clean_value(value)
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    if text in NULLISH_SCHOOLS:
        return ""
    text = text.replace("&", " and ")
    text = re.sub(r"\bst\.\b", "st", text)
    text = re.sub(r"\bsaint\b", "st", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(university|college|the)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return SCHOOL_ALIASES.get(text, text)


def has_destination_conflict(row) -> bool:
    destinations = [
        normalize_school(row.get("committed_school")),
        normalize_school(row.get("signed_school_db")),
        normalize_school(row.get("enrolled_institution_247_db")),
    ]
    return len({destination for destination in destinations if destination}) > 1


def destination_school(row) -> str:
    # Display column remains "Committed School", but data priority is final-status first.
    return (
        clean_value(row.get("enrolled_institution_247_db"))
        or clean_value(row.get("signed_school_db"))
        or clean_value(row.get("committed_school"))
        or "Uncommitted"
    )


def find_profile_html(player_key: int) -> Path | None:
    for directory in PROFILE_CACHE_DIRS:
        candidate = directory / f"{player_key}.html"
        if candidate.exists():
            return candidate
    return None


def extract_profile_image(player_key: int) -> str | None:
    profile = find_profile_html(player_key)
    if not profile:
        return None
    text = profile.read_text(errors="replace")
    match = re.search(
        r'<div class="img-container".*?<img[^>]+(?:data-src|src)="([^"]+)"',
        text,
        flags=re.DOTALL,
    )
    if not match:
        return None
    url = html.unescape(match.group(1))
    if "1x1.gif" in url:
        noscript = re.search(
            r'<div class="img-container".*?<noscript><img[^>]+src="([^"]+)"',
            text,
            flags=re.DOTALL,
        )
        if noscript:
            url = html.unescape(noscript.group(1))
    if "Uploads/Player/0/1." in url:
        return None
    return url if url.startswith("http") and "1x1.gif" not in url else None


def build_player(row) -> dict:
    school = destination_school(row)
    role_probabilities = {
        column.replace("prob_", ""): round(float(row[column]), 6)
        for column in ROLE_COLUMNS
        if clean_value(row.get(column)) is not None
    }
    top_role = clean_value(row.get("pred_role_1")) or max(role_probabilities, key=role_probabilities.get)
    hs_bpr = optional_number(row.get("predicted_college_basic_bpr"))
    rating = optional_number(row.get("rating")) or optional_number(row.get("hs_rating"))
    stars = optional_number(row.get("stars")) or optional_number(row.get("hs_stars"))
    national_rank = optional_number(row.get("national_rank")) or optional_number(row.get("hs_national_rank"))
    fit_score = max(50, min(99, int(round((rating or 86) - 4))))
    weight = optional_number(row.get("hs_weight"))

    return {
        "player_id": f"hs-{int(row['player_key'])}",
        "player_name": clean_value(row.get("full_name")) or f"Recruit {int(row['player_key'])}",
        "player_source": "hs",
        "profile_image_url": extract_profile_image(int(row["player_key"])),
        "position": clean_value(row.get("position")) or clean_value(row.get("hs_position")) or "N/A",
        "height": clean_value(row.get("height")) or height_from_inches(row.get("hs_height_in")),
        "weight": int(weight) if weight is not None else 0,
        "class_year": "Fr",
        "current_team": school,
        "conference": "Recruit",
        "portal_status": "not_in_portal",
        "is_in_portal": False,
        "projected_bpr": round((rating or 88) / 20, 1),
        "projected_minutes": max(8, min(30, int(round(((rating or 88) - 70) * 0.9)))),
        "projected_points": round(max(3, (rating or 88) / 9), 1),
        "projected_rebounds": round(6.0 if top_role in {"C", "PF/C", "Stretch 4"} else 3.2, 1),
        "projected_assists": round(4.2 if top_role in {"Pure PG", "Scoring PG", "Combo G"} else 1.5, 1),
        "hs_bpr": hs_bpr,
        "skill_spacing_percentile": optional_number(row.get("spacing_percentile")),
        "skill_facilitating_percentile": optional_number(row.get("facilitating_percentile")),
        "skill_rim_protection_percentile": optional_number(row.get("rim_protection_percentile")),
        "skill_defense_percentile": optional_number(row.get("defense_percentile")),
        "skill_finishing_percentile": optional_number(row.get("finishing_percentile")),
        "playtype_probabilities": role_probabilities,
        "fit_score": fit_score,
        "recommendation_rank": int(national_rank) if national_rank is not None else 999,
        "fit_explanation": f"2026 high school recruit projected most likely as {top_role}.",
        "scouting_summary": "Model-driven role projection from high school recruiting profile data.",
        "hs_rating": rating,
        "hs_stars": stars,
        "hs_national_rank": national_rank,
        "hs_position_rank": optional_number(row.get("position_rank")) or optional_number(row.get("hs_position_rank")),
        "hs_player_key": int(row["player_key"]),
        "top3_roles": [
            {"label": clean_value(row.get(f"pred_role_{idx}")), "probability": optional_number(row.get(f"pred_prob_{idx}"))}
            for idx in (1, 2, 3)
            if clean_value(row.get(f"pred_role_{idx}")) is not None
        ],
    }


def main() -> None:
    df = pd.read_csv(PLAYTYPE_PREDICTIONS)
    bpr_df = pd.read_csv(BPR_PREDICTIONS)[["player_key", "predicted_college_basic_bpr"]]
    skill_df = pd.read_csv(HS_SKILL_PERCENTILES)[["player_key", *SKILL_PERCENTILE_COLUMNS]]
    if skill_df["player_key"].duplicated().any():
        raise RuntimeError("HS skill percentile rows are not unique by player_key.")
    con = duckdb.connect(str(HS_COMPLETE_DB), read_only=True)
    try:
        hs_complete = con.execute(
            """
            select
              year,
              player_key,
              committed_school,
              signed_school as signed_school_db,
              current_school,
              enrolled_institution_247 as enrolled_institution_247_db,
              position,
              height,
              stars,
              rating,
              national_rank,
              position_rank
            from hs_complete
            where year = 2026
            """
        ).fetchdf()
    finally:
        con.close()
    df = df.merge(bpr_df, on="player_key", how="left")
    before_skill_merge = len(df)
    df = df.merge(skill_df, on="player_key", how="left")
    if len(df) != before_skill_merge:
        raise RuntimeError(f"HS skill percentile merge changed row count: before={before_skill_merge}, after={len(df)}")
    df = df.merge(hs_complete, left_on=["hs_year", "player_key"], right_on=["year", "player_key"], how="left")
    conflict_count = int(df.apply(has_destination_conflict, axis=1).sum())
    df = df[~df["player_key"].isin(EXCLUDED_HS_PLAYER_KEYS)].copy()
    players = [build_player(row) for _, row in df.iterrows()]
    with_images = sum(1 for player in players if player["profile_image_url"])
    with_skill_percentiles = sum(
        1
        for player in players
        if any(
            player.get(key) is not None
            for key in (
                "skill_spacing_percentile",
                "skill_facilitating_percentile",
                "skill_rim_protection_percentile",
                "skill_defense_percentile",
                "skill_finishing_percentile",
            )
        )
    )

    lines = [
        'import type { Player } from "./players";',
        "",
        "// Generated by frontend_site/scripts/build_hs_recruits.py.",
        "// Sources:",
        "// - models_dir/baseline_model_hs_playtype/jun_5_autoclass/outputs/baseline/catboost_baseline_top3_predictions.csv",
        "// - models_dir/hs_bpr/catboost_model/catboost_dual_bpr_inference_outputs/dual_bpr_inference_THISONE/dual_bpr_predictions.csv",
        "// - data_dir/player_percentile/hs_freshman_prior_percentile_outputs/hs_2026_projected_skill_percentiles.csv",
        f"export const hsRecruitPlayers: Player[] = {json_literal(players)};",
        "",
        f"export const hsRecruitImageCoverage = {{ total: {len(players)}, withImages: {with_images} }};",
        "",
    ]
    OUTPUT.write_text("\n".join(lines))
    print(f"wrote {OUTPUT}")
    print(
        f"players={len(players)} with_images={with_images} "
        f"with_skill_percentiles={with_skill_percentiles} excluded_destination_conflicts={conflict_count}"
    )


if __name__ == "__main__":
    main()
