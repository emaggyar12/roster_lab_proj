import concurrent.futures
from pathlib import Path

import duckdb
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


START_YEAR = 2010
END_YEAR = 2026
PAGE_SIZE = 250
MAX_WORKERS = 8
OUT_DIR = Path(__file__).resolve().parent / "outputs"
CACHE_ROOT = Path(__file__).resolve().parent / "cache" / "hs"


def pull_all_recruits(session, year):
    cache_dir = CACHE_ROOT / str(year)
    all_players = []
    page = 1
    while True:
        data = request_json(
            session=session,
            url=TFS_BASE_URL + "recruits",
            params={
                "sportKey": SPORT_KEY_MBB,
                "year": year,
                "page": page,
                "pageSize": PAGE_SIZE,
            },
            cache_path=cache_dir / "api" / f"recruits_page_{page}.json",
        )
        players = data.get("players", [])
        all_players.extend(players)
        pagination = data.get("pagination", {})
        print(
            f"HS API {year} page {page}: {len(players)} rows "
            f"({len(all_players)}/{pagination.get('count', '?')})",
            flush=True,
        )
        if page >= int(pagination.get("pageCount", page)):
            break
        page += 1
    return all_players


def flatten_recruits(players):
    df = pd.json_normalize(players)
    expected_cols = [
        "key",
        "cbs_Key",
        "firstName",
        "lastName",
        "profileUrl",
        "defaultAssetUrl",
        "primaryPosition",
        "compositeRating",
        "compositeStarRating",
        "compositeNationalRank",
        "compositePositionRank",
        "compositeStateRank",
        "homeTown.city",
        "homeTown.state",
        "committedInstitution.institutionKey",
        "committedInstitution.teamKey",
        "committedInstitution.cbsKey",
        "committedInstitution.name",
        "committedInstitution.abbreviation",
        "committedInstitution.fullName",
        "signedInstitution.institutionKey",
        "signedInstitution.teamKey",
        "signedInstitution.cbsKey",
        "signedInstitution.name",
        "signedInstitution.abbreviation",
        "signedInstitution.fullName",
        "currentInstitution.institutionKey",
        "currentInstitution.teamKey",
        "currentInstitution.cbsKey",
        "currentInstitution.name",
        "currentInstitution.abbreviation",
        "currentInstitution.fullName",
    ]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None
    return df


def profile_lookup(row_dict, year):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    player_key = row_dict["key"]
    url = normalize_profile_url(row_dict.get("profileUrl"))
    if not url:
        return {
            "key": player_key,
            "profile_lookup_url": None,
            "profile_lookup_status": None,
            "height": None,
            "weight": None,
            "scouting_report": None,
            "has_scouting_report": False,
        }

    html, status = fetch_text_cached(
        session=session,
        url=url,
        cache_path=CACHE_ROOT / str(year) / "profiles" / f"{player_key}.html",
    )
    height, weight = extract_profile_jsonld_measurables(html) if status == 200 else (None, None)
    scouting_report = extract_scouting_report(html) if status == 200 else None
    return {
        "key": player_key,
        "profile_lookup_url": url,
        "profile_lookup_status": status,
        "height": height,
        "weight": weight,
        "scouting_report": scouting_report,
        "has_scouting_report": bool(scouting_report),
    }


def add_profile_enrichment(recruits_df, year):
    rows = recruits_df[["key", "profileUrl"]].to_dict("records")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(profile_lookup, row, year) for row in rows]
        for i, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            results.append(future.result())
            if i % 50 == 0 or i == len(futures):
                print(f"HS profile pages {year}: {i}/{len(futures)}", flush=True)
    return recruits_df.merge(pd.DataFrame(results), on="key", how="left")


