#!/usr/bin/env python3
"""
Rate-limit-aware CollegeBasketballData lineup puller.

Reads the API key from CBBD_API_KEY and avoids duplicate requests by caching
raw responses and maintaining a completion state file.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_URL = "https://api.collegebasketballdata.com"
DEFAULT_START_SEASON = 2010
DEFAULT_END_SEASON = 2026
DEFAULT_MIN_LINEUP_SEASON = 2024


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "unknown"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            label = f"{prefix}_{key}" if prefix else str(key)
            out.update(flatten(value, label))
    elif isinstance(obj, list):
        if all(not isinstance(item, (dict, list)) for item in obj):
            out[prefix] = json.dumps(obj, ensure_ascii=False)
        else:
            for idx, value in enumerate(obj):
                label = f"{prefix}_{idx}" if prefix else str(idx)
                out.update(flatten(value, label))
    else:
        out[prefix] = obj
    return out


def normalize_rows(rows: Any, season: int, requested_team: str) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if isinstance(rows, dict):
        # Some APIs wrap arrays in keys such as data/items/results.
        for key in ("data", "items", "results", "lineups"):
            if isinstance(rows.get(key), list):
                rows = rows[key]
                break
        else:
            rows = [rows]
    if not isinstance(rows, list):
        return []

    normalized: list[dict[str, Any]] = []
    for row in rows:
        flat = flatten(row)
        flat["pull_season"] = season
        flat["requested_team"] = requested_team
        normalized.append(flat)
    return normalized


class CbbdClient:
    def __init__(
        self,
        api_key: str,
        log_path: Path,
        max_requests: int,
        min_delay: float,
        timeout: int,
    ) -> None:
        self.api_key = api_key
        self.log_path = log_path
        self.max_requests = max_requests
        self.min_delay = min_delay
        self.timeout = timeout
        self.requests_made = 0
        self.last_request_at = 0.0
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(self, payload: dict[str, Any]) -> None:
        payload = {"timestamp": now_iso(), **payload}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")

    def get_json(self, path: str, params: dict[str, Any]) -> Any:
        if self.requests_made >= self.max_requests:
            raise RuntimeError(
                f"Request budget exhausted: {self.requests_made}/{self.max_requests}"
            )

        clean_params = {
            key: value
            for key, value in params.items()
            if value is not None and str(value).strip() != ""
        }
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(clean_params)}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "uiuc-proj-cbb-lineup-puller/1.0",
        }

        attempts = 0
        while True:
            attempts += 1
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.min_delay:
                time.sleep(self.min_delay - elapsed)

            request = urllib.request.Request(url, headers=headers, method="GET")
            self.requests_made += 1
            self.last_request_at = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                    self._log(
                        {
                            "url": url,
                            "status": response.status,
                            "attempt": attempts,
                            "request_number": self.requests_made,
                        }
                    )
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                self._log(
                    {
                        "url": url,
                        "status": exc.code,
                        "attempt": attempts,
                        "request_number": self.requests_made,
                        "error": body[:500],
                    }
                )
                if exc.code == 429 and attempts <= 5:
                    retry_after = exc.headers.get("Retry-After")
                    sleep_seconds = float(retry_after) if retry_after else 60.0 * attempts
                    time.sleep(sleep_seconds)
                    continue
                if 500 <= exc.code < 600 and attempts <= 4:
                    time.sleep(min(60.0, 2.0**attempts))
                    continue
                raise
            except urllib.error.URLError as exc:
                self._log(
                    {
                        "url": url,
                        "status": "url_error",
                        "attempt": attempts,
                        "request_number": self.requests_made,
                        "error": str(exc),
                    }
                )
                if attempts <= 4:
                    time.sleep(min(60.0, 2.0**attempts))
                    continue
                raise


def extract_team_names(payload: Any) -> list[str]:
    rows = payload
    if isinstance(payload, dict):
        for key in ("data", "items", "results", "teams"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    if not isinstance(rows, list):
        return []

    names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("school") or row.get("team") or row.get("name")
        if name is not None and str(name).strip():
            names.append(str(name).strip())
    return sorted(set(names))


def append_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_fields: list[str] = []
    existing_rows: list[dict[str, Any]] = []

    if path.exists() and path.stat().st_size > 0:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing_fields = list(reader.fieldnames or [])
            existing_rows = list(reader)

    fields = list(existing_fields)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in existing_rows:
            writer.writerow(row)
        for row in rows:
            writer.writerow(row)


def write_duckdb(csv_path: Path, db_path: Path) -> None:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return
    try:
        import duckdb
    except ImportError:
        return
    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP TABLE IF EXISTS cbb_lineups_all")
        con.execute(
            """
            CREATE TABLE cbb_lineups_all AS
            SELECT *
            FROM read_csv(
                ?,
                header=true,
                all_varchar=true,
                delim=',',
                quote='"',
                escape='"',
                strict_mode=false,
                null_padding=true
            )
            """,
            [str(csv_path)],
        )
    finally:
        con.close()


def build_plan(
    seasons: list[int],
    teams_by_season: dict[int, list[str]],
    completed: set[str],
    team_limit: int | None,
) -> list[tuple[int, str]]:
    plan: list[tuple[int, str]] = []
    for season in seasons:
        teams = teams_by_season.get(season, [])
        if team_limit is not None:
            teams = teams[:team_limit]
        for team in teams:
            key = f"{season}||{team}"
            if key not in completed:
                plan.append((season, team))
    return plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=DEFAULT_START_SEASON)
    parser.add_argument("--end-season", type=int, default=DEFAULT_END_SEASON)
    parser.add_argument(
        "--min-lineup-season",
        type=int,
        default=DEFAULT_MIN_LINEUP_SEASON,
        help="Oldest season to request from /lineups/team. Default is 2024 because public CBBD notes lineup data starts with 2023-24.",
    )
    parser.add_argument(
        "--allow-pre-availability",
        action="store_true",
        help="Allow lineup requests before --min-lineup-season. Off by default to avoid known-empty calls.",
    )
    parser.add_argument(
        "--empty-season-probe-limit",
        type=int,
        default=5,
        help="If the first N lineup responses in a season are empty, skip the rest of that season.",
    )
    parser.add_argument(
        "--estimate-teams-per-season",
        type=int,
        default=300,
        help="Dry-run estimate used when a season's team list is not cached yet.",
    )
    parser.add_argument("--max-requests", type=int, default=950)
    parser.add_argument("--min-delay", type=float, default=1.25)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--team-limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--refresh-teams", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parent)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.output_root
    raw_dir = root / "raw"
    out_dir = root / "outputs"
    state_dir = root / "state"
    log_dir = root / "logs"
    state_path = state_dir / "lineup_pull_state.json"
    csv_path = out_dir / "cbb_lineups_all.csv"
    db_path = out_dir / "cbb_lineups_all.duckdb"

    requested_seasons = list(range(args.start_season, args.end_season + 1))
    if args.allow_pre_availability:
        seasons = requested_seasons
        skipped_known_empty: list[int] = []
    else:
        skipped_known_empty = [s for s in requested_seasons if s < args.min_lineup_season]
        seasons = [s for s in requested_seasons if s >= args.min_lineup_season]
    if not seasons:
        print(
            "No seasons to pull after applying availability floor. "
            f"Use --allow-pre-availability to request seasons before {args.min_lineup_season}."
        )
        return 0
    state = load_json(
        state_path,
        {
            "completed_lineup_requests": [],
            "empty_lineup_requests": [],
            "failed_lineup_requests": [],
            "skipped_known_empty_seasons": [],
            "skipped_empty_probe_seasons": [],
            "team_counts": {},
        },
    )
    state["skipped_known_empty_seasons"] = sorted(
        set(state.get("skipped_known_empty_seasons", [])) | set(skipped_known_empty)
    )
    completed = set() if args.force else set(state.get("completed_lineup_requests", []))

    api_key = os.environ.get("CBBD_API_KEY", "").strip()
    client = None
    if not args.dry_run:
        if not api_key:
            print("Missing CBBD_API_KEY environment variable.", file=sys.stderr)
            return 2
        client = CbbdClient(
            api_key=api_key,
            log_path=log_dir / "request_log.jsonl",
            max_requests=args.max_requests,
            min_delay=args.min_delay,
            timeout=args.timeout,
        )

    teams_by_season: dict[int, list[str]] = {}
    team_calls_needed = 0
    for season in seasons:
        teams_path = raw_dir / f"teams_{season}.json"
        if teams_path.exists() and not args.refresh_teams:
            payload = load_json(teams_path, [])
        elif args.dry_run:
            payload = []
            team_calls_needed += 1
        else:
            assert client is not None
            payload = client.get_json("/teams", {"season": season})
            write_json(teams_path, payload)
        teams = extract_team_names(payload)
        teams_by_season[season] = teams
        if teams or not args.dry_run:
            state.setdefault("team_counts", {})[str(season)] = len(teams)

    plan = build_plan(seasons, teams_by_season, completed, args.team_limit)
    estimated_team_calls = team_calls_needed
    if args.dry_run:
        estimated_lineup_calls = 0
        for season in seasons:
            teams = teams_by_season.get(season, [])
            if teams:
                estimated_lineup_calls += min(len(teams), args.team_limit or len(teams))
            else:
                estimated_lineup_calls += min(
                    args.estimate_teams_per_season,
                    args.team_limit or args.estimate_teams_per_season,
                )
    else:
        estimated_lineup_calls = len(plan)
    estimated_total_calls = estimated_team_calls + estimated_lineup_calls

    print("Requested seasons:", requested_seasons[0], "through", requested_seasons[-1])
    print("Lineup seasons to pull:", seasons[0], "through", seasons[-1])
    if skipped_known_empty:
        print(
            "Skipped known-empty pre-lineup seasons without API calls:",
            f"{skipped_known_empty[0]} through {skipped_known_empty[-1]}",
        )
    print("Known team counts:", state.get("team_counts", {}))
    if args.dry_run:
        print("Estimated lineup requests:", estimated_lineup_calls)
    else:
        print("Lineup requests remaining:", len(plan))
    print("Estimated uncached calls this run:", estimated_total_calls)
    print("Request budget:", args.max_requests)

    if args.dry_run:
        print("Dry run only. No API calls made.")
        write_json(state_path, state)
        return 0

    all_new_rows: list[dict[str, Any]] = []
    completed_list = set(state.get("completed_lineup_requests", []))
    empty_list = set(state.get("empty_lineup_requests", []))
    failed_list = set(state.get("failed_lineup_requests", []))
    skipped_empty_probe_seasons = set(state.get("skipped_empty_probe_seasons", []))
    empty_probe_counts: dict[int, int] = {}
    seen_nonempty_seasons: set[int] = set()

    assert client is not None
    for season, team in plan:
        if season in skipped_empty_probe_seasons:
            continue
        request_key = f"{season}||{team}"
        raw_path = raw_dir / f"lineups_{season}_{slugify(team)}.json"
        try:
            if raw_path.exists() and not args.force:
                payload = load_json(raw_path, None)
            else:
                payload = client.get_json("/lineups/team", {"season": season, "team": team})
                write_json(raw_path, payload)
            rows = normalize_rows(payload, season=season, requested_team=team)
            if rows:
                all_new_rows.extend(rows)
                seen_nonempty_seasons.add(season)
            else:
                empty_list.add(request_key)
                if season not in seen_nonempty_seasons:
                    empty_probe_counts[season] = empty_probe_counts.get(season, 0) + 1
                    if empty_probe_counts[season] >= args.empty_season_probe_limit:
                        skipped_empty_probe_seasons.add(season)
                        state["skipped_empty_probe_seasons"] = sorted(skipped_empty_probe_seasons)
                        state["last_empty_probe_skip"] = {
                            "season": season,
                            "empty_probe_limit": args.empty_season_probe_limit,
                            "time": now_iso(),
                        }
                        write_json(state_path, state)
                        print(
                            f"Skipping remaining {season} teams after "
                            f"{args.empty_season_probe_limit} empty lineup responses."
                        )
            completed_list.add(request_key)
            failed_list.discard(request_key)
            state["completed_lineup_requests"] = sorted(completed_list)
            state["empty_lineup_requests"] = sorted(empty_list)
            state["failed_lineup_requests"] = sorted(failed_list)
            state["last_updated"] = now_iso()
            write_json(state_path, state)
            if all_new_rows:
                append_rows_csv(csv_path, all_new_rows)
                all_new_rows = []
                write_duckdb(csv_path, db_path)
        except Exception as exc:
            failed_list.add(request_key)
            state["failed_lineup_requests"] = sorted(failed_list)
            state["last_error"] = {"request_key": request_key, "error": str(exc), "time": now_iso()}
            write_json(state_path, state)
            print(f"Failed {request_key}: {exc}", file=sys.stderr)
            if "Request budget exhausted" in str(exc):
                break

    if all_new_rows:
        append_rows_csv(csv_path, all_new_rows)
    write_duckdb(csv_path, db_path)
    print("Requests made this process:", client.requests_made)
    print("Completed lineup requests total:", len(completed_list))
    print("Empty lineup requests total:", len(empty_list))
    print("Failed lineup requests total:", len(failed_list))
    print("CSV:", csv_path)
    print("DuckDB:", db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
