import ast
from pathlib import Path

import pandas as pd
import requests

try:
    from common_247 import SPORT_KEY_MBB, TFS_BASE_URL, get_247_headers, request_json
except ModuleNotFoundError:
    from .common_247 import SPORT_KEY_MBB, TFS_BASE_URL, get_247_headers, request_json


YEAR = 2025
PAGE_SIZE = 250
LIST_TYPE_OVERALL = 3
OUT_DIR = Path(__file__).resolve().parent / "outputs"
CACHE_DIR = Path(__file__).resolve().parent / "cache" / "transfers" / str(YEAR)


def pull_all_transfers(session):
    all_players = []
    page = 1
    while True:
        data = request_json(
            session=session,
            url=TFS_BASE_URL + "transfers",
            params={
                "sportKey": SPORT_KEY_MBB,
                "year": YEAR,
                "listType": LIST_TYPE_OVERALL,
                "page": page,
                "pageSize": PAGE_SIZE,
            },
            cache_path=CACHE_DIR / "api" / f"transfers_page_{page}.json",
        )
        players = data.get("players", [])
        all_players.extend(players)
        pagination = data.get("pagination", {})
        print(
            f"Transfer API page {page}: {len(players)} rows "
            f"({len(all_players)}/{pagination.get('count', '?')})"
        )
        if page >= int(pagination.get("pageCount", page)):
            break
        page += 1
    return all_players


def flatten_destination(value):
    if isinstance(value, list):
        destinations = value
    elif isinstance(value, str) and value.strip():
        try:
            destinations = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            destinations = []
    else:
        destinations = []

    committed = next((item for item in destinations if item.get("transferred")), None)
    if committed is None and destinations:
        committed = destinations[0]
    committed = committed or {}
    return pd.Series(
        {
            "destination_school": committed.get("institution"),
            "destination_institution_key": committed.get("institutionKey"),
            "destination_school_root_path": committed.get("institutionRootPath"),
            "destination_transferred": committed.get("transferred"),
            "destination_options_count": len(destinations),
        }
    )


def normalize_final(df):
    for col in [
        "player.transfer.destination",
        "player.firstName",
        "player.lastName",
        "player.transfer.source.institution",
        "player.transfer.source.institutionKey",
    ]:
        if col not in df.columns:
            df[col] = None

    destinations = df["player.transfer.destination"].apply(flatten_destination)
    return pd.DataFrame(
        {
            "year": YEAR,
            "player_key": df["player.key"],
            "first_name": df["player.firstName"],
            "last_name": df["player.lastName"],
            "full_name": (
                df["player.firstName"].fillna("").astype(str)
                + " "
                + df["player.lastName"].fillna("").astype(str)
            ).str.strip(),
            "position": df["player.position"],
            "position_group": df["player.positionGroupName"],
            "height": df["player.height"],
            "weight": df["player.weight"],
            "stars": df["player.starRating"],
            "rating": df["player.rating"],
            "transfer_rating": df["player.transferRating"],
            "high_school_rating": df["player.highSchoolRating"],
            "transfer_rank": df["player.transferRank"],
            "high_school_rank": df["player.highSchoolRank"],
            "position_rank": df["player.positionRank"],
            "state_rank": df["player.stateRank"],
            "eligibility_type": df["player.eligibility.type"],
            "eligibility_years": df["player.eligibility.years"],
            "status": df["player.status"],
            "institution_status": df["player.institutionStatus"],
            "transfer_date": df["player.transferDate"],
            "transfer_commit_date": df["player.transferCommitDateTime"],
            "source_school": df["player.transfer.source.institution"],
            "source_institution_key": df["player.transfer.source.institutionKey"],
            "source_school_root_path": df["player.transfer.source.institutionRootPath"],
            "destination_school": destinations["destination_school"],
            "destination_institution_key": destinations["destination_institution_key"],
            "destination_school_root_path": destinations["destination_school_root_path"],
            "destination_transferred": destinations["destination_transferred"],
            "destination_options_count": destinations["destination_options_count"],
            "player_profile_url": df["player.playerProfileUrl"],
            "avatar_url": df["player.avatar"],
            "last_update_date": df["player.lastUpdateDate"],
            "source": "247sports_api_transfers",
        }
    )


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(get_247_headers())
    players = pull_all_transfers(session)
    raw = pd.json_normalize(players)
    final = normalize_final(raw)

    raw_csv = OUT_DIR / f"transfers_247_api_raw_{YEAR}.csv"
    final_csv = OUT_DIR / f"transfers_247_enriched_{YEAR}.csv"
    raw.to_csv(raw_csv, index=False)
    final.to_csv(final_csv, index=False)

    print(f"Wrote {raw_csv}: {raw.shape}")
    print(f"Wrote {final_csv}: {final.shape}")
    print(f"height rows: {final['height'].notna().sum()}/{len(final)}")
    print(f"weight rows: {final['weight'].notna().sum()}/{len(final)}")
    print(final.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
