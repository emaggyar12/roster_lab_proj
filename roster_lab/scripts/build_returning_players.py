#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from html import unescape
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend_site"
SAME_SCHOOL_PREDICTIONS = (
    ROOT
    / "models_dir/same_school_bpr/catboost_same_school_bpr_inference_outputs/"
    / "catboost_same_school__2026_20260607_201623/catboost_same_school_predictions_2026.csv"
)
TRANSFER_PREDICTIONS = (
    ROOT
    / "models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/"
    / "dual_transfer_bpr_inference_2026_20260607_190712/dual_transfer_bpr_predictions_2026.csv"
)
PERCENTILES = ROOT / "data_dir/player_percentile/cluster_percentile_outputs/players_group_percentiles_from_db.csv"
OUTPUT = FRONTEND / "data/returningPlayers.ts"
HS_BV_MATCHED_DB = ROOT / "data_dir/hs_bv_matched.db"
HS_CACHE = ROOT / "scrapers_web/cache/hs"


POSITION_BY_ROLE = {
    "Pure PG": "PG",
    "Scoring PG": "PG",
    "Combo G": "CG",
    "Wing G": "SG",
    "Wing F": "SF",
    "Stretch 4": "PF",
    "PF/C": "PF",
    "C": "C",
}

CLASS_BY_SOURCE = {
    "FR": "Fr",
    "SO": "So",
    "JR": "Jr",
    "SR": "Sr",
    "GR": "Gr",
    "Fr": "Fr",
    "So": "So",
    "Jr": "Jr",
    "Sr": "Sr",
    "Gr": "Gr",
}

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


def clean_value(value: Any) -> Any:
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


def clean_float(value: Any) -> float | None:
    value = clean_value(value)
    if value is None:
        return None
    return float(value)


def clean_int(value: Any) -> int | None:
    value = clean_value(value)
    if value is None:
        return None
    return int(float(value))


def clean_height_text(value: Any) -> str:
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


def json_literal(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)


