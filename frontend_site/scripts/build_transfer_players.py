from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend_site"
PREDICTIONS = ROOT / "models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions.csv"
BPR_PREDICTIONS = ROOT / "models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/dual_transfer_bpr_inference_2026_20260607_190712/dual_transfer_bpr_predictions_2026.csv"
TRANSFER_247_BV_DB = ROOT / "data_dir/247_bv_transf_matched.db"
PERCENTILES = ROOT / "data_dir/player_percentile/cluster_percentile_outputs/players_group_percentiles_from_db.csv"
PROFILE_CACHE_DIR = ROOT / "scrapers_web/cache/transfers/2026/profiles"
OUTPUT = FRONTEND / "data/transferPlayers.ts"
ALLOWED_POSITIONS = {"PG", "SG", "CG", "SF", "PF", "C", "N/A"}
EXCLUDED_TRANSFER_KEYS = {
    ("cole alexander", "fairleigh dickinson"),
    ("najimi george", "new haven"),
}
TRANSFER_TRID_OVERRIDES = {
    ("donny yeager", "oakland", 3772): 9_999_133_670,
}

ROLE_COLUMNS = [
    "prob_C",
    "prob_Combo_G",
    "prob_PF_C",
    "prob_Pure_PG",
    "prob_Scoring_PG",
    "prob_Stretch_4",
    "prob_Wing_F",
    "prob_Wing_G",
]

MONTH_HEIGHTS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


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


def optional_number(value):
    value = clean_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_height_text(value) -> str:
    value = clean_value(value)
    if value is None:
        return "N/A"
    text = str(value).strip()
    text = text.replace('="', "").replace('"', "")
    date_match = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})", text)
    if date_match:
        inches = int(date_match.group(1))
        feet = MONTH_HEIGHTS.get(date_match.group(2).lower())
        if feet in {5, 6, 7} and 0 <= inches <= 11:
            return f"{feet}-{inches}"
    return text or "N/A"


def normalize_position(value) -> str:
    value = clean_value(value)
    if value is None:
        return "N/A"
    text = str(value).strip().upper()
    return text if text in ALLOWED_POSITIONS else "N/A"


def first_position(*values) -> str:
    for value in values:
        position = normalize_position(value)
        if position != "N/A":
            return position
    return "N/A"


def first_non_null(*values):
    for value in values:
        value = clean_value(value)
        if value is not None:
            return value
    return None