def normalize_final(enriched, year):
    return pd.DataFrame(
        {
            "year": year,
            "player_key": enriched["key"],
            "first_name": enriched["firstName"],
            "last_name": enriched["lastName"],
            "full_name": (
                enriched["firstName"].fillna("").astype(str)
                + " "
                + enriched["lastName"].fillna("").astype(str)
            ).str.strip(),
            "position": enriched["primaryPosition"],
            "height": enriched["height"],
            "weight": enriched["weight"],
            "stars": enriched["compositeStarRating"],
            "rating": enriched["compositeRating"],
            "national_rank": enriched["compositeNationalRank"],
            "position_rank": enriched["compositePositionRank"],
            "state_rank": enriched["compositeStateRank"],
            "hometown_city": enriched["homeTown.city"],
            "hometown_state": enriched["homeTown.state"],
            "committed_institution_key": enriched["committedInstitution.institutionKey"],
            "committed_team_key": enriched["committedInstitution.teamKey"],
            "committed_school": enriched["committedInstitution.name"],
            "committed_school_abbr": enriched["committedInstitution.abbreviation"],
            "committed_school_full": enriched["committedInstitution.fullName"],
            "signed_institution_key": enriched["signedInstitution.institutionKey"],
            "signed_team_key": enriched["signedInstitution.teamKey"],
            "signed_school": enriched["signedInstitution.name"],
            "signed_school_abbr": enriched["signedInstitution.abbreviation"],
            "signed_school_full": enriched["signedInstitution.fullName"],
            "current_institution_key": enriched["currentInstitution.institutionKey"],
            "current_team_key": enriched["currentInstitution.teamKey"],
            "current_school": enriched["currentInstitution.name"],
            "current_school_abbr": enriched["currentInstitution.abbreviation"],
            "current_school_full": enriched["currentInstitution.fullName"],
            "profile_url_api": enriched["profileUrl"],
            "profile_lookup_url": enriched["profile_lookup_url"],
            "profile_lookup_status": enriched["profile_lookup_status"],
            "has_scouting_report": enriched["has_scouting_report"],
            "scouting_report": enriched["scouting_report"],
            "source": "247sports_api_recruits_plus_profile_jsonld",
        }
    )


def _series_equal(left, right):
    if pd.api.types.is_numeric_dtype(left) or pd.api.types.is_numeric_dtype(right):
        left_num = pd.to_numeric(left, errors="coerce")
        right_num = pd.to_numeric(right, errors="coerce")
        return (left_num.isna() & right_num.isna()) | ((left_num - right_num).abs() < 1e-9)
    return left.fillna("__NA__").astype(str) == right.fillna("__NA__").astype(str)


def validate_raw_vs_enriched(raw, enriched_final, year):
    raw_cmp = pd.DataFrame(
        {
            "player_key": raw["key"],
            "first_name": raw["firstName"],
            "last_name": raw["lastName"],
            "full_name": (
                raw["firstName"].fillna("").astype(str)
                + " "
                + raw["lastName"].fillna("").astype(str)
            ).str.strip(),
            "position": raw["primaryPosition"],
            "stars": raw["compositeStarRating"],
            "rating": raw["compositeRating"],
            "national_rank": raw["compositeNationalRank"],
            "position_rank": raw["compositePositionRank"],
            "state_rank": raw["compositeStateRank"],
            "hometown_city": raw["homeTown.city"],
            "hometown_state": raw["homeTown.state"],
            "committed_institution_key": raw["committedInstitution.institutionKey"],
            "committed_team_key": raw["committedInstitution.teamKey"],
            "committed_school": raw["committedInstitution.name"],
            "committed_school_abbr": raw["committedInstitution.abbreviation"],
            "committed_school_full": raw["committedInstitution.fullName"],
            "signed_institution_key": raw["signedInstitution.institutionKey"],
            "signed_team_key": raw["signedInstitution.teamKey"],
            "signed_school": raw["signedInstitution.name"],
            "signed_school_abbr": raw["signedInstitution.abbreviation"],
            "signed_school_full": raw["signedInstitution.fullName"],
            "current_institution_key": raw["currentInstitution.institutionKey"],
            "current_team_key": raw["currentInstitution.teamKey"],
            "current_school": raw["currentInstitution.name"],
            "current_school_abbr": raw["currentInstitution.abbreviation"],
            "current_school_full": raw["currentInstitution.fullName"],
            "profile_url_api": raw["profileUrl"],
        }
    )
    common_cols = list(raw_cmp.columns)
    enriched_cmp = enriched_final[common_cols].copy()

    errors = []
    if len(raw) != len(enriched_final):
        errors.append(f"row count mismatch raw={len(raw)} enriched={len(enriched_final)}")
    if raw["key"].duplicated().sum():
        errors.append(f"raw duplicate keys={raw['key'].duplicated().sum()}")
    if enriched_final["player_key"].duplicated().sum():
        errors.append(
            f"enriched duplicate keys={enriched_final['player_key'].duplicated().sum()}"
        )
    raw_keys = set(raw["key"])
    enriched_keys = set(enriched_final["player_key"])
    if raw_keys != enriched_keys:
        errors.append(
            f"key set mismatch raw_only={len(raw_keys - enriched_keys)} "
            f"enriched_only={len(enriched_keys - raw_keys)}"
        )

    raw_cmp = raw_cmp.sort_values("player_key").reset_index(drop=True)
    enriched_cmp = enriched_cmp.sort_values("player_key").reset_index(drop=True)
    mismatch_counts = {}
    for col in common_cols:
        equal_mask = _series_equal(raw_cmp[col], enriched_cmp[col])
        mismatch_count = int((~equal_mask).sum())
        if mismatch_count:
            mismatch_counts[col] = mismatch_count
    if mismatch_counts:
        errors.append(f"carried field mismatches={mismatch_counts}")

    if errors:
        raise ValueError(f"Validation failed for {year}: " + "; ".join(errors))

    validation = pd.DataFrame(
        [
            {
                "year": year,
                "raw_rows": len(raw),
                "enriched_rows": len(enriched_final),
                "duplicate_raw_keys": int(raw["key"].duplicated().sum()),
                "duplicate_enriched_keys": int(enriched_final["player_key"].duplicated().sum()),
                "height_non_null": int(enriched_final["height"].notna().sum()),
                "weight_non_null": int(enriched_final["weight"].notna().sum()),
                "scouting_report_true": int(enriched_final["has_scouting_report"].sum()),
                "profile_status_200": int((enriched_final["profile_lookup_status"] == 200).sum()),
                "validation_passed": True,
            }
        ]
    )
    return validation


