# CollegeBasketballData Lineup Pulls

This folder contains a rate-limit-aware puller for CollegeBasketballData lineup stats.

## API Key

Do not hard-code the API key. Export it in your shell:

```bash
export CBBD_API_KEY="your_key_here"
```

The API uses Bearer authentication.

## Availability And Request Estimate

The free tier is 1,000 requests per calendar month. A full 2010-2026 pull using `/teams` plus `/lineups/team` is roughly:

```text
17 team-list calls + about 300 lineup calls per season = about 5,100+ requests
```

That is over the free monthly limit. Use `--dry-run` first and pull in batches.

CollegeBasketballData public notes indicate lineup/substitution data starts with the 2023-24 season. In this API's season convention, that is usually `2024`. The puller therefore skips lineup calls before `2024` by default so it does not burn requests on known-empty seasons.

## Typical Commands

Dry-run a small plan:

```bash
python3 pull_cbb_lineups.py --start-season 2010 --end-season 2026 --dry-run
```

Pull with a conservative request budget:

```bash
python3 pull_cbb_lineups.py --start-season 2010 --end-season 2026 --max-requests 950 --min-delay 1.25
```

Resume later:

```bash
python3 pull_cbb_lineups.py --start-season 2024 --end-season 2026 --max-requests 950
```

Test only a few teams:

```bash
python3 pull_cbb_lineups.py --start-season 2024 --end-season 2024 --team-limit 5 --max-requests 10
```

Force a pre-2024 probe only if you intentionally want to test availability:

```bash
python3 pull_cbb_lineups.py --start-season 2010 --end-season 2010 --allow-pre-availability --team-limit 5 --max-requests 10
```

If the first `5` teams in a season return empty lineup responses, the script skips the rest of that season. Change that threshold with:

```bash
python3 pull_cbb_lineups.py --empty-season-probe-limit 3
```

## Outputs

The script writes:

- `raw/teams_{season}.json`
- `raw/lineups_{season}_{team_slug}.json`
- `outputs/cbb_lineups_all.csv`
- `outputs/cbb_lineups_all.duckdb`
- `state/lineup_pull_state.json`
- `logs/request_log.jsonl`

The script resumes from existing raw files and state, so it does not re-request completed team-season combinations unless `--force` is passed.