def json_literal(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def find_profile_html(player_key: int) -> Path | None:
    candidate = PROFILE_CACHE_DIR / f"{player_key}.html"
    return candidate if candidate.exists() else None


def extract_profile_image(player_key: int, avatar_url: str | None = None) -> str | None:
    profile = find_profile_html(player_key)
    if profile:
        text = profile.read_text(errors="replace")
        match = re.search(
            r'<div class="img-container".*?<img[^>]+(?:data-src|src)="([^"]+)"',
            text,
            flags=re.DOTALL,
        )
        if match:
            url = html.unescape(match.group(1))
            if "1x1.gif" not in url and url.startswith("http"):
                return url
        noscript = re.search(
            r'<div class="img-container".*?<noscript><img[^>]+src="([^"]+)"',
            text,
            flags=re.DOTALL,
        )
        if noscript:
            url = html.unescape(noscript.group(1))
            if "1x1.gif" not in url and url.startswith("http"):
                return url
    avatar_url = clean_value(avatar_url)
    return avatar_url if isinstance(avatar_url, str) and avatar_url.startswith("http") else None


def names_match(*values) -> bool:
    cleaned = [
        re.sub(r"[^a-z0-9]+", "", str(value).lower())
        for value in values
        if clean_value(value) is not None
    ]
    return len(cleaned) >= 2 and len(set(cleaned)) == 1


def safe_247_metadata_match(row, player_name: str) -> bool:
    name_score = optional_number(row.get("metadata_name_score"))
    overall_score = optional_number(row.get("metadata_overall_match_score"))
    return (
        name_score is not None
        and overall_score is not None
        and name_score >= 95
        and overall_score >= 90
        and names_match(row.get("metadata_247_full_name"), player_name)
    )


def truthy(value) -> bool:
    value = clean_value(value)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    return str(value).strip().lower() in {"true", "1", "yes"}


def safe_247_prediction_display_match(row, player_name: str) -> bool:
    """Use 247 fields from the dual BPR CSV for display only when identity is exact."""
    return (
        optional_number(row.get("247_player_key")) is not None
        and truthy(row.get("match_flag"))
        and names_match(row.get("247_full_name"), player_name)
    )


def first_247_display_value(row, metadata_column: str, prediction_column: str, allow_prediction_fallback: bool):
    metadata_value = clean_value(row.get(metadata_column))
    if metadata_value is not None:
        return metadata_value
    if allow_prediction_fallback:
        return clean_value(row.get(prediction_column))
    return None


def build_player(row) -> dict:
    top_role = clean_value(row.get("pred_role_1")) or "Unknown"
    role_probabilities = {
        column.replace("prob_", "").replace("_", " ").replace("PF C", "PF/C"): round(float(row[column]), 6)
        for column in ROLE_COLUMNS
        if clean_value(row.get(column)) is not None
    }

    top_prob = optional_number(row.get("pred_prob_1")) or 0.0
    class_year = clean_value(row.get("allyears_yr")) or clean_value(row.get("transfer_player_class")) or "N/A"
    conference = clean_value(row.get("transfer_old_team_conf")) or "Transfer"
    player_name = (
        clean_value(row.get("transfer_player_name"))
        or clean_value(row.get("allyears_player_name"))
        or "Unknown Transfer"
    )
    safe_247_match = safe_247_metadata_match(row, player_name)
    safe_247_display_match = safe_247_match or safe_247_prediction_display_match(row, player_name)
    origin = (
        first_non_null(row.get("metadata_247_source_school"), row.get("transfer_old_team"), row.get("allyears_team"))
        if safe_247_match
        else first_non_null(row.get("transfer_old_team"), row.get("allyears_team"))
    ) or "Uncommitted"
    destination = (
        first_non_null(row.get("metadata_247_destination_school"), row.get("transfer_new_team"))
        if safe_247_match
        else clean_value(row.get("transfer_new_team"))
    )
    if destination == "__MISSING__":
        destination = None
    status = "committed" if destination else "entered"
    transfer_status = clean_value(row.get("metadata_247_status")) if safe_247_match else None
    player_name_key = (player_name or "").strip().lower()
    origin_key = (clean_value(row.get("transfer_old_team")) or "").strip().lower()
    if (player_name_key, origin_key) in EXCLUDED_TRANSFER_KEYS:
        return None
    height = clean_height_text(
        first_247_display_value(row, "metadata_247_height", "247_height", safe_247_display_match)
        or row.get("transfer_player_height")
        or row.get("allyears_player_height")
        or row.get("allyears_ht")
    )
    weight = optional_number(
        first_247_display_value(row, "metadata_247_weight", "247_weight", safe_247_display_match)
    )
    weight = weight or 0
    player_key = optional_number(
        first_247_display_value(row, "metadata_247_player_key", "247_player_key", safe_247_display_match)
    )
    transfer_rating = optional_number(
        first_247_display_value(row, "metadata_247_transfer_rating", "247_transfer_rating", safe_247_display_match)
    )
    if transfer_rating is None:
        transfer_rating = optional_number(
            first_247_display_value(row, "metadata_247_rating", "247_rating", safe_247_display_match)
        )
    rating = transfer_rating
    stars = optional_number(
        first_247_display_value(row, "metadata_247_stars", "247_stars", safe_247_display_match)
    )
    transfer_rank = optional_number(
        first_247_display_value(row, "metadata_247_transfer_rank", "247_transfer_rank", safe_247_display_match)
    )
    transfer_bpr = optional_number(row.get("pred_next_year_basic_bpr"))
    transfer_barttorvik_trid = optional_number(row.get("allyears_barttorvik_trid")) or optional_number(row.get("transfer_barttorvik_trid"))
    transfer_barttorvik_trid = TRANSFER_TRID_OVERRIDES.get(
        (player_name_key, origin_key, int(row["transfer_row_number"])),
        transfer_barttorvik_trid,
    )
    transfer_status_display = transfer_status
    if transfer_status_display is None and safe_247_display_match:
        transfer_status_display = clean_value(row.get("247_status"))

    transfer_image = None
    if player_key is not None:
        avatar_url = first_247_display_value(
            row, "metadata_247_avatar_url", "247_avatar_url", safe_247_display_match
        )
        transfer_image = extract_profile_image(int(player_key), clean_value(avatar_url))

    projected_bpr = round(transfer_bpr, 1) if transfer_bpr is not None else round(3.0 + top_prob * 5.5, 1)
    projected_minutes = max(8, min(32, int(round(12 + top_prob * 20))))
    projected_points = round(max(4.0, 8.0 + top_prob * 8.0), 1)
    projected_rebounds = round(6.0 if top_role in {"C", "PF/C", "Stretch 4"} else 3.2, 1)
    projected_assists = round(4.2 if top_role in {"Pure PG", "Scoring PG", "Combo G"} else 1.5, 1)
    fit_score = max(50, min(99, int(round(50 + top_prob * 49))))

    player = {
        "player_id": f"transfer-{int(row['transfer_row_number'])}",
        "player_name": player_name,
        "player_source": "transfer",
        "profile_image_url": transfer_image,
        "position": first_position(
            row.get("transfer_player_role"),
            row.get("allyears_role"),
            first_247_display_value(row, "metadata_247_position", "247_position", safe_247_display_match),
        ),
        "height": height,
        "weight": weight,
        "class_year": class_year,
        "current_team": origin,
        "previous_team": origin,
        "new_team": destination,
        "conference": conference,
        "portal_status": status,
        "is_in_portal": True,
        "committed_team": destination,
        "transfer_247_status": transfer_status_display,
        "transfer_247_stars": stars,
        "transfer_247_rating": rating,
        "transfer_247_rank": transfer_rank,
        "transfer_247_weight": weight,
        "transfer_247_player_key": int(player_key) if player_key is not None else None,
        "transfer_barttorvik_trid": int(transfer_barttorvik_trid) if transfer_barttorvik_trid is not None else None,
        "transfer_bpr": transfer_bpr,
        "skill_spacing_percentile": optional_number(row.get("spacing_percentile")),
        "skill_facilitating_percentile": optional_number(row.get("facilitating_percentile")),
        "skill_rim_protection_percentile": optional_number(row.get("rim_protection_percentile")),
        "skill_defense_percentile": optional_number(row.get("defense_percentile")),
        "skill_finishing_percentile": optional_number(row.get("finishing_percentile")),
        "projected_bpr": projected_bpr,
        "projected_minutes": projected_minutes,
        "projected_points": projected_points,
        "projected_rebounds": projected_rebounds,
        "projected_assists": projected_assists,
        "playtype_probabilities": role_probabilities,
        "fit_score": fit_score,
        "recommendation_rank": int(row["transfer_row_number"]),
        "fit_explanation": f"Transfer projected most likely as {top_role}.",
        "scouting_summary": "Model-driven role projection from transfer portal data.",
        "hs_rating": None,
        "hs_stars": None,
        "hs_national_rank": None,
        "hs_position_rank": None,
        "hs_player_key": None,
        "top3_roles": [
            {
                "label": clean_value(row.get(f"pred_role_{idx}")),
                "probability": optional_number(row.get(f"pred_prob_{idx}")),
            }
            for idx in (1, 2, 3)
            if clean_value(row.get(f"pred_role_{idx}")) is not None
        ],
    }

    for optional_key in ["new_team", "committed_team", "hs_player_key", "transfer_247_status", "transfer_247_stars", "transfer_247_rating", "transfer_247_rank", "transfer_247_weight", "transfer_247_player_key", "transfer_barttorvik_trid", "transfer_bpr", "skill_spacing_percentile", "skill_facilitating_percentile", "skill_rim_protection_percentile", "skill_defense_percentile", "skill_finishing_percentile"]:
        if player.get(optional_key) is None:
            player.pop(optional_key, None)

    return player


def main() -> None:
    df = pd.read_csv(BPR_PREDICTIONS)
    if df["pred_next_year_basic_bpr"].isna().any():
        missing = int(df["pred_next_year_basic_bpr"].isna().sum())
        raise RuntimeError(f"Transfer BPR prediction file has {missing} missing pred_next_year_basic_bpr values.")
    if df.duplicated(["transfer_row_number", "allyears_barttorvik_trid"]).any():
        raise RuntimeError("Transfer BPR predictions are not unique by transfer_row_number + allyears_barttorvik_trid.")

    role_df = pd.read_csv(PREDICTIONS)[
        ["transfer_row_number", "allyears_barttorvik_trid", "pred_role_1", "pred_prob_1", "pred_role_2", "pred_prob_2", "pred_role_3", "pred_prob_3", *ROLE_COLUMNS]
    ]
    if role_df.duplicated(["transfer_row_number", "allyears_barttorvik_trid"]).any():
        raise RuntimeError("Transfer role predictions are not unique by transfer_row_number + allyears_barttorvik_trid.")

    before_rows = len(df)
    df = df.merge(
        role_df,
        on=["transfer_row_number", "allyears_barttorvik_trid"],
        how="left",
        validate="one_to_one",
    )
    if len(df) != before_rows:
        raise RuntimeError(f"Transfer role merge changed row count: before={before_rows}, after={len(df)}")

    percentile_df = pd.read_csv(PERCENTILES)[
        [
            "bvt_pid",
            "year",
            "spacing_percentile",
            "facilitating_percentile",
            "rim_protection_percentile",
            "defense_percentile",
            "finishing_percentile",
        ]
    ].copy()
    percentile_df = percentile_df[percentile_df["year"] == 2026].drop(columns=["year"])
    percentile_df["bvt_pid"] = pd.to_numeric(percentile_df["bvt_pid"], errors="raise").astype(int)
    if percentile_df["bvt_pid"].duplicated().any():
        raise RuntimeError("2026 skill percentile rows are not unique by bvt_pid.")

    con = duckdb.connect(str(TRANSFER_247_BV_DB), read_only=True)
    metadata_df = con.execute(
        """
        SELECT
            db1_allyears_pid AS metadata_allyears_pid,
            "247_full_name" AS metadata_247_full_name,
            "247_position" AS metadata_247_position,
            "247_height" AS metadata_247_height,
            "247_source_school" AS metadata_247_source_school,
            "247_destination_school" AS metadata_247_destination_school,
            "247_player_key" AS metadata_247_player_key,
            "247_weight" AS metadata_247_weight,
            "247_stars" AS metadata_247_stars,
            "247_rating" AS metadata_247_rating,
            "247_transfer_rating" AS metadata_247_transfer_rating,
            "247_transfer_rank" AS metadata_247_transfer_rank,
            "247_status" AS metadata_247_status,
            "247_avatar_url" AS metadata_247_avatar_url,
            "247_cache_path" AS metadata_247_cache_path,
            name_score AS metadata_name_score,
            overall_match_score AS metadata_overall_match_score
        FROM transfer_247_bv_matched
        WHERE db1_allyears_year = 2026
        """
    ).fetchdf()
    con.close()
    metadata_df["metadata_allyears_pid"] = pd.to_numeric(metadata_df["metadata_allyears_pid"], errors="raise").astype(int)
    if metadata_df["metadata_allyears_pid"].duplicated().any():
        raise RuntimeError("2026 transfer 247/BV metadata rows are not unique by allyears pid.")

    df["allyears_pid"] = pd.to_numeric(df["allyears_pid"], errors="coerce").astype("Int64")
    df = df.merge(
        metadata_df,
        left_on="allyears_pid",
        right_on="metadata_allyears_pid",
        how="left",
        validate="many_to_one",
    ).drop(columns=["metadata_allyears_pid"])
    df = df.merge(
        percentile_df,
        left_on="allyears_pid",
        right_on="bvt_pid",
        how="left",
        validate="many_to_one",
    ).drop(columns=["bvt_pid"])

    players = [player for _, row in df.iterrows() if (player := build_player(row)) is not None]
    with_bpr = sum(1 for player in players if player.get("transfer_bpr") is not None)
    if with_bpr != len(players):
        raise RuntimeError(f"Generated transfer rows without transfer_bpr: players={len(players)}, with_bpr={with_bpr}")
    with_247_metadata = sum(1 for player in players if player.get("transfer_247_player_key") is not None)
    with_skill_percentiles = sum(
        1
        for player in players
        if all(
            player.get(key) is not None
            for key in [
                "skill_spacing_percentile",
                "skill_facilitating_percentile",
                "skill_rim_protection_percentile",
                "skill_defense_percentile",
                "skill_finishing_percentile",
            ]
        )
    )

    players_json = json_literal(players)
    lines = [
        'import type { Player } from "./players";',
        "",
        "// Generated by frontend_site/scripts/build_transfer_players.py.",
        "// Sources:",
        "// - models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions.csv",
        "// - models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/dual_transfer_bpr_inference_2026_20260607_190712/dual_transfer_bpr_predictions_2026.csv",
        "// - data_dir/247_bv_transf_matched.db (safe 247 metadata only; not used for transfer origin/destination)",
        "// - data_dir/player_percentile/cluster_percentile_outputs/players_group_percentiles_from_db.csv (radar percentiles only)",
        f"export const transferPlayers = JSON.parse({json_literal(players_json)}) as Player[];",
        "",
    ]
    OUTPUT.write_text("\n".join(lines))
    print(f"wrote {OUTPUT}")
    print(f"players={len(players)} with_bpr={with_bpr} with_247_metadata={with_247_metadata} with_skill_percentiles={with_skill_percentiles}")


if __name__ == "__main__":
    main()