def write_duckdb(db_path, raw, enriched, validation):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.register("raw_df", raw)
        con.register("enriched_df", enriched)
        con.register("validation_df", validation)
        con.execute("DROP TABLE IF EXISTS hs_recruits_raw")
        con.execute("DROP TABLE IF EXISTS hs_recruits_enriched")
        con.execute("DROP TABLE IF EXISTS validation_summary")
        con.execute("CREATE TABLE hs_recruits_raw AS SELECT * FROM raw_df")
        con.execute("CREATE TABLE hs_recruits_enriched AS SELECT * FROM enriched_df")
        con.execute("CREATE TABLE validation_summary AS SELECT * FROM validation_df")

        raw_count = con.execute("SELECT COUNT(*) FROM hs_recruits_raw").fetchone()[0]
        enriched_count = con.execute("SELECT COUNT(*) FROM hs_recruits_enriched").fetchone()[0]
        if raw_count != len(raw) or enriched_count != len(enriched):
            raise RuntimeError(
                f"DuckDB write failed for {db_path}: raw={raw_count}/{len(raw)} "
                f"enriched={enriched_count}/{len(enriched)}"
            )


def write_dummy_csv(path, enriched):
    if len(enriched) <= 10:
        dummy = enriched.copy()
    else:
        dummy = pd.concat([enriched.head(5), enriched.tail(5)], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    dummy.to_csv(path, index=False)


def scrape_year(session, year):
    players = pull_all_recruits(session, year)
    raw = flatten_recruits(players)
    enriched_intermediate = add_profile_enrichment(raw, year)
    enriched_final = normalize_final(enriched_intermediate, year)
    validation = validate_raw_vs_enriched(raw, enriched_final, year)

    db_path = OUT_DIR / f"hs_recruits_247_{year}.db"
    dummy_path = OUT_DIR / f"hs_recruit_dummy_{year}.csv"
    write_duckdb(db_path, raw, enriched_final, validation)
    write_dummy_csv(dummy_path, enriched_final)

    print(f"Wrote {db_path}: raw={raw.shape}, enriched={enriched_final.shape}", flush=True)
    print(f"Wrote {dummy_path}: {min(len(enriched_final), 10)} rows", flush=True)
    print(validation.to_string(index=False), flush=True)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(get_247_headers())
    for year in range(START_YEAR, END_YEAR + 1):
        scrape_year(session, year)


if __name__ == "__main__":
    main()