def extract_profile_image_url(profile_path: Path) -> str | None:
    if not profile_path.exists():
        return None
    html = profile_path.read_text(errors="ignore")
    patterns = [
        r'<meta\s+(?:content="([^"]+)"\s+property="og:image"|property="og:image"\s+content="([^"]+)")',
        r'<meta\s+(?:name="twitter:image"\s+content="([^"]+)"|content="([^"]+)"\s+name="twitter:image")',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if not match:
            continue
        url = unescape(next(group for group in match.groups() if group))
        if "s3media.247sports.com/Uploads/Assets" in url:
            return url
    return None


def load_returning_profile_images(returning_pids: set[int]) -> dict[int, str]:
    if not returning_pids:
        return {}
    con = duckdb.connect(str(HS_BV_MATCHED_DB), read_only=True)
    pid_values = ", ".join(str(pid) for pid in sorted(returning_pids))
    matches = con.execute(
        f"""
        SELECT
            bv_pid,
            hs_player_key,
            hs_year,
            hs_dob_247_source_profile_file
        FROM hs_bv_matched
        WHERE bv_pid IN ({pid_values})
        ORDER BY bv_pid, hs_year DESC
        """
    ).fetchdf()
    con.close()

    profile_images: dict[int, str] = {}
    for row in matches.itertuples(index=False):
        pid = int(row.bv_pid)
        if pid in profile_images:
            continue
        paths: list[Path] = []
        if isinstance(row.hs_dob_247_source_profile_file, str) and row.hs_dob_247_source_profile_file.strip():
            paths.append(ROOT / row.hs_dob_247_source_profile_file)
        if pd.notna(row.hs_player_key) and pd.notna(row.hs_year):
            paths.append(HS_CACHE / str(int(row.hs_year)) / "profiles" / f"{int(row.hs_player_key)}.html")
        for path in paths:
            image_url = extract_profile_image_url(path)
            if image_url:
                profile_images[pid] = image_url
                break
    return profile_images


def build_player(row: pd.Series, rank: int, profile_image_url: str | None) -> dict[str, Any]:
    role = clean_value(row.get("bvt_role")) or "N/A"
    projected_bpr = clean_float(row.get("pred_next_basic_bpr")) or 0.0
    current_bpr = clean_float(row.get("basic_bpr"))
    class_year = CLASS_BY_SOURCE.get(str(clean_value(row.get("bvt_player_class")) or clean_value(row.get("advanced_class")) or "").strip(), "N/A")
    pid = clean_int(row.get("bvt_pid"))
    return {
        "player_id": f"returning-{pid}",
        "player_name": clean_value(row.get("name")) or "Unknown Player",
        "player_source": "roster",
        "profile_image_url": profile_image_url,
        "position": POSITION_BY_ROLE.get(role, "N/A"),
        "height": clean_height_text(row.get("bvt_player_height")),
        "weight": 0,
        "class_year": class_year,
        "current_team": clean_value(row.get("team")) or "Unknown Team",
        "conference": "Returning",
        "portal_status": "not_in_portal",
        "is_in_portal": False,
        "projected_bpr": projected_bpr,
        "projected_minutes": 0,
        "projected_points": 0,
        "projected_rebounds": 0,
        "projected_assists": 0,
        "playtype_probabilities": {},
        "fit_score": max(0, min(99, round((projected_bpr + 5) * 8))),
        "recommendation_rank": rank,
        "fit_explanation": "Same-school returning player projection.",
        "scouting_summary": "Projected from same-school BPR model; transfer-listed PIDs are excluded from this Returning pool.",
        "returning_bvt_pid": pid,
        "returning_barttorvik_trid": clean_int(row.get("bvt_barttorvik_trid")),
        "returning_role": role,
        "returning_current_bpr": current_bpr,
        "returning_projected_bpr": projected_bpr,
        "season_basic_bpr": current_bpr,
        "season_gp": clean_float(row.get("bvt_GP")),
        "season_mp": clean_float(row.get("bvt_mp")),
        "season_oreb": clean_float(row.get("bvt_oreb")),
        "season_dreb": clean_float(row.get("bvt_dreb")),
        "season_treb": clean_float(row.get("bvt_treb")),
        "season_ast": clean_float(row.get("bvt_ast")),
        "season_stl": clean_float(row.get("bvt_stl")),
        "season_blk": clean_float(row.get("bvt_blk")),
        "season_pts": clean_float(row.get("bvt_pts")),
        "season_ft_pct": clean_float(row.get("bvt_FT_per")),
        "skill_spacing_percentile": clean_float(row.get("spacing_percentile")),
        "skill_facilitating_percentile": clean_float(row.get("facilitating_percentile")),
        "skill_rim_protection_percentile": clean_float(row.get("rim_protection_percentile")),
        "skill_defense_percentile": clean_float(row.get("defense_percentile")),
        "skill_finishing_percentile": clean_float(row.get("finishing_percentile")),
    }


def main() -> None:
    df = pd.read_csv(SAME_SCHOOL_PREDICTIONS)
    transfer_df = pd.read_csv(TRANSFER_PREDICTIONS, usecols=["allyears_pid"])
    transfer_pids = set(pd.to_numeric(transfer_df["allyears_pid"], errors="coerce").dropna().astype(int))

    before_rows = len(df)
    df["bvt_pid"] = pd.to_numeric(df["bvt_pid"], errors="raise").astype(int)
    if df["bvt_pid"].duplicated().any():
        raise RuntimeError("Same-school prediction rows are not unique by bvt_pid.")
    df = df[~df["bvt_pid"].isin(transfer_pids)].copy()
    excluded_transfer_rows = before_rows - len(df)
    percentile_df = pd.read_csv(PERCENTILES)[
        [
            "bvt_pid",
            "spacing_percentile",
            "facilitating_percentile",
            "rim_protection_percentile",
            "defense_percentile",
            "finishing_percentile",
        ]
    ].copy()
    percentile_df["bvt_pid"] = pd.to_numeric(percentile_df["bvt_pid"], errors="raise").astype(int)
    if percentile_df["bvt_pid"].duplicated().any():
        raise RuntimeError("Skill percentile rows are not unique by bvt_pid.")
    before_percentile_merge = len(df)
    df = df.merge(percentile_df, on="bvt_pid", how="left", validate="one_to_one")
    if len(df) != before_percentile_merge:
        raise RuntimeError(
            f"Skill percentile merge changed row count: before={before_percentile_merge}, after={len(df)}"
        )
    df = df.sort_values(["pred_next_basic_bpr", "name"], ascending=[False, True]).reset_index(drop=True)
    profile_images = load_returning_profile_images(set(df["bvt_pid"].astype(int)))

    players = [
        build_player(row, index + 1, profile_images.get(int(row["bvt_pid"])))
        for index, row in df.iterrows()
    ]
    with_projected_bpr = sum(1 for player in players if player["returning_projected_bpr"] is not None)
    with_images = sum(1 for player in players if player["profile_image_url"])
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

    lines = [
        'import type { Player } from "./players";',
        "",
        "// Generated by frontend_site/scripts/build_returning_players.py.",
        "// Same-school BPR predictions for 2026 players, excluding known transfer PIDs.",
        f"export const returningPlayers: Player[] = {json_literal(players)};",
        "",
        "export const returningPlayerBuildInfo = {",
        f"  sourceRows: {before_rows},",
        f"  excludedTransferRows: {excluded_transfer_rows},",
        f"  total: {len(players)},",
        f"  withProjectedBpr: {with_projected_bpr},",
        f"  withImages: {with_images},",
        f"  withSkillPercentiles: {with_skill_percentiles},",
        "};",
        "",
    ]
    OUTPUT.write_text("\n".join(lines))
    print(
        f"players={len(players)} source_rows={before_rows} "
        f"excluded_transfer_rows={excluded_transfer_rows} with_projected_bpr={with_projected_bpr} "
        f"with_images={with_images} with_skill_percentiles={with_skill_percentiles}"
    )


if __name__ == "__main__":
    main()
