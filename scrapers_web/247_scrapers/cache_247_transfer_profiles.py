from __future__ import annotations

import concurrent.futures
import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

try:
    from common_247 import (
        PROJECT_ROOT,
        fetch_text_cached,
        normalize_profile_url,
    )
except ModuleNotFoundError:
    from .common_247 import (
        PROJECT_ROOT,
        fetch_text_cached,
        normalize_profile_url,
    )


MAX_WORKERS = 8

OUTPUTS_ROOT = PROJECT_ROOT / "scrapers_web" / "247_scrapers" / "outputs"
CACHE_BASE_ROOT = PROJECT_ROOT / "scrapers_web" / "cache" / "transfers"


def get_247_page_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:71.0) Gecko/20100101 Firefox/71.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "close",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://247sports.com/",
    }


def safe_player_key(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", text)


def normalize_transfer_profile_url(value: object) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    if url.startswith("/"):
        return normalize_profile_url(url)
    return url


def canonicalize_transfer_profile_url(value: object) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None

    if url.startswith("/"):
        return normalize_profile_url(url)

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return normalize_profile_url(url)

    path = parsed.path.rstrip("/")
    if "/player/" not in path:
        return url

    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "player":
        slug = parts[1]
        match = re.search(r"-(\d+)$", slug)
        if match:
            return f"https://247sports.com/player/{slug}/"
    return url


def cache_one_profile(session: requests.Session, row: dict[str, object]) -> dict[str, object]:
    year = int(row.get("year") or 0)
    player_key = safe_player_key(row.get("player_key"))
    raw_profile_url = normalize_transfer_profile_url(row.get("player_profile_url"))
    if not raw_profile_url:
        return {
            "player_key": player_key,
            "profile_url": None,
            "cache_path": None,
            "status_code": None,
            "resolved_via": None,
        }

    cache_root = CACHE_BASE_ROOT / str(year)
    profile_cache = cache_root / "profiles"
    cache_path = profile_cache / f"{player_key}.html"
    canonical_url = canonicalize_transfer_profile_url(raw_profile_url)
    urls_to_try = [raw_profile_url]
    if canonical_url and canonical_url != raw_profile_url:
        urls_to_try.append(canonical_url)

    status = None
    chosen_url = None
    chosen_via = None
    for attempt_name, candidate_url in zip(("raw", "canonical"), urls_to_try):
        _, candidate_status = fetch_text_cached(session=session, url=candidate_url, cache_path=cache_path)
        status = candidate_status
        if candidate_status == 200:
            chosen_url = candidate_url
            chosen_via = attempt_name
            break

    return {
        "player_key": player_key,
        "year": year,
        "profile_url": chosen_url or canonical_url or raw_profile_url,
        "cache_path": str(cache_path),
        "status_code": status,
        "resolved_via": chosen_via,
    }


def run_for_year(year: int) -> pd.DataFrame:
    input_csv = OUTPUTS_ROOT / f"transfers_247_enriched_{year}.csv"
    if not input_csv.exists():
        raise FileNotFoundError(f"Missing input CSV: {input_csv}")

    cache_root = CACHE_BASE_ROOT / str(year)
    profile_cache = cache_root / "profiles"
    profile_cache.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_csv)
    rows = df[["player_key", "full_name", "player_profile_url"]].to_dict("records")
    for row in rows:
        row["year"] = year

    session = requests.Session()
    session.headers.update(get_247_page_headers())

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(cache_one_profile, session, row) for row in rows]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if index % 50 == 0 or index == len(futures):
                print(f"[{year}] Cached transfer profiles: {index}/{len(futures)}", flush=True)

    result_df = pd.DataFrame(results)
    summary_csv = cache_root / f"transfer_profile_cache_summary_{year}.csv"
    result_df.to_csv(summary_csv, index=False)
    print(f"Wrote {summary_csv}: {result_df.shape}")
    return result_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    run_for_year(args.year)
