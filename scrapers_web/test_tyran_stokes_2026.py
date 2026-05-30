from pathlib import Path

import pandas as pd
import requests

try:
    from common_247 import (
        SPORT_KEY_MBB,
        TFS_BASE_URL,
        extract_profile_jsonld_measurables,
        extract_scouting_report,
        fetch_text_cached,
        get_247_headers,
        normalize_profile_url,
        request_json,
    )
    from scrape_247_hs_2025 import flatten_recruits
except ModuleNotFoundError:
    from .common_247 import (
        SPORT_KEY_MBB,
        TFS_BASE_URL,
        extract_profile_jsonld_measurables,
        extract_scouting_report,
        fetch_text_cached,
        get_247_headers,
        normalize_profile_url,
        request_json,
    )
    from .scrape_247_hs_2025 import flatten_recruits


YEAR = 2026
PLAYER_FIRST = "Tyran"
PLAYER_LAST = "Stokes"
PAGE_SIZE = 250
OUT_DIR = Path(__file__).resolve().parent / "outputs"
CACHE_DIR = Path(__file__).resolve().parent / "cache" / "hs" / str(YEAR)


def pull_2026_recruits(session):
    players = []
    page = 1
    while True:
        data = request_json(
            session=session,
            url=TFS_BASE_URL + "recruits",
            params={
                "sportKey": SPORT_KEY_MBB,
                "year": YEAR,
                "page": page,
                "pageSize": PAGE_SIZE,
            },
            cache_path=CACHE_DIR / "api" / f"recruits_page_{page}.json",
        )
        players.extend(data.get("players", []))
        pagination = data.get("pagination", {})
        if page >= int(pagination.get("pageCount", page)):
            break
        page += 1
    return players


def normalize_one(enriched):
    row = enriched.iloc[0]
    return pd.DataFrame(
        [
            {
                "year": YEAR,
                "player_key": row["key"],
                "first_name": row["firstName"],
                "last_name": row["lastName"],
                "full_name": f"{row['firstName']} {row['lastName']}".strip(),
                "position": row["primaryPosition"],
                "height": row["height"],
                "weight": row["weight"],
                "stars": row["compositeStarRating"],
                "rating": row["compositeRating"],
                "national_rank": row["compositeNationalRank"],
                "position_rank": row["compositePositionRank"],
                "state_rank": row["compositeStateRank"],
                "hometown_city": row["homeTown.city"],
                "hometown_state": row["homeTown.state"],
                "committed_institution_key": row["committedInstitution.institutionKey"],
                "committed_team_key": row["committedInstitution.teamKey"],
                "committed_school": row["committedInstitution.name"],
                "committed_school_abbr": row["committedInstitution.abbreviation"],
                "committed_school_full": row["committedInstitution.fullName"],
                "signed_institution_key": row["signedInstitution.institutionKey"],
                "signed_team_key": row["signedInstitution.teamKey"],
                "signed_school": row["signedInstitution.name"],
                "signed_school_abbr": row["signedInstitution.abbreviation"],
                "signed_school_full": row["signedInstitution.fullName"],
                "current_institution_key": row["currentInstitution.institutionKey"],
                "current_team_key": row["currentInstitution.teamKey"],
                "current_school": row["currentInstitution.name"],
                "current_school_abbr": row["currentInstitution.abbreviation"],
                "current_school_full": row["currentInstitution.fullName"],
                "profile_url_api": row["profileUrl"],
                "profile_lookup_url": row["profile_lookup_url"],
                "profile_lookup_status": row["profile_lookup_status"],
                "has_scouting_report": row["has_scouting_report"],
                "scouting_report": row["scouting_report"],
                "source": "247sports_api_recruits_plus_profile_jsonld",
            }
        ]
    )


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    api_session = requests.Session()
    api_session.headers.update(get_247_headers())
    players = pull_2026_recruits(api_session)
    recruit = [
        player
        for player in players
        if player.get("firstName", "").casefold() == PLAYER_FIRST.casefold()
        and player.get("lastName", "").casefold() == PLAYER_LAST.casefold()
    ]
    if len(recruit) != 1:
        raise RuntimeError(f"Expected one {PLAYER_FIRST} {PLAYER_LAST} match, found {len(recruit)}")

    recruit_df = flatten_recruits(recruit)
    row = recruit_df.iloc[0]
    player_key = row["key"]
    profile_url = normalize_profile_url(row["profileUrl"])

    profile_session = requests.Session()
    profile_session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    html, status = fetch_text_cached(
        session=profile_session,
        url=profile_url,
        cache_path=CACHE_DIR / "profiles" / f"{player_key}.html",
    )
    height, weight = extract_profile_jsonld_measurables(html) if status == 200 else (None, None)
    scouting_report = extract_scouting_report(html) if status == 200 else None

    recruit_df["profile_lookup_url"] = profile_url
    recruit_df["profile_lookup_status"] = status
    recruit_df["height"] = height
    recruit_df["weight"] = weight
    recruit_df["scouting_report"] = scouting_report
    recruit_df["has_scouting_report"] = bool(scouting_report)

    final = normalize_one(recruit_df)
    out_path = OUT_DIR / "tyran_stokes_2026_test.csv"
    final.to_csv(out_path, index=False)

    print(f"Wrote {out_path}: {final.shape}")
    print(f"height={height!r} weight={weight!r}")
    print(f"has_scouting_report={bool(scouting_report)}")
    print(f"scouting_report_chars={len(scouting_report or '')}")
    print(final[["full_name", "position", "height", "weight", "committed_school", "has_scouting_report"]].to_string(index=False))


if __name__ == "__main__":
    main()
