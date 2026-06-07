from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend_site"
PREDICTIONS = ROOT / "models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions_with_247_cols.csv"
PROFILE_CACHE_DIR = ROOT / "scrapers_web/cache/transfers/2026/profiles"
OUTPUT = FRONTEND / "data/transferPlayers.ts"
ALLOWED_POSITIONS = {"PG", "SG", "CG", "SF", "PF", "C", "N/A"}
EXCLUDED_TRANSFER_KEYS = {
    ("cole alexander", "fairleigh dickinson"),
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
    return text or "N/A"


def normalize_position(value) -> str:
    value = clean_value(value)
    if value is None:
        return "N/A"
    text = str(value).strip().upper()
    return text if text in ALLOWED_POSITIONS else "N/A"


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


def build_player(row) -> dict:
    top_role = clean_value(row.get("pred_role_1")) or "Unknown"
    role_probabilities = {
        column.replace("prob_", "").replace("_", " ").replace("PF C", "PF/C"): round(float(row[column]), 6)
        for column in ROLE_COLUMNS
        if clean_value(row.get(column)) is not None
    }

    top_prob = optional_number(row.get("pred_prob_1")) or 0.0
    origin = first_non_null(row.get("247_source_school"), row.get("transfer_old_team")) or "Uncommitted"
    destination = first_non_null(row.get("247_destination_school"), row.get("transfer_new_team"))
    class_year = clean_value(row.get("allyears_yr")) or clean_value(row.get("transfer_player_class")) or "N/A"
    transfer_status = clean_value(row.get("247_status"))
    status = "committed" if (destination or (transfer_status and str(transfer_status).lower() in {"committed", "enrolled"})) else "entered"
    conference = clean_value(row.get("transfer_old_team_conf")) or "Transfer"
    player_name = (
        clean_value(row.get("transfer_player_name"))
        or clean_value(row.get("247_full_name"))
        or clean_value(row.get("allyears_player_name"))
        or "Unknown Transfer"
    )
    player_name_key = (player_name or "").strip().lower()
    origin_key = (clean_value(row.get("transfer_old_team")) or "").strip().lower()
    if (player_name_key, origin_key) in EXCLUDED_TRANSFER_KEYS:
        return None
    height = clean_height_text(
        row.get("allyears_ht")
        or row.get("247_height")
        or row.get("transfer_player_height")
        or row.get("allyears_player_height")
    )
    weight = optional_number(row.get("247_weight")) or 0
    player_key = optional_number(row.get("247_player_key"))
    transfer_rating = optional_number(row.get("247_transfer_rating"))
    rating = transfer_rating if transfer_rating is not None else optional_number(row.get("247_rating"))
    stars = optional_number(row.get("247_stars"))
    transfer_rank = optional_number(row.get("247_transfer_rank"))
    transfer_image = None
    if player_key is not None:
        transfer_image = extract_profile_image(int(player_key), clean_value(row.get("247_avatar_url")))

    projected_bpr = round(3.0 + top_prob * 5.5, 1)
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
        "position": normalize_position(row.get("247_position")),
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
        "transfer_247_status": transfer_status,
        "transfer_247_stars": stars,
        "transfer_247_rating": rating,
        "transfer_247_rank": transfer_rank,
        "transfer_247_weight": weight,
        "transfer_247_player_key": int(player_key) if player_key is not None else None,
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

    for optional_key in ["new_team", "committed_team", "hs_player_key", "transfer_247_status", "transfer_247_stars", "transfer_247_rating", "transfer_247_rank", "transfer_247_weight", "transfer_247_player_key"]:
        if player.get(optional_key) is None:
            player.pop(optional_key, None)

    return player


def main() -> None:
    df = pd.read_csv(PREDICTIONS)
    players = [player for _, row in df.iterrows() if (player := build_player(row)) is not None]

    lines = [
        'import type { Player } from "./players";',
        "",
        "// Generated by frontend_site/scripts/build_transfer_players.py.",
        "// Source: models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions_with_247_cols.csv",
        f"export const transferPlayers: Player[] = {json_literal(players)};",
        "",
    ]
    OUTPUT.write_text("\n".join(lines))
    print(f"wrote {OUTPUT}")
    print(f"players={len(players)}")


if __name__ == "__main__":
    main()
