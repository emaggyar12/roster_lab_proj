# Codex Work Context

This file records the data-building decisions and validation results that matter for future matching work. It is intentionally written as process documentation rather than a code dump.

## Current Canonical Data Files

- `data_dir/hs_complete.db`
  - Canonical cleaned 247 HS recruit file.
  - Main table: `hs_complete`.
  - Current row count after JUCO/duplicate cleanup and 2009 append: 13,740.
  - Contains one row per retained HS recruit after removing confirmed JUCO rows and moving old duplicate HS rows out of the active table.
- `data_dir/bvt_allyears_MAX.db`
  - Canonical BartTorvik all-years player stats file.
  - Main table: `bvt_allyears_MAX`.
  - Current row count: 81,562.
  - `barttorvik_trid` is an alias of BartTorvik `pid` in this file.
- `data_dir/bv_trans_compl_MAX.db`
  - Canonical BartTorvik transfer file.
  - Main table: `bv_trans_compl_MAX`.
  - Current row count: 16,897.
  - Non-null transfer `barttorvik_trid` values were validated to all exist as `pid` values in `bvt_allyears_MAX.db`.

## 247 HS Recruit Pipeline

- The HS recruit scrape starts from the 247 `recruits` API endpoint at `https://ipa.247sports.com/rdb/v1/recruits` with `sportKey=2` for men's basketball and a recruiting class year.
- That API provides player identity, class, rank/rating, position, hometown, and committed/signed/current school fields. It does not expose DOB in the cached recruit JSON checked so far.
- Height, weight, scouting report text, scouting-report evaluator, and skill ratings come from the player's 247 profile HTML/cache, not the recruit-list API payload.
- Some older 247 profile URLs require a `college-XXXXX` suffix. The scraper first tries the API profile URL, then uses search fallback when the base URL does not contain height/weight.
- JUCO rows were removed from the active HS table only when the profile page indicated a definite JUCO page using the specific JUCO details block/class, not merely because the word JUCO appeared somewhere on the page.
- After JUCO removal, repeated HS recruits were treated as multi-school HS cases. The most recent row with the most filled information stayed in `hs_complete`; older duplicate rows were moved to an `old_hs_duplicates` table.
- The active HS table should be treated as one retained row per recruit for ML input. The duplicate/removed tables exist as audit trails.

## BartTorvik All-Years Player Pipeline

- The historical BartTorvik player-stat CSV was renamed using `pstatheaders.xlsx`.
- `year_pulled` was validated to equal `year` before being removed from the final all-years CSV.
- Height and DOB handling were protected during CSV generation because spreadsheet applications can silently convert height-like strings into dates.
- `bvt_allyears_MAX.db` extends the original stat data with BartTorvik identity and source columns such as `barttorvik_trid`, `player_class`, `player_height`, `player_birth_date`, `player_hometown`, player/team/source URLs, and build notes.
- In the all-years MAX file, `barttorvik_trid` and `pid` are the same identifier.

## BartTorvik Transfer Pipeline

- BartTorvik transfer year `n` describes movement before season `n + 1`. Example: transfer cycle 2018 maps into the 2019 season context.
- The plain 2026 transfer request was rejected because it duplicated the current 2026-27 transfer set but with less information and bad orientation behavior. The canonical 2026 transfer rows come from the `trans_current_2026_27` request and are stored as `barttorvik_year = 2026`.
- The final cleaned transfer DB removed the bad plain-2026 rows and retained the current 2026-27 rows as 2026. Validation confirmed the row count dropped by exactly the size of the discarded duplicate request when that cleanup was performed.
- Transfer direction definition:
  - `raw_team_1` means origination / old team.
  - `raw_team_2` means destination / new team.
  - This definition applies to the current canonical transfer MAX DB, including the 2026 current rows.
- Transfer team URL year logic:
  - old team URL uses the transfer cycle year.
  - new team URL uses transfer cycle year + 1.
  - Player-stat URLs use the season context relevant to the player/team row, not a team URL pattern.
- The transfer MAX file still has null `barttorvik_trid` rows. A temporary synthetic-ID experiment for perfect transfer chains was undone because those null transfers first need to be checked against all-years `pid` candidates before inventing new IDs.

## Prompt Log

### 2026-05-31 16:16:44 CDT

Prompt summary:

- Explore whether 247 has DOB or other useful matching fields available through the same general data sources used by the HS scraper.
- If DOB is available, add it to `data_dir/hs_complete.db` without removing or altering existing columns.
- Start this documentation file and keep adding timestamped prompt/result summaries going forward.

Result:

- The cached 247 recruit-list API JSON did not expose DOB fields.
- DOB was found in profile-page JSON-LD as `birthDate` for a subset of cached 247 profile HTML files.
- Added new columns only to `data_dir/hs_complete.db`: `dob_247`, `dob_247_raw`, and `dob_247_source_profile_file`.
- Backed up the DB before editing as `data_dir/hs_complete.backup_before_247_dob_20260531_161644.db`.
- Validation:
  - `hs_complete` row count stayed 13,814 before and after.
  - 1,745 unique cached `year/player_key` DOB records were found.
  - 1,640 rows in `hs_complete` matched those cached DOB records.
  - No conflicting DOB values were found for the same `year/player_key`.
- Updated `scrapers_web/247_scrapers/common_247.py` and `scrapers_web/247_scrapers/scrape_247_hs.py` so future HS scrapes retain `dob_247` from profile JSON-LD.
- Also corrected the moved-path constants in `scrape_247_hs.py` so the script points at `scrapers_web/cache/hs`, `scrapers_web/outputs`, and `scrapers_web/247_scrapers/missing_data`.

### 2026-05-31 21:03:17 CDT

Prompt summary:

- Implement high-confidence matching from `data_dir/hs_complete.db` to `data_dir/bvt_allyears_MAX.db` in `data_dir/data_cleaning/hs_allyears_match.py`.
- Match using HS `full_name`, HS class year mapped to BartTorvik season `year + 1`, and HS `signed_school` against BartTorvik `player_name`, `year`, and `team`.
- Use DOB only as extra identity evidence when available. Do not require DOB for otherwise strong matches.
- Do not match 2026 HS recruits because they have not reached college yet.
- Do not edit any DB files; only write CSV outputs.

Result:

- Implemented a non-mutating matcher that reads the two canonical DB files and writes:
  - `data_dir/data_cleaning/hs_bv_match.csv`
  - `data_dir/data_cleaning/hs_bv_unmatched.csv`
- The matcher uses only the earliest BartTorvik row per `pid`, because the modeling target is performance straight out of high school.
- The hard year rule is `BartTorvik year = HS class year + 1`.
- HS class `2026` rows are retained in the left-join output but marked `ineligible_future_recruit`; none are matched.
- The matcher uses conservative fuzzy scoring with exact hard year constraint, normalized team/name strings, DOB rejection on conflicting DOBs, and a DOB-rescue tier for high-confidence DOB-supported cases.
- Added a one-to-one validation step so the same BartTorvik earliest row cannot be assigned to multiple HS rows; 4 duplicate BV assignments were dropped to `unmatched_duplicate_bv_conflict`.
- Validation from the final run:
  - Output rows: 13,814.
  - Matched rows: 4,974.
  - Unmatched/ineligible rows: 8,840.
  - 2026 matched rows: 0.
  - Hard year violations: 0.
  - Duplicate BartTorvik `pid` assignments: 0.
  - Match tiers: 4,966 `strict_name_team`, 8 `dob_rescue`, 631 `ineligible_future_recruit`, 4 `unmatched_duplicate_bv_conflict`, and 8,205 regular unmatched.

### 2026-05-31 21:06:55 CDT

Prompt summary:

- Shrink `data_dir/data_cleaning/hs_bv_match.csv` so it only contains the small set of human-review columns: 247 name, 247 signed team, 247 year, BartTorvik year, BartTorvik player name, and BartTorvik team.

Result:

- Rewrote `data_dir/data_cleaning/hs_bv_match.csv` in place with only:
  - `hs_year`
  - `hs_full_name`
  - `hs_signed_school`
  - `bv_player_name`
  - `bv_team`
  - `bv_year`
- Row count stayed 13,814.
- Non-null BartTorvik player names stayed 4,974, matching the previous matched-row count.
- `hs_bv_unmatched.csv` was not modified.

### 2026-05-31 21:25:48 CDT

Prompt summary:

- Resolve a 247 matching gap where some recruits do not have `signed_school` or `committed_school` in the API row but their recruiting-profile page shows an `Enrolled` institution.
- Example: Johni Broome has no signed/committed school in the API row but his recruiting profile shows he enrolled at Morehead State.
- Add only new DB columns to `data_dir/hs_complete.db`: the recruiting-profile URL and the enrolled institution.
- Keep recruiting-profile HTML cache separate from the existing main-profile cache.

Result:

- Added a repeatable enrichment script at `data_dir/data_cleaning/enrich_247_enrolled_institution.py`.
- Backed up the DB before editing as `data_dir/backups/hs_complete.backup_before_enrolled_institution_20260531_212548.db`.
- Cached recruiting-profile pages separately under `scrapers_web/cache/hs_recruiting_profiles`.
- Added exactly two new columns to `data_dir/hs_complete.db`:
  - `recruiting_profile_url_247`
  - `enrolled_institution_247`
- Validation:
  - Row count stayed 13,814.
  - Column count increased from 57 to 59.
  - Recruiting-profile URLs found: 10,766.
  - Enrolled institutions found: 8,064.
  - Rows with missing `signed_school` but non-null `enrolled_institution_247`: 3,135.
  - Johni Broome now has `recruiting_profile_url_247 = https://247sports.com/player/johni-broome-46085384/high-school-237032` and `enrolled_institution_247 = Morehead State`.

### 2026-05-31 22:09:49 CDT

Prompt summary:

- Rematch the HS recruits against BartTorvik using the same name/year/school matching logic, but use `enrolled_institution_247` as the school fallback when `signed_school` is missing.
- Add any newly matched recruits to the concise `data_dir/data_cleaning/hs_bv_match.csv`.
- Keep `hs_bv_match.csv` columns concise and unchanged.

Result:

- Updated `data_dir/data_cleaning/hs_allyears_match.py` so the school used for matching is `signed_school` first, falling back to `enrolled_institution_247` when signed school is blank.
- The matcher now writes the concise six-column `hs_bv_match.csv` directly:
  - `hs_year`
  - `hs_full_name`
  - `hs_signed_school`
  - `bv_player_name`
  - `bv_team`
  - `bv_year`
- Reran the matcher without editing any DB files.
- Validation:
  - `hs_bv_match.csv` row count stayed 13,814.
  - Non-null BartTorvik matches increased from 4,974 to 7,060.
  - Newly added matches: 2,086.
  - `hs_bv_unmatched.csv` decreased to 6,754 rows.
  - 2026 matched rows stayed 0.
  - Johni Broome now matches to `Johni Broome`, `Morehead St.`, BartTorvik year 2021.

### 2026-05-31 22:24:10 CDT

Prompt summary:

- Run a looser manual-review fuzzy pass on the remaining unmatched recruits.
- Do not add these candidates to `hs_bv_match.csv`.
- Only hard constraint: `BartTorvik year = HS year + 1`.
- Candidate threshold: at least 80 for name similarity and at least 80 for school/team similarity.
- Write candidates to `data_dir/data_cleaning/name_team_manualreview.csv`.

Result:

- Added a repeatable manual-review script at `data_dir/data_cleaning/build_name_team_manualreview.py`.
- Wrote `data_dir/data_cleaning/name_team_manualreview.csv`.
- No DB files were edited.

### 2026-06-02 21:45:00 CDT

Prompt summary:

- Create `data_dir/hs_bv_matched.db` containing matched recruits only.
- Each row must include the full source row from `data_dir/hs_complete.db` and the full source row from `data_dir/bvt_allyears_MAX.db`.
- Use `data_dir/data_cleaning/hs_bv_match.csv` only as the match map, since that CSV is intentionally concise and does not contain the full payload.

Result:

- Added repeatable builder script:
  - `data_dir/data_cleaning/build_hs_bv_matched_db.py`
- Created:
  - `data_dir/hs_bv_matched.db`
- Tables in the new DB:
  - `hs_bv_matched`
  - `hs_bv_matched_validation`
- Validation:
  - output rows: 7,900.
  - non-null `hs_full_name`: 7,900.
  - non-null `bv_player_name`: 7,900.
  - distinct `hs_player_key`: 7,900.
  - distinct `bv_pid`: 7,897.
  - column count: 136.
- The three repeated BartTorvik `pid` values came from the current match map, not from row multiplication during DB creation:
  - `51100`: `Ladarius Brewer` / `Ledarrius Brewer` -> `Ledarrius Brewer`.
  - `71118`: `Jalen Thomas` / `Josh Townley-Thomas` -> `Jalen Thomas`.
  - `32107`: `Isaac Thornton` / `Isaac Thorton` -> `Isaac Thornton`.
- Source DB files were read-only and were not edited.
- `hs_bv_match.csv` was not changed by this step; it remains concise with 13,814 rows and 7,060 non-null BartTorvik matches.
- Validation:
  - Candidate rows: 672.
  - Unique HS recruits represented: 660.
  - Minimum `name_score`: 80.0.
  - Minimum `team_score`: 80.0.
  - 2026 candidate rows: 0.
  - Hard year violations: 0.
  - Manual-review school source counts: 549 from `enrolled_institution_247`, 123 from `signed_school_fallback`.

### 2026-06-01 21:20:15 CDT

Prompt summary:

- Consume `match_flag` values added by the user in `name_team_manualreview.csv`.
- Rows with `match_flag = true` should be promoted to confirmed matches and removed from manual review.
- Rebuild matching around a new 247-side `signed_or_enrolled` field: `signed_school` first, falling back to `enrolled_institution_247`.
- Remove the hard year constraint to handle redshirt cases such as Dajuan Harris, while still excluding 2026 recruits.
- Use 90% confidence for name and team fuzzy matching.
- Do not edit any DB files.

Result:

- Added `data_dir/data_cleaning/rebuild_hs_bv_matches_signed_or_enrolled.py`.
- The script reads `hs_complete.db` and `bvt_allyears_MAX.db` read-only and writes only CSV outputs.
- It uses unique normalized BartTorvik team names as a blocking step, then expands back to the original BartTorvik rows for that team so player and team still come from the same source row.
- Final CSV state after the run:
  - `hs_bv_match.csv`: 13,814 rows, 8,370 non-null BartTorvik matches.
  - `hs_bv_unmatched.csv`: 5,444 rows.
  - `name_team_manualreview.csv`: 364 remaining rows, 0 remaining true flags.
  - 2026 matched rows: 0.
  - Dajuan Harris now matches to Kansas, BartTorvik year 2021.
- Important caveat: `name_team_manualreview.csv` initially had 167 true flags, but only 96 resolved into one-to-one source DB matches during this run. The script was then patched so future runs only remove true-flag rows that actually resolve; unresolved true flags would remain in manual review. No DB files were edited.

### 2026-06-01 21:56:29 CDT

Prompt summary:

- Examine the remaining unmatched HS recruits against unused/unmatched BartTorvik all-years player rows.
- Use judgment-heavy matching to identify likely matches and update the manual-review CSV accordingly.
- Do not edit any DB files.

Result:

- Added `data_dir/data_cleaning/assistant_suggest_manual_matches.py`.
- Created a safety copy of the previous manual review file:
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_assistant_suggestions_20260601_215629.csv`
- The script reads `hs_bv_unmatched.csv`, `hs_bv_match.csv`, and `bvt_allyears_MAX.db` read-only.
- It only considers unused BartTorvik earliest-player rows that are not already present in confirmed matches.
- Matching logic uses the available basketball identity evidence:
  - normalized player name similarity,
  - school evidence from signed/enrolled/committed 247 fields,
  - exact DOB agreement when available,
  - plausible HS-to-college year windows, including redshirt-style delays.
- The script rewrote `data_dir/data_cleaning/name_team_manualreview.csv` with likely assistant-suggested matches marked in `match_flag`.
- Current validation:
  - `hs_bv_match.csv`: 13,814 rows, 8,314 non-null BartTorvik matches.
  - `hs_bv_unmatched.csv`: 5,500 rows.
  - `name_team_manualreview.csv`: 2,680 rows.
  - `match_flag = 1.0`: 2,315 assistant-suggested likely matches.
  - `match_flag` blank: 365 rows still left for manual review.
- No DB files were edited.

### 2026-06-01 22:22:00 CDT

Prompt summary:

- Investigate why Malique Ewin shows Florida State as signed/enrolled in the HS-to-BartTorvik matching CSVs even though his original post-HS path was JUCO/Ole Miss.
- Do not edit any CSV or DB files.

Result:

- No CSV or DB files were edited.
- Malique Ewin's `Florida State` value was already present in `hs_complete.db` and its backups before the DOB/enrolled-institution enrichment steps.
- The cached 247 API recruit rows for player key `46083137` in both 2022 and 2024 currently report:
  - `committedInstitution = Florida State`
  - `signedInstitution = Florida State`
  - `currentInstitution = Arkansas`
- The cached main 247 profile timeline shows the actual sequence:
  - Ole Miss enrolled: 2022-06-01.
  - South Florida transfer: 2023-06-05.
  - Florida State commit/sign/enroll: April-August 2024.
  - Arkansas transfer: 2025-04-15.
- The `enrich_247_enrolled_institution.py` fallback allowed `junior-college` and `prep` URLs as "recruiting profile" URLs. For Malique, this selected:
  - `https://247sports.com/player/malique-ewin-46083137/junior-college-313694`
  - That page's top commit/enrolled banner says Florida State, which reinforced the later JUCO/transfer destination rather than the original HS destination.
- Scope check in `hs_complete.db`:
  - 9,766 rows have a `high-school` recruiting profile URL.
  - 920 rows have a `junior-college` recruiting profile URL.
  - 78 rows have a `prep` recruiting profile URL.
  - 3,048 rows have no recruiting profile URL.
  - 998 total rows therefore use non-HS recruiting-profile URLs.
  - 504 of those have disagreement between `signed_school` and `enrolled_institution_247`.
- Current interpretation:
  - This is not random CSV corruption.
  - It is source/logic contamination from 247's current player object plus our fallback accepting non-HS profile pages.
  - The fix should treat `junior-college`/`prep` profile URLs separately, preferably by deriving original HS enrollment from timeline events around the recruit class year or by explicitly using institution-list `(HS)` links when the goal is HS matching.

### 2026-06-01 22:38:22 CDT

Prompt summary:

- Trace how `scrapers_web/outputs/actual_db_files/juco_rec.db` was made.
- Move strict JUCO rows out of the HS recruit mix if the existing JUCO DB was built with comparable logic.
- Remove those players from `data_dir/data_cleaning/name_team_manualreview.csv`, including rows where `match_flag` was true.
- Keep prep-profile rows in the HS dataset.

Result:

- Traced `juco_rec.db` to `scrapers_web/cleaning_utils/clean_hs_juco_duplicates.py`.
- The original JUCO DB was built from cached 247 HTML using confirmed JUCO evidence such as:
  - `details.is-juco`,
  - JUCO ranking labels/links,
  - `/junior-college-` profile links inside the relevant profile section,
  - and class-year agreement.
- The newly identified issue was a stricter URL-level marker in `data_dir/hs_complete.db`: rows whose `recruiting_profile_url_247` itself contains `/junior-college-`.
- Backups created:
  - `data_dir/backups/hs_complete.backup_before_strict_juco_move_20260601_223822.db`
  - `scrapers_web/outputs/actual_db_files/backups/juco_rec.backup_before_strict_juco_append_20260601_223822.db`
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_strict_juco_removal_20260601_223822.csv`
- Moved 920 strict `/junior-college-` rows from `data_dir/hs_complete.db` into `scrapers_web/outputs/actual_db_files/juco_rec.db`.
- Added those rows to both `juco_recruits` and `juco_detection_audit` with `juco_evidence = recruiting_profile_url_247_junior_college`.
- Validation:
  - `data_dir/hs_complete.db` went from 13,814 to 12,894 rows.
  - Strict `/junior-college-` rows remaining in HS: 0.
  - Prep rows remaining in HS: 78.
  - `juco_rec.db` went from 1,162 to 2,082 rows.
  - `juco_detection_audit` went from 1,162 to 2,082 rows.
  - Malique Ewin is no longer in `data_dir/hs_complete.db`.
  - Malique Ewin is now in `juco_rec.db`.
  - `name_team_manualreview.csv` went from 2,680 to 2,431 rows.
  - Manual-review rows removed for strict JUCO names: 249.
  - Removed manual-review rows with true flags: 187.

### 2026-06-01 22:47:00 CDT

Prompt summary:

- Report how many BartTorvik transfers remain unmatched/unidentified in `data_dir/bv_trans_compl_MAX.db`.
- Find where those unmatched transfers are stored.
- Do not edit any files.

Result:

- No files were edited.
- Canonical current transfer MAX DB:
  - `data_dir/bv_trans_compl_MAX.db`
  - mirrored copy with the same counts: `scrapers_web/get_bartovik_data/db_files/bv_trans_compl_MAX.db`
- Main table:
  - `bv_trans_compl_MAX`
- The current unmatched/unidentified transfer representation is `barttorvik_trid IS NULL` inside the main table, not a separate current unmatched table.
- Counts:
  - total transfer rows: 16,897.
  - non-null `barttorvik_trid`: 11,683.
  - null `barttorvik_trid`: 5,214.
  - distinct non-null `barttorvik_trid`: 8,941.
- Null `barttorvik_trid` breakdown:
  - 5,089 rows are `stats_merge_status = left_only` and `has_stats_enrichment = False`.
  - 125 rows are `stats_merge_status = both` but still have null `barttorvik_trid`; these are all 2026/current-2027 rows with limited future-season stats identity.
- Old unique-ID experiment DBs under `scrapers_web/get_bartovik_data/db_files/old_db/` contain `manual_review_cases`, but those are obsolete for current canonical work because they came from the abandoned unique-ID run and/or the older transfer orientation/2026 setup.

### 2026-06-02 21:13:45 CDT

Prompt summary:

- Move only true-flagged rows from `data_dir/data_cleaning/name_team_manualreview.csv` into `data_dir/data_cleaning/hs_bv_match.csv`.
- Remove those true rows from manual review.
- Do not touch DB files.

Result:

- Backups created:
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_true_move_20260602_211345.csv`
  - `data_dir/data_cleaning/hs_bv_match.backup_before_true_move_20260602_211345.csv`
- Moved 2,300 true-ish `match_flag` rows from manual review to `hs_bv_match.csv`.
- `name_team_manualreview.csv` went from 2,431 to 131 rows.
- True-ish `match_flag` rows remaining in manual review: 0.
- `hs_bv_match.csv` went from 13,814 to 16,114 rows.
- Rows in `hs_bv_match.csv` with non-null `bv_player_name`/`bv_team`: 10,614.
- No DB files were edited.

### 2026-06-02 21:19:00 CDT

Prompt summary:

- Correct the prior manual-review move.
- Only rows where `match_flag` is the literal word `TRUE` should move to `hs_bv_match.csv`.
- Numeric `1` / `1.0` rows should stay in `name_team_manualreview.csv`.
- Do not edit DB files.

Result:

- First restored the previous mistaken move from backups:
  - `name_team_manualreview.csv` returned to 2,431 rows.
  - `hs_bv_match.csv` returned to 13,814 rows.
- Backups created before the corrected TRUE-only move:
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_TRUE_only_move_20260602_211900.csv`
  - `data_dir/data_cleaning/hs_bv_match.backup_before_TRUE_only_move_20260602_211900.csv`
- Moved only literal `TRUE` rows:
  - TRUE rows moved: 110.
  - `name_team_manualreview.csv` went from 2,431 to 2,321 rows.
  - literal `TRUE` rows remaining in manual review: 0.
  - numeric `1` / `1.0` rows remaining in manual review: 2,190.
  - `hs_bv_match.csv` went from 13,814 to 13,924 rows.
  - rows with non-null `bv_player_name`: 8,424.
- No DB files were edited.

### 2026-06-02 21:26:06 CDT

Prompt summary:

- Correct the HS match CSV shape after the TRUE-only move.
- `hs_bv_match.csv` should not grow beyond the recruit universe.
- Remove JUCO rows from `hs_bv_match.csv` so it reflects the current `data_dir/hs_complete.db` size of 12,894 rows.
- Mark TRUE manual rows as matches by filling existing recruit rows, not appending new rows.
- Do not edit DB files.

Result:

- Backups created before rebuilding:
  - `data_dir/data_cleaning/hs_bv_match.backup_before_rebuild_12894_retry_20260602_212606.csv`
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_rebuild_12894_retry_20260602_212606.csv`
- Rebuilt `hs_bv_match.csv` from the current `data_dir/hs_complete.db` HS universe.
- Final validation:
  - `hs_bv_match.csv` rows: 12,894.
  - `name_team_manualreview.csv` rows: 2,321.
  - literal `TRUE` rows remaining in manual review: 0.
  - numeric `1` / `1.0` rows remaining in manual review: 2,190.
  - literal TRUE manual rows available from the pre-move backup: 110.
  - literal TRUE rows applied as updates to existing HS rows: 110.
  - literal TRUE rows missing a current HS row: 0.
  - rows with non-null `bv_player_name`: 7,900.
  - matched rows missing `bv_year`: 0.
- No DB files were edited.

### 2026-06-02 21:55:49 CDT

Prompt summary:

- Add `hs_height_in` to `data_dir/hs_bv_matched.db`, derived from existing `hs_height`.
- Add `height_in` to `data_dir/hs_complete.db`, derived from existing `height`.
- Store backups in `data_dir/backups`.
- Do not touch any other columns or data rows.
- Continue documenting every prompt in this file using the existing summary structure.

Result:

- The `.db` files were confirmed to be DuckDB databases, not SQLite databases.
- Backups created before editing:
  - `data_dir/backups/hs_bv_matched.backup_before_height_inches_20260602.db`
  - `data_dir/backups/hs_complete.backup_before_height_inches_20260602.db`
- Added and populated:
  - `data_dir/hs_bv_matched.db`, table `hs_bv_matched`, new integer column `hs_height_in`.
  - `data_dir/hs_complete.db`, table `hs_complete`, new integer column `height_in`.
- Height parsing converts feet-inches strings such as `6-10` and `'6-5` into total inches. Non-height placeholders such as `-` remain null in the new columns.
- Validation:
  - `hs_bv_matched` row count stayed 7,900.
  - `hs_bv_matched` column count increased from 136 to 137.
  - `hs_height_in` non-null rows: 7,797.
  - `hs_bv_matched_validation` row count stayed 6 and its data matched the backup exactly.
  - `hs_complete` row count stayed 12,894.
  - `hs_complete` column count increased from 59 to 60.
  - `height_in` non-null rows: 12,743.
  - `scouting_report_evaluator_parse` row count stayed 1,077 and its data matched the backup exactly.
  - Comparing current DBs to their backups while excluding only the newly added columns showed zero differences in all pre-existing columns.

### 2026-06-02 22:11:25 CDT

Prompt summary:

- Review `models_dir/catboost_trials.py`, a basic CatBoost/Optuna model intended to predict college `bv_role` playtype probabilities from high-school recruit numerical and categorical features.
- Identify drastic modeling or implementation mistakes.
- Explain how the 2024/2025 test dataframe should be used and whether Optuna requires a test dataframe.
- Do not directly edit model logic; only insert comments if useful.
- Continue documenting each prompt in this file.

Result:

- Reviewed `models_dir/catboost_trials.py` and inspected `data_dir/hs_bv_matched.db`.
- Added review-only comments to `models_dir/catboost_trials.py`; no executable model logic was changed.
- Key finding: the script currently splits on `df["year"]`, but `hs_bv_matched` has `hs_year` and `bv_year`, not `year`, so the script should fail before training until that is corrected.
- Data inspection:
  - `hs_bv_matched` rows: 7,900.
  - Target column `bv_role` exists.
  - `bv_role` has 8 non-null classes plus 5 null rows.
  - `hs_height_in` non-null rows: 7,797.
  - `hs_stars`, `hs_rating`, `hs_national_rank`, and `hs_position_rank` are each non-null for 5,396 rows.
  - Found 8 rows where `bv_year < hs_year` and 28 rows where `bv_year > hs_year + 3`, suggesting some match-timing outliers should be filtered or reviewed before modeling.
- Guidance recorded in code comments and discussed:
  - Filter out null `bv_role` rows before training.
  - Split by `hs_year` for recruit forecasting, not by a nonexistent `year` column.
  - Optuna does not require a test dataframe; it should tune on train/validation only.
  - Keep 2024/2025 as untouched holdout data and evaluate the final selected model once, with caution that 2025/2026 labels may be current/incomplete.
  - The current script prints best parameters but does not yet refit/save a final model or evaluate the test dataframe.

### 2026-06-02 22:16:04 CDT

Prompt summary:

- Implement the final review comment in the CatBoost/Optuna playtype model.
- Specifically, after Optuna tuning, refit a final model, evaluate the held-out test dataframe once, and save the model plus class-probability column order.
- The user had renamed/fixed the model file, and requested that the code not be run.

Result:

- Found the current model script at `models_dir/catboost_baseline_trials.py`; `models_dir/catboost_trials.py` no longer existed.
- Did not run or compile the training script, per user request.
- Updated `models_dir/catboost_baseline_trials.py` to:
  - create `test_df` from `hs_year` 2024-2025.
  - use `hs_year` 2022-2023 as validation.
  - keep `hs_year` 2010-2021 as training.
  - refit a final CatBoost model on train + validation rows using `study.best_params`.
  - evaluate final model log loss once on `test_df` when non-empty.
  - save the final model to `models_dir/artifacts/catboost_baseline_playtype_model.cbm`.
  - save metadata to `models_dir/artifacts/catboost_baseline_playtype_metadata.json`, including target column, feature columns, categorical features, class order for probability outputs, best validation log loss, test log loss, best parameters, final parameters, split year ranges, and split row counts.
- Added safe JSON casting for class labels and log-loss values.

### 2026-06-02 22:29:59 CDT

Prompt summary:

- Interpret the completed CatBoost/Optuna run results:
  - best validation log loss: 1.3579014922404222.
  - test log loss: 1.3266202224846795.
  - saved model and metadata artifact paths.
- Explain what the scores mean for high-school recruit to college playtype probability prediction.

Result:

- Read `models_dir/artifacts/catboost_baseline_playtype_metadata.json`.
- Confirmed model setup:
  - target: `bv_role`.
  - features: `hs_year`, `hs_position`, `hs_height_in`, `hs_weight`, `hs_stars`, `hs_rating`, `hs_national_rank`, `hs_position_rank`.
  - class order: `C`, `Combo G`, `PF/C`, `Pure PG`, `Scoring PG`, `Stretch 4`, `Wing F`, `Wing G`.
  - train rows: 5,713 from HS years 2010-2021.
  - validation rows: 1,195 from HS years 2022-2023.
  - test rows: 987 from HS years 2024-2025.
- Interpretation:
  - Both validation and test log loss are far better than an uninformed uniform 8-class log loss of about 2.079.
  - Test log loss being slightly better than validation log loss suggests no obvious validation overfit in this run.
  - The best model is a conservative low-learning-rate, shallow-tree model: 2,256 iterations, learning rate about 0.0114, depth 4.
- Additional saved-model diagnostics on the 2024-2025 test split:
  - test accuracy: 47.0%.
  - top-2 accuracy: 72.0%.
  - average max predicted probability: 48.4%.
  - strongest recall: `C` at 86.5% and `Wing G` at 77.6%.
  - weakest recall: `Pure PG` at 0.0%, `Stretch 4` at 3.5%, and `PF/C` at 11.6%.
  - common confusions included `Scoring PG -> Combo G`, `Combo G -> Wing G`, `PF/C -> C`, and `Stretch 4` split across `Wing G`, `Wing F`, and `C`.
- Recommendation:
  - Treat the current model as a useful baseline probability model, not a final classifier.
  - Next improvements should focus on class imbalance, playtype granularity, calibration, confusion analysis, and stronger recruit/team-context features.

### 2026-06-02 22:36:40 CDT

Prompt summary:

- Explain whether CatBoost automatically ignores non-meaningful features and whether rerunning without `hs_year` is worth trying.
- Use the saved baseline CatBoost model to run inference from `models_dir/catboost_baseline_inference.py`.
- Write top-3 predicted college playtype roles for each player in the inference dataframe to `models_dir/outputs/baseline`.

Result:

- Explained that CatBoost can learn to mostly ignore weak features, but features are not literally thrown out automatically; noisy, leaky, or time-shift features can still affect splits and probability calibration.
- Recommended trying a no-year rerun as a valid ablation because `hs_year` may capture era/data-coverage effects rather than player talent.
- Replaced the inference stub at `models_dir/catboost_baseline_inference.py` with a complete reproducible inference script.
- The script now:
  - reads `data_dir/hs_complete.db` in read-only mode.
  - aliases HS columns to the exact feature names expected by the trained model.
  - loads `models_dir/artifacts/catboost_baseline_playtype_model.cbm`.
  - validates saved metadata class order against the model class order.
  - writes top-3 predicted roles/probabilities plus all class probabilities.
- Created inference output:
  - `models_dir/outputs/baseline/catboost_baseline_top3_predictions.csv`.
- Validation:
  - rows scored: 12,894.
  - output shape: 12,894 rows by 27 columns.
  - probability row sums ranged from approximately 1.0 to 1.0.
  - top predicted role counts:
    - `Wing G`: 4,413.
    - `C`: 2,858.
    - `Combo G`: 2,356.
    - `Wing F`: 1,211.
    - `Scoring PG`: 1,079.
    - `PF/C`: 877.
    - `Stretch 4`: 87.
    - `Pure PG`: 13.

### 2026-06-03 20:18:53 CDT

Prompt summary:

- Scrape and append the missing 2009 247 HS recruit class only.
- Do not scrape or modify 2010+ HS rows.
- Cache 2009 main profile HTML under `scrapers_web/cache/hs` and recruiting-profile HTML separately under `scrapers_web/cache/hs_recruiting_profiles`.
- Deposit confirmed 2009 JUCO rows into `scrapers_web/outputs/actual_db_files/juco_rec.db`.
- Append only non-JUCO 2009 HS recruits to `data_dir/hs_complete.db`.
- Store `hs_complete.db` backups in `data_dir/backups`.
- Try to capture scouting reports and skill ratings using the same style as previous 247 scrapers.
- Document the work in this file.

Result:

- Added a dedicated 2009-only append script:
  - `scrapers_web/247_scrapers/scrape_247_hs_2009_append.py`
- The script reuses the existing 247 API/profile parsing helpers and intentionally refuses to run if 2009 rows already exist in either live destination DB.
- Ran the script with network access after the first sandboxed attempt failed before any DB backup or append due to blocked DNS/network access while generating 247 request headers.
- 247 API scrape:
  - pages cached: 5.
  - raw 2009 recruit rows: 1,011.
  - duplicate `year/player_key` rows: 0.
- Main profile cache:
  - `scrapers_web/cache/hs/2009/profiles`: 1,011 cached HTML files.
  - `scrapers_web/cache/hs/2009/api`: 5 cached JSON files.
  - `scrapers_web/cache/hs/2009/resolved_urls`: not created because fallback search was not needed.
- Recruiting profile cache:
  - `scrapers_web/cache/hs_recruiting_profiles/2009`: 1,003 cached HTML files.
- 2009-only output files created:
  - `scrapers_web/outputs/hs_recruits_247_2009.db`
  - `scrapers_web/outputs/hs_recruit_dummy_2009.csv`
  - `scrapers_web/247_scrapers/missing_data/2009_missing_hw.csv`
- Backups created before live DB appends:
  - `data_dir/backups/hs_complete.backup_before_2009_append_20260603_201716.db`
  - `scrapers_web/outputs/actual_db_files/backups/juco_rec.backup_before_2009_append_20260603_201716.db`
- Appended rows:
  - 846 non-JUCO 2009 HS recruits appended to `data_dir/hs_complete.db`.
  - 165 confirmed 2009 JUCO rows appended to `scrapers_web/outputs/actual_db_files/juco_rec.db`.
  - 165 corresponding 2009 rows appended to `juco_detection_audit`.
- `data_dir/hs_complete.db` validation:
  - row count went from 12,894 to 13,740.
  - 2009 HS rows now in `hs_complete`: 846.
  - non-2009 row count stayed 12,894.
  - comparing current non-2009 rows to the pre-append backup showed zero differences in both directions.
  - duplicate `year/player_key` groups after append: 0.
  - 2009 HS height non-null rows: 846.
  - 2009 HS `height_in` non-null rows: 836.
  - 2009 HS DOB non-null rows: 70.
  - 2009 HS recruiting-profile URLs: 839.
  - 2009 HS enrolled institutions: 826.
- `juco_rec.db` validation:
  - row count went from 2,082 to 2,247.
  - 2009 JUCO rows now in `juco_recruits`: 165.
  - 2009 JUCO audit rows: 165.
  - comparing current non-2009 JUCO rows to the pre-append backup showed zero differences in both directions.
  - 2009 JUCO evidence counts:
    - 162 rows: `prospect_title_247sports_juco;ranking_link_juniorcollege;junior_college_profile_link;recruiting_profile_url_247_junior_college`.
    - 2 rows: `details.is-juco;recruiting_profile_url_247_junior_college`.
    - 1 row: `details.is-juco`.
- Scouting report and skill-rating outcome:
  - The 2009 cached profile pages contain `scouting-report` sections, but the content is the older `H.S. Athletic Background` block rather than the richer evaluation narrative used by the existing 2010-2026 extraction logic.
  - No 2009 pages contained the existing skill-rating list markup such as `section.skills`.
  - Therefore 2009 rows were appended with `has_scouting_report = False`, `scouting_report = NULL`, and `skill_rating = False`; no new `_appended` skill columns were needed.

### 2026-06-03 20:37:50 CDT

Prompt summary:

- Rerun HS-to-BartTorvik matching after the 2009 HS append.
- Only consider BartTorvik players not previously matched in `data_dir/hs_bv_matched.db`.
- For BartTorvik duplicate player-id rows, only use each player id's oldest row because the target is performance right out of high school.
- Match primarily by HS full name and signed-or-enrolled institution, using DOB as fallback/supporting evidence.
- Put potential matches in `data_dir/data_cleaning/name_team_manualreview.csv`.
- Put still-unmatched recruits in `data_dir/data_cleaning/hs_bv_unmatched.csv`.
- Append complete high-confidence rows to `data_dir/hs_bv_matched.db`; do not touch existing matched rows.

Result:

- Added repeatable second-round matcher:
  - `data_dir/data_cleaning/second_round_unused_bv_matching.py`
- The matcher reads:
  - `data_dir/hs_complete.db`
  - `data_dir/hs_bv_matched.db`
  - `data_dir/bvt_allyears_MAX.db`
- BartTorvik candidate restriction:
  - Built earliest BartTorvik row per non-null `pid`.
  - Excluded every `bv_pid` already present in `hs_bv_matched`.
  - Available unused earliest BartTorvik rows considered: 24,106.
- HS candidate universe:
  - Current HS rows: 13,740.
  - Existing matched rows before this pass: 7,900.
  - Current unmatched HS universe before this pass: 5,840.
  - 2026 recruits were retained in unmatched output but excluded from active matching.
- Backups created before writes:
  - `data_dir/backups/hs_bv_matched.backup_before_second_round_append_20260603_203551.db`
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_second_round_20260603_203551.csv`
  - `data_dir/data_cleaning/hs_bv_unmatched.backup_before_second_round_20260603_203551.csv`
- Matching results:
  - Resolved one-to-one candidates: 858.
  - High-confidence auto matches appended to `hs_bv_matched`: 686.
  - Manual-review candidates added: 172.
  - Manual-review rows now: 2,493.
  - Keyed/manual rows from this second round: 172.
  - Still-unmatched rows now: 5,154.
  - Still-unmatched 2009 HS rows: 176.
  - 2026 ineligible future recruits in unmatched output: 631.
- `data_dir/hs_bv_matched.db` validation:
  - row count increased from 7,900 to 8,586.
  - exactly 686 rows were appended.
  - pre-existing 7,900 rows compared against the backup showed zero changed or removed rows.
  - overlap between newly appended `bv_pid` values and pre-existing matched `bv_pid` values: 0.
  - duplicate `hs_year/hs_player_key` groups in matched table: 0.
  - 2009 rows now in matched table: 670.
  - `hs_bv_matched_validation` was intentionally left unchanged because the user requested append-only behavior for the match DB.
- CSV output validation:
  - `name_team_manualreview.csv`: 2,493 rows by 18 columns.
  - `hs_bv_unmatched.csv`: 5,154 rows by 147 columns, preserving the previous full unmatched output shape.
- Correction during this run:
  - The first manual-review merge collapsed old unkeyed manual-review rows because older rows did not have `hs_year/hs_player_key/bv_pid/bv_year`.
  - Restored the old manual-review CSV from backup and re-appended the 172 new keyed candidate rows.
  - Patched the script so future manual-review deduplication only deduplicates rows where all key columns are present.

### 2026-06-03 20:41:08 CDT

Prompt summary:

- Clarify how the 686 second-round high-confidence matches were defined before treating them as final.
- Investigate why 16 appended matches were not 2009 recruits.

Result:

- Confirmed that the second-round script did not restrict auto-appends to 2009 recruits.
- The script considered all currently unmatched HS recruits, excluding 2026, against unused earliest BartTorvik player ids.
- High confidence was a heuristic score, not a calibrated probability:
  - `confidence = 0.58 * name_score + 0.37 * team_score + DOB/year bonuses`.
  - `+7` for exact DOB match.
  - `+3` for `bv_year - hs_year` of 0 or 1.
  - `+1` for year gap of 2 or 3.
  - Auto append required `confidence >= 95` and an auto tier such as very strong name/team or DOB-supported matching.
- The 16 non-2009 appended rows were pulled because they were unmatched HS rows from prior passes and had unused BartTorvik pids with strong name/team evidence and plausible year gaps.
- Important interpretation:
  - The 16 non-2009 rows should be treated cautiously because the fact that prior passes did not match them is negative evidence.
  - A stricter follow-up policy would be to keep automatic appends limited to 2009, and send non-2009 second-round candidates to manual review unless they have exact DOB support and unambiguous name/team evidence.

### 2026-06-03 21:06:57 CDT

Prompt summary:

- Review the two non-baseline model implementations in `models_dir`:
  - scouting-report transformer model.
  - structured + scouting-report + skill-rating model.
- Create `artifacts`, `outputs`, and `scripts` directories for model folders that do not already have them.
- If no significant issues are found, run both models one after another and run 2026 inference into the proper output directories.
- If significant issues are found, report them immediately and do not run model training/inference.

Result:

- Created directories:
  - `models_dir/scouting_report_xfmr/artifacts`
  - `models_dir/scouting_report_xfmr/outputs`
  - `models_dir/scouting_report_xfmr/scripts`
  - `models_dir/skill_rating_xfmr/artifacts`
  - `models_dir/skill_rating_xfmr/outputs`
  - `models_dir/skill_rating_xfmr/scripts`
- Did not run model training or inference because significant code issues were found.
- Main blocker:
  - Both non-baseline scripts query `data_dir/hs_bv_matched.db`, whose columns are prefixed, e.g. `hs_scouting_report` and `hs_skill_athleticism`.
  - The scripts currently reference unprefixed names such as `scouting_report`, `skill_athleticism`, `skill_defender`, etc., so they would fail before training.
- Additional issues:
  - Neither non-baseline folder currently has a 2026 inference script.
  - If scripts are moved into the new `scripts` directories, their artifact path logic must change from `Path(__file__).resolve().parent / "artifacts"` to the model-folder artifact directory.
  - The 2026 inference source would be `data_dir/hs_complete.db`, where columns are unprefixed (`scouting_report`, `skill_athleticism`, etc.), while the training source `hs_bv_matched.db` is prefixed (`hs_scouting_report`, `hs_skill_athleticism`, etc.), so training and inference need explicit column aliasing to the same feature names.
  - Current 2026 HS rows have 135 non-empty scouting reports but 0 rows with `skill_rating = TRUE`; the combined skill/scouting model can still run, but the skill component will add no 2026-specific signal unless 2026 skill ratings are populated later.

### 2026-06-03 21:19:49 CDT

Prompt summary:

- Update the scouting-report model and skill+scouting model feature names so they match `data_dir/hs_bv_matched.db`.
- Include flags for scouting report availability, evaluator availability, and skill-rating availability.
- Add the scouting evaluator itself as a feature to the scouting-report model and include evaluator features in the combined skill+scouting model.
- Create 2026 inference scripts using the same style of identity/input columns as the baseline inference script.
- Explain that prior suggestions after item 4 were cut off.

Result:

- Replaced/corrected training scripts:
  - `models_dir/scouting_report_xfmr/scripts/catboost_scouting_rep.py`
  - `models_dir/skill_rating_xfmr/scripts/catboost_skill_scouting.py`
- Added inference scripts:
  - `models_dir/scouting_report_xfmr/scripts/catboost_scouting_inference.py`
  - `models_dir/skill_rating_xfmr/scripts/catboost_skill_scouting_inference.py`
- Training scripts now query `hs_bv_matched.db` with explicit aliases from prefixed source columns to normalized feature names:
  - `hs_scouting_report AS scouting_report`
  - `hs_scouting_report_evaluator_name AS scouting_report_evaluator_name`
  - `hs_skill_athleticism AS skill_athleticism`, etc.
- Added feature flags:
  - `has_scouting_report_text`
  - `has_scouting_report_evaluator`
  - `has_skill_ratings_available` for the skill+scouting model.
- Added `scouting_report_evaluator_name` as a categorical feature in both transformer-based models.
- Fixed artifact paths so scripts under `scripts/` write to the model folder's sibling `artifacts/` directory.
- Inference scripts read 2026 rows from `data_dir/hs_complete.db`, where HS columns are unprefixed, and build the same normalized feature columns expected by training.
- Syntax checks passed for all four scripts.
- Data availability check:
  - labeled rows in `hs_bv_matched.db` with non-null `bv_role`: 8,577.
  - labeled rows with non-empty scouting reports: 818.
  - labeled rows with evaluator names: 812.
  - labeled rows with skill ratings: 86.
  - 2026 inference rows in `hs_complete.db`: 631.
  - 2026 rows with non-empty scouting reports: 135.
  - 2026 rows with evaluator names: 134.
  - 2026 rows with skill ratings: 0.
- Did not run model training or inference because `sentence_transformers` is not installed locally:
  - import check failed with `ModuleNotFoundError: No module named 'sentence_transformers'`.

### 2026-06-03 22:42:50 CDT

Prompt summary:

- Downgrade `transformers` and run the scouting-report CatBoost model after the prior Torch/Transformers incompatibility.
- Keep the scouting evaluator logic present but commented out as a model feature because evaluator overlap may not hold for 2026.
- Train the scouting-report model, run 2026 inference, and report normal held-out test metrics.

Result:

- Downgraded `transformers` to `4.57.6`; `torch` remained at `2.2.2`.
- Added/kept environment guards in transformer model scripts to avoid TensorFlow/Keras import conflicts:
  - `USE_TF=0`
  - `TRANSFORMERS_NO_TF=1`
- Confirmed `SentenceTransformer` imports successfully after the downgrade.
- In `models_dir/scouting_report_xfmr/scripts/catboost_scouting_rep.py`, left evaluator parsing/metadata in place but commented evaluator feature usage out:
  - `EVALUATOR_COL` is commented out of `CAT_FEATURES`.
  - `EVALUATOR_COL` and `EVALUATOR_FLAG_COL` are commented out of `feature_cols`.
- Training completed for `models_dir/scouting_report_xfmr/scripts/catboost_scouting_rep.py`.
- Best validation log loss: `1.3570080461531382`.
- Best params:
  - `iterations`: `1187`
  - `learning_rate`: `0.03174556449427722`
  - `depth`: `4`
  - `l2_leaf_reg`: `2.4202281174435583`
  - `bagging_temperature`: `0.4734355286065646`
- Held-out 2024-2025 test metrics:
  - rows: `988`
  - log loss: `1.322872`
  - top-1 accuracy: `0.469636`
  - top-3 accuracy: `0.857287`
  - balanced accuracy: `0.360986`
  - average top-1 probability: `0.481419`
  - median top-1 probability: `0.435931`
- Saved artifacts:
  - `models_dir/scouting_report_xfmr/artifacts/catboost_playtype_with_scouting_embeddings.cbm`
  - `models_dir/scouting_report_xfmr/artifacts/catboost_playtype_with_scouting_embeddings_metadata.json`
  - `models_dir/scouting_report_xfmr/artifacts/scouting_embeddings_sentence-transformers__all-MiniLM-L6-v2.parquet`
- Ran 2026 inference successfully.
- Saved 631 scored 2026 rows to:
  - `models_dir/scouting_report_xfmr/outputs/catboost_scouting_2026_top3_predictions.csv`
- Notes:
  - The first training run needed network approval to download/cache `sentence-transformers/all-MiniLM-L6-v2`.
  - The first inference attempt stalled under sandboxed DNS because `sentence-transformers` performed Hugging Face metadata checks even after caching; it was terminated and rerun with network approval.
  - Non-fatal warnings seen: mixed Intel/LLVM OpenMP warning, Arrow CPU `sysctlbyname` permission warnings, and pandas fragmentation warnings during inference embedding-column insertion.

### 2026-06-04 19:16:27 CDT

Prompt summary:

- Clean `data_dir/data_cleaning/name_team_manualreview.csv` so manual review does not include players or BartTorvik rows already present in `data_dir/hs_bv_matched.db`.
- Do not edit any DB files.
- Validate that already-matched examples such as Anthony Davis, GG Jackson, and Zakai Zeigler are removed from manual review.

Result:

- Edited only `data_dir/data_cleaning/name_team_manualreview.csv`.
- Did not edit `data_dir/hs_bv_matched.db` or any other database.
- Removed manual-review rows when either side was already matched using strict validation checks:
  - exact `hs_player_key` / `hs_year` presence in the matched DB when keys were available.
  - exact `bv_pid` presence in the matched DB when keys were available.
  - normalized exact HS name plus normalized enrolled/signed institution match against matched DB identities.
  - normalized exact HS name plus exact DOB match when DOB was available.
  - normalized exact BV name plus normalized BV team match against matched DB identities.
  - normalized exact BV name plus exact BV DOB match when DOB was available.
- `name_team_manualreview.csv` row count changed from `2,493` to `1,456`.
- Preserved the original 18 CSV columns.
- Post-clean validation results:
  - `remaining_already_matched_violations`: `0`.
  - Anthony Davis remaining manual-review rows: `0`.
  - GG Jackson remaining manual-review rows: `0`.
  - Zakai Zeigler remaining manual-review rows: `0`.
  - `hs_bv_matched.db` remained at `8,586` rows.

### 2026-06-04 19:32:05 CDT

Prompt summary:

- Reformat/rebuild `data_dir/data_cleaning/name_team_manualreview.csv` so it is useful for reviewing unmatched recruits.
- The manual review CSV does not need to retain every old sparse row, but every remaining row must be actionable: when the user later says to move a recruit, the row should identify exact source rows from both `hs_complete.db` and `bvt_allyears_MAX.db` so all HS and BartTorvik columns can be expanded into `hs_bv_matched.db`.
- Do not edit DB files.

Result:

- Rebuilt `data_dir/data_cleaning/name_team_manualreview.csv` from the current unmatched HS pool and unused earliest BartTorvik pid pool using the second-round matching candidate logic.
- Replaced the mixed sparse/full manual-review file with keyed candidate rows only.
- Row count is now `172`.
- Preserved the existing 18-column CSV schema.
- All remaining rows now have:
  - `hs_year`
  - `hs_player_key`
  - `hs_signed_or_enrolled`
  - `bv_year`
  - `bv_pid`
  - `name_score`
  - `team_score`
  - `confidence`
  - `year_gap`
  - `match_tier`
- `match_flag` is blank for the rebuilt candidates; the user can mark rows for later movement.
- Validation results:
  - each manual row maps to exactly one source row in `hs_complete.db` by `(hs_year, hs_player_key)`: `0` failures.
  - each manual row maps to exactly one earliest BartTorvik pid source row in `bvt_allyears_MAX.db` by `(bv_year, bv_pid)`: `0` failures.
  - already-matched HS key violations against `hs_bv_matched.db`: `0`.
  - already-used BV pid violations against `hs_bv_matched.db`: `0`.
  - duplicate manual key rows by `(hs_year, hs_player_key, bv_year, bv_pid)`: `0`.
  - `hs_bv_matched.db` remained at `8,586` rows.

### 2026-06-04 19:44:03 CDT

Prompt summary:

- Correct the manual-review rebuild after the user clarified that the CSV should contain broad possible matches, not only one-to-one resolved candidates.
- Use the entire currently unmatched HS pool that can reasonably be matched to college data, explicitly including the newly scraped 2009 recruits.
- Match against only unmatched BartTorvik players, using each BartTorvik pid's oldest season row.
- Keep the CSV concise for human review, but retain source keys so a selected row can later be expanded into the full HS and full BartTorvik records for `hs_bv_matched.db`.

Result:

- Rebuilt `data_dir/data_cleaning/name_team_manualreview.csv` again as a broad manual-review candidate pool.
- Backed up the prior 172-row keyed file to:
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_broad_rebuild_20260604_194109.csv`
- The previous 172-row result was too narrow because it used one-to-one candidate resolution; that was inappropriate for manual review.
- New candidate logic:
  - HS side: currently unmatched HS recruits from `hs_complete.db`, excluding 2026 because no completed college season should be expected yet.
  - Included 2009 HS recruits.
  - BV side: unused BartTorvik pids only, using the oldest season row per pid.
  - Primary evidence: fuzzy full-name match plus fuzzy signed/enrolled institution vs BV team match.
  - Allowed multiple possible BV candidates per HS recruit, up to 10 per recruit.
  - Candidate year gaps considered: `0` through `4`.
  - DOB is displayed and affects match tier/confidence, but DOB conflicts are not automatically discarded because some source DOBs appear defaulted or imperfect.
- Rebuilt CSV result:
  - candidate rows: `368`
  - unique HS recruits with candidates: `347`
  - eligible unmatched HS pool searched: `1,452`
  - 2009 candidate rows: `57`
- Validation results:
  - every row has non-null `(hs_year, hs_player_key, bv_year, bv_pid)`: `368`.
  - each row maps to exactly one source row in `hs_complete.db`: `0` failures.
  - each row maps to exactly one oldest-pid source row in `bvt_allyears_MAX.db`: `0` failures.
  - already-matched HS key violations: `0`.
  - already-used BV pid violations: `0`.
  - duplicate exact candidate rows: `0`.
  - `hs_bv_matched.db` remained at `8,586` rows.

### 2026-06-04 19:54:54 CDT

Prompt summary:

- Validate the usable unmatched HS pool using the user's equation:
  - matched HS rows + usable unmatched pool = `hs_complete` non-2026 rows.
- Rebuild `name_team_manualreview.csv` using institution matching when possible, then strict name-only fallback only when no institution signal is available.
- Keep 2009 recruits included.

Result:

- Pool validation:
  - `hs_complete` rows: `13,740`.
  - 2026 HS rows excluded from matching: `631`.
  - non-2026 HS rows: `13,109`.
  - `hs_bv_matched.db` rows / unique matched HS keys: `8,586`.
  - unmatched non-2026 HS pool: `4,523`.
  - validation equation passed: `8,586 + 4,523 = 13,109`.
- Root cause of the prior low `1,452` usable-pool number:
  - `1,452` only counted unmatched non-2026 recruits with signed/enrolled school fields.
  - It incorrectly excluded unmatched recruits that lacked signed/enrolled fields but had committed-school institution evidence or no institution evidence.
- Rebuilt `data_dir/data_cleaning/name_team_manualreview.csv` again with corrected candidate logic.
- Backed up prior broad file to:
  - `data_dir/data_cleaning/name_team_manualreview.backup_before_institution_plus_name_fallback_20260604_195000.csv`
- Candidate logic:
  - HS pool: all `4,523` unmatched non-2026 HS recruits.
  - institution-backed pass: used signed/enrolled institution first, then committed-school fields as fallback institution evidence.
  - name-only fallback: used only for HS rows with no signed/enrolled/committed institution signal.
  - did not use `current_school` as institution evidence because it can contain high schools, NBA teams, or other non-college values.
  - BV pool: unused BartTorvik pids only, using oldest season row per pid.
  - 2009 recruits included.
- Final manual-review CSV:
  - candidate rows: `2,337`.
  - unique HS recruits with candidates: `2,228`.
  - 2009 candidate rows: `68`.
  - all rows have non-null source keys `(hs_year, hs_player_key, bv_year, bv_pid)`.
- Validation results:
  - HS source lookup failures by `(hs_year, hs_player_key)`: `0`.
  - BV oldest-pid source lookup failures by `(bv_year, bv_pid)`: `0`.
  - already-matched HS violations: `0`.
  - already-used BV pid violations: `0`.
  - duplicate exact candidate rows: `0`.
  - `hs_bv_matched.db` remained at `8,586` rows.

### 2026-06-04 19:57:09 CDT

Prompt summary:

- Add a `dupe_flag` column to `data_dir/data_cleaning/name_team_manualreview.csv`.
- Mark duplicate HS recruit candidate groups so the user can see which recruits have multiple possible BV matches.
- Leave `match_flag` available and blank for user review decisions.

Result:

- Added `dupe_flag` to `name_team_manualreview.csv`.
- `dupe_flag = True` for every row where the same `(hs_year, hs_player_key)` appears more than once in the manual-review CSV.
- Row count remained `2,337`.
- `dupe_flag` true rows: `203`.
- Unique HS recruits with duplicate candidate rows: `94`.
- `match_flag` remained present and blank for all rows.

### 2026-06-04 20:28:11 CDT

Prompt summary:

- Investigate the confusing Anyeuri Castillo manual-review row without editing CSV files.
- Specifically explain why the row shows Kent State on one side but Appalachian State in `hs_signed_or_enrolled`.

Result:

- Did not edit CSV or DB files.
- `hs_complete.db` contains one HS row for `player_key = 46059298`.
- That row has:
  - `signed_school = Appalachian State`
  - `committed_school = Appalachian State`
  - `current_school = Kent State`
  - `enrolled_institution_247 = Kent State`
- Cached 247 profile/timeline confirms both facts:
  - signed/committed Appalachian State on `2018-11-15`.
  - enrolled Kent State on `2019-10-15`.
- BartTorvik has Anyeuri Castillo at Kent State in 2020 with pid `70250`.
- Interpretation:
  - This is not a simple scrape corruption; 247 itself records a signed/committed school and a later enrolled/current school.
  - For matching actual college appearance, Kent State is the stronger institution signal.
  - The manual-review row is confusing because `hs_signed_or_enrolled` currently prioritizes `signed_school` over `enrolled_institution_247`, so it displays Appalachian State even when enrolled/current is Kent State.

### 2026-06-04 20:33:23 CDT

Prompt summary:

- Investigate six name-only manual-review candidates without editing data files.
- Look only in BartTorvik data to determine whether an earlier BV year exists for the same player/name/pid.

Result:

- Did not edit CSV or DB files.
- Checked listed BV pids and exact normalized BV player names in `data_dir/bvt_allyears_MAX.db`.
- Findings:
  - Mark McLaughlin, pid `17294`: earliest BV row is Seattle `2011`; no earlier exact-name or same-pid BV row.
  - Shane Phillips, pid `21259`: earliest BV row is South Carolina `2012`; no earlier exact-name or same-pid BV row.
  - Tyler Summitt, pid `16661`: earliest BV row is Tennessee `2011`; no earlier exact-name or same-pid BV row.
  - C.J. Reese, pid `31567`: earliest BV row is Southeast Missouri St. `2014`; no earlier exact-name or same-pid BV row.
  - Cameron Neysmith, pid `38201`: earliest BV row is Kennesaw St. `2015`; no earlier exact-name or same-pid BV row.
  - Deontae Hawkins, pid `36639`: earliest BV row is Illinois St. `2015`; no earlier exact-name or same-pid BV row.
- Interpretation:
  - For these six cases, the delayed BV year is real in the current BV data rather than caused by selecting a later row for an existing pid.
  - Some of the BV rows list non-freshman classes in the first available BV season, e.g. Shane Phillips as `Jr` in 2012, which suggests prior non-D1/JUCO/redshirt/late-entry context may exist outside the current BV table.

### 2026-06-04 20:46:43 CDT

Prompt summary:

- Move only manual-review rows with `match_flag = True` from `data_dir/data_cleaning/name_team_manualreview.csv` into `data_dir/hs_bv_matched.db`.
- Expand each selected manual-review row back to the complete HS row plus complete BartTorvik row using the stored source keys.
- Remove successfully moved rows from the manual-review CSV.
- Keep ambiguous rows in the manual-review CSV.
- Put CSV backups under `data_dir/data_cleaning/backups`.

Result:

- Created backups before editing:
  - `data_dir/data_cleaning/backups/name_team_manualreview.backup_before_true_append_20260604_204500.csv`
  - `data_dir/backups/hs_bv_matched.backup_before_manual_true_append_20260604_204500.db`
- Found `2,109` true-like manual-review rows.
- Appended `2,071` complete expanded rows into `data_dir/hs_bv_matched.db`.
- Removed those `2,071` moved rows from `name_team_manualreview.csv`.
- Left `38` true-flagged rows in the manual-review CSV because they represented `19` duplicate BartTorvik `(year, pid)` conflicts where two HS recruit rows pointed to the same BV player.
- Final counts:
  - `hs_bv_matched.db`: `8,586` rows before, `10,657` rows after.
  - `name_team_manualreview.csv`: `2,337` rows before, `266` rows after.
  - loose root-level CSV backups in `data_dir/data_cleaning`: `0`.

Validation:

- Each appended HS row resolved one-to-one from `data_dir/hs_complete.db` by `(hs_year, hs_player_key)`.
- Each appended BV row resolved one-to-one from `data_dir/bvt_allyears_MAX.db` by `(bv_year, bv_pid)`.
- Manual display fields were checked against source rows before append.
- No appended row reused an already-matched HS recruit key.
- No appended row reused an already-matched BV pid.
- No duplicate HS recruit keys or duplicate BV pids were appended in this batch.

### 2026-06-04 20:54:43 CDT

Prompt summary:

- Put the remaining manual-review rows that map to duplicate BartTorvik pids into a single CSV.
- Keep rows from the same duplicate BV pid group right next to each other so the user can choose one.

Result:

- Created `data_dir/data_cleaning/duplicate_bv_pid_manualreview.csv`.
- Included only the remaining true-flagged manual-review rows where the same `(bv_year, bv_pid)` appears more than once.
- Wrote `38` rows across `19` duplicate BV pid groups.
- Sorted by `bv_year`, `bv_pid`, BV player name, HS year, and HS player key so each duplicate group is contiguous.
- Left `data_dir/data_cleaning/name_team_manualreview.csv` unchanged.

Validation:

- Confirmed the output CSV has `38` rows.
- Confirmed it has `19` groups.
- Confirmed every group has more than one row.
- Confirmed all rows for each duplicate BV key are adjacent.

### 2026-06-04 21:01:00 CDT

Prompt summary:

- Resolve the duplicate-BV-pid manual-review groups because the user determined the groups were matches.
- For each duplicate BV pid group, prefer the candidate where `bv_year = hs_year + 1`.
- If a duplicate group still has multiple candidates after that filter, select the expanded HS+BV row with the most non-null/non-empty source values.
- Insert the selected complete expanded rows into `data_dir/hs_bv_matched.db`.

Result:

- Created backups before editing:
  - `data_dir/backups/hs_bv_matched.backup_before_duplicate_pid_resolution_20260604_210039.db`
  - `data_dir/data_cleaning/backups/name_team_manualreview.backup_before_duplicate_pid_resolution_20260604_210039.csv`
  - `data_dir/data_cleaning/backups/duplicate_bv_pid_manualreview.backup_before_resolution_20260604_210039.csv`
- Resolved `19` duplicate BV pid groups.
- Inserted `19` complete expanded HS+BV rows into `data_dir/hs_bv_matched.db`.
- Reduced `data_dir/data_cleaning/duplicate_bv_pid_manualreview.csv` from `38` rows to the `19` selected winner rows and added selection metadata columns.
- Removed the `38` resolved true-flagged duplicate-conflict rows from `data_dir/data_cleaning/name_team_manualreview.csv`.
- Final counts:
  - `hs_bv_matched.db`: `10,657` rows before, `10,676` rows after.
  - `name_team_manualreview.csv`: `266` rows before, `228` rows after.
  - `duplicate_bv_pid_manualreview.csv`: `38` rows before, `19` rows after.

Validation:

- Confirmed all `19` selected BV pids appear exactly once in `hs_bv_matched.db`.
- Confirmed `name_team_manualreview.csv` has `0` remaining true-flagged rows.
- Confirmed `duplicate_bv_pid_manualreview.csv` now has `19` unique BV keys and no repeated BV key.
- Selection breakdown:
  - `17` groups selected by the `bv_year = hs_year + 1` rule.
  - `2` groups selected by the non-null/non-empty information count tiebreak because no candidate had `bv_year = hs_year + 1`.

### 2026-06-04 21:05:43 CDT

Prompt summary:

- Inspect `data_dir/data_cleaning/duplicate_bv_pid_manualreview.csv` for user-added last-column flags.
- Reinsert rows marked as "leave separate" back into `data_dir/data_cleaning/name_team_manualreview.csv`.

Result:

- Did not edit CSV or DB data files.
- Inspected the duplicate-pid CSV and found `19` rows.
- The physical last column is `selection_next_year_candidates`, which contains the prior metadata values `0`, `1`, or `2`.
- The prior blank note column `Unnamed: 19` is blank for all `19` rows.
- No saved value resembling "leave separate" was found in the CSV, so no rows were reinserted into `name_team_manualreview.csv`.

### 2026-06-04 21:09:29 CDT

Prompt summary:

- Use `data_dir/data_cleaning/potential_repeated_bv.csv` instead of `duplicate_bv_pid_manualreview.csv`.
- For rows marked `leave_both_separate`, reinsert the affected manual-review rows into `data_dir/data_cleaning/name_team_manualreview.csv`.

Result:

- Inspected `potential_repeated_bv.csv`.
- Found `14` BV-vs-BV pairs marked `leave_both_separate`.
- Found `1` BV-vs-BV pair marked `older_pid_kept_if_same_player`.
- Compared the current manual-review CSV against the pre-append backup for all BV pids involved in the `leave_both_separate` pairs.
- Current `name_team_manualreview.csv` already contained `32` of the `33` relevant prior manual-review rows.
- Reinserted the one missing row:
  - HS `2016`, `player_key = 46045420`, `Keaton Van Soelen`
  - BV `2018`, `pid = 51158`, `Keaton Van Soelen`, Air Force
- Cleared `match_flag` on the reinserted row to avoid making it look like a ready-to-append duplicate.
- Added note `reinserted_leave_both_separate_from_potential_repeated_bv` in `Unnamed: 19`.
- `name_team_manualreview.csv` row count increased from `228` to `229`.
- Left DB files unchanged.

Backup:

- `data_dir/data_cleaning/backups/name_team_manualreview.backup_before_reinsert_leave_separate_bv_20260604_210910.csv`

Validation:

- Confirmed the current manual-review CSV now has all `33` prior manual-review rows involving the `leave_both_separate` BV pids.
- Confirmed `0` missing rows versus `name_team_manualreview.backup_before_true_append_20260604_204500.csv` for those BV pids.

### 2026-06-04 21:11:12 CDT

Prompt summary:

- Enforce the year constraint in `data_dir/hs_bv_matched.db`.
- For every matched row where `bv_year != hs_year + 1`, remove it from `hs_bv_matched`.
- Insert those removed rows into a new table named `year_constraint_failure` in the same DuckDB file.
- List the highest-rated recruits that failed the year constraint.

Result:

- Created backup:
  - `data_dir/backups/hs_bv_matched.backup_before_year_constraint_move_20260604_211101.db`
- Created table `year_constraint_failure` with the same schema as `hs_bv_matched`.
- Moved `1,677` rows from `hs_bv_matched` into `year_constraint_failure`.
- `hs_bv_matched` row count changed from `10,676` to `8,999`.
- `year_constraint_failure` row count is `1,677`.

Validation:

- Confirmed `hs_bv_matched` has `0` remaining rows where `hs_year IS NULL`, `bv_year IS NULL`, or `bv_year != hs_year + 1`.
- Failure year-gap distribution:
  - `-11`: `1`
  - `-5`: `1`
  - `-3`: `1`
  - `-2`: `1`
  - `-1`: `4`
  - `0`: `74`
  - `2`: `1,343`
  - `3`: `186`
  - `4`: `63`
  - `5`: `3`

### 2026-06-04 23:27:47 CDT

Prompt summary:

- Rerun the `baseline_model` and `scouting_report_xfmr` playtype models using the updated `data_dir/hs_bv_matched.db`.
- Run inference on the 2026 class for both models.
- Add better logging artifacts: Optuna trial metrics, per-iteration metrics, split metrics, model params, confusion matrices, and practical ML summaries.
- Back up existing saved model artifacts before overwriting current artifact filenames.

Code changes:

- Updated `models_dir/baseline_model/scripts/catboost_baseline_trials.py`.
  - Fixed project/model path handling.
  - Added `optuna_trials.csv`, `optuna_iteration_metrics.csv`, `final_iteration_metrics.csv`, `metrics_by_split.csv`, `metrics_summary.json`.
  - Added train/valid/test confusion matrices and classification reports.
  - Added top-1 and top-3 accuracy alongside log loss.
- Updated `models_dir/baseline_model/scripts/catboost_baseline_inference.py`.
  - Fixed project/model path handling after folder move.
- Updated `models_dir/scouting_report_xfmr/scripts/catboost_scouting_rep.py`.
  - Added the same metrics/logging artifact outputs as baseline.
  - Kept scouting evaluator value commented out as a feature, but kept evaluator availability flag.
  - Added local-only SentenceTransformer loading using the cached local snapshot.
  - Rebuilt scouting embeddings for the updated filtered matched data.
- Updated `models_dir/scouting_report_xfmr/scripts/catboost_scouting_inference.py`.
  - Added local-only SentenceTransformer loading using metadata `embedding_model_path`.
  - Reworked embedding-column assembly to avoid pandas fragmentation warnings.

Backups:

- Baseline previous artifacts:
  - `models_dir/baseline_model/artifacts/backups/previous_artifacts_20260604_212507/catboost_baseline_playtype_model.cbm`
  - `models_dir/baseline_model/artifacts/backups/previous_artifacts_20260604_212507/catboost_baseline_playtype_metadata.json`
  - `models_dir/baseline_model/artifacts/backups/previous_artifacts_20260604_212507/model_params.txt`
- Scouting previous artifacts:
  - `models_dir/scouting_report_xfmr/artifacts/backups/previous_artifacts_20260604_212507/catboost_playtype_with_scouting_embeddings.cbm`
  - `models_dir/scouting_report_xfmr/artifacts/backups/previous_artifacts_20260604_212507/catboost_playtype_with_scouting_embeddings_metadata.json`
  - `models_dir/scouting_report_xfmr/artifacts/backups/previous_artifacts_20260604_212507/model_params.txt`

Training results:

- Baseline model:
  - labeled rows: `8,990`
  - train rows: `6,822`
  - valid rows: `1,117`
  - test rows: `1,051`
  - best validation log loss: `1.350719246824245`
  - test log loss: `1.3604667574646236`
  - test top-1 accuracy: `0.4548049476688868`
  - test top-3 accuracy: `0.8667935299714558`
  - best params: `iterations=1603`, `learning_rate=0.1208477527445918`, `depth=4`, `l2_leaf_reg=2.1474533743252815`, `bagging_temperature=0.8256178443374325`
- Scouting report embedding model:
  - labeled rows: `8,990`
  - train rows: `6,822`
  - valid rows: `1,117`
  - test rows: `1,051`
  - best validation log loss: `1.3355686527466277`
  - test log loss: `1.3468232248353262`
  - test top-1 accuracy: `0.46907706945765937`
  - test top-3 accuracy: `0.879162702188392`
  - best params: `iterations=1801`, `learning_rate=0.02817040664839508`, `depth=5`, `l2_leaf_reg=1.137628112577669`, `bagging_temperature=0.9836916216232724`

Inference outputs:

- Baseline 2026 predictions:
  - `models_dir/baseline_model/outputs/baseline/catboost_baseline_top3_predictions.csv`
  - rows scored: `631`
- Scouting 2026 predictions:
  - `models_dir/scouting_report_xfmr/outputs/catboost_scouting_2026_top3_predictions.csv`
  - rows scored: `631`

Notes:

- The first scouting training attempt failed because the old embedding cache did not cover the updated dataset and SentenceTransformer tried to check Hugging Face while network access was unavailable.
- Fixed by using the local cached snapshot path and rebuilding the embedding cache locally.
- DuckDB/Arrow emitted sandbox-related `sysctlbyname` warnings; these did not block training or inference.
- SentenceTransformer emitted an OpenMP duplicate-runtime warning; training and inference completed successfully despite it.

### 2026-06-05 21:01:41 CDT

Prompt summary:

- Start matching unmatched BartTorvik transfer rows.
- Use `data_dir/bv_trans_compl_MAX.db` as the transfer source.
- For transfer rows with null `barttorvik_trid`, find potential player matches in `data_dir/bvt_allyears_MAX.db`.
- Do not edit any DB files.
- Keep code and outputs under `data_dir/data_cleaning/transfer_cleaning`.
- Candidate all-years players must have `pid`/`barttorvik_trid` values that are not already present as non-null transfer `barttorvik_trid` values.

Implementation:

- Added `data_dir/data_cleaning/transfer_cleaning/build_transfer_manual_review.py`.
- Used documented transfer orientation:
  - old-team side maps to `barttorvik_year`.
  - new-team side maps to `transfer_cycle_season` when present, otherwise `barttorvik_year + 1`.
- Used broad fuzzy matching with `rapidfuzz` over transfer player name and old/new team names.
- Generated:
  - route candidates when the same unused all-years `pid` matched both old-team and new-team sides.
  - one-sided candidates when only the old or new side had a strong candidate.
- Left `match_flag` blank for manual review.

Outputs:

- `data_dir/data_cleaning/transfer_cleaning/transfer_null_trid_manual_review.csv`
- `data_dir/data_cleaning/transfer_cleaning/transfer_null_trid_manual_review_summary.json`

Result:

- Total transfer rows: `16,897`.
- Null transfer `barttorvik_trid` rows: `5,214`.
- Non-null transfer `barttorvik_trid` rows: `11,683`.
- Distinct non-null transfer IDs excluded from candidate pool: `8,941`.
- Unused all-years rows considered: `55,129`.
- Unused all-years distinct pids considered: `23,062`.
- Candidate rows written: `1,096`.
- Null transfer rows with candidates: `1,093`.
- Null transfer rows without candidates: `4,121`.
- Candidate type counts:
  - `old_side_only`: `648`
  - `new_side_only`: `424`
  - `route_old_and_new`: `24`

Validation:

- Confirmed `0` candidate pids in the manual-review CSV appear as existing non-null transfer `barttorvik_trid` values.
- Confirmed all `match_flag` values are blank for manual review.
- Confirmed no DB files were edited.

Notes:

- The brute-force pass was intentionally left broad for recall/accuracy rather than optimized aggressively.
- Runtime was longer because another ML training job was running concurrently, but the process completed successfully.

### 2026-06-05 21:37:56 CDT

Prompt summary:

- Scan the live main DB files in `data_dir` for strange name symbols/mojibake.
- Do not scan backup DBs.
- Do not edit the transfer manual-review CSV.
- Do not remove or overwrite existing DB values.
- If strange name symbols are found, add a column with corrected names.

Result:

- Scanned live DBs directly under `data_dir`:
  - `bv_trans_compl_MAX.db`
  - `bvt_allyears_MAX.db`
  - `hs_bv_matched.db`
  - `hs_complete.db`
- Treated legitimate accented names/hometowns as valid, e.g. `Uroš Paunović`, `Vasja Pandža`, `Domžale`.
- Found actual mojibake in `data_dir/bvt_allyears_MAX.db`, table `bvt_allyears_MAX`, column `player_name`:
  - `Barry HonorĂŠ`
  - `Zieyik EstimĂ¨`
- Added nullable column `player_name_corrected` to `bvt_allyears_MAX`.
- Populated only rows with corrupted source names:
  - `Barry HonorĂŠ` -> `Barry Honoré` (`1` row)
  - `Zieyik EstimĂ¨` -> `Zieyik Estimè` (`2` rows)
- Left all other `player_name_corrected` values as `NULL`.
- Did not remove or alter original `player_name` values.
- Did not edit `data_dir/data_cleaning/transfer_cleaning/transfer_null_trid_manual_review.csv`.

Backup:

- `data_dir/backups/bvt_allyears_MAX.backup_before_player_name_corrected_20260605_213735.db`

Validation:

- `bvt_allyears_MAX` row count stayed `81,562`.
- `bv_trans_compl_MAX` row count stayed `16,897`.
- `hs_bv_matched` row count stayed `8,999`.
- `year_constraint_failure` row count stayed `1,677`.
- `hs_complete` row count stayed `13,740`.
- Confirmed `player_name_corrected` has exactly `3` non-null rows in `bvt_allyears_MAX`.

Source checks:

- Used public source snippets to confirm the corrected display names:
  - Barry Honoré / Honore reference from Oklahoma/Sports-Reference/ESPN context.
  - Zieyik Estimè reference from Norfolk State game notes context.

### 2026-06-05 21:42:23 CDT

Prompt summary:

- Review `scrapers_web/evanmiya_analytics/evanmiya_output/evanmiya_player_ratings_all_years.db`.
- Check for weird accent/mojibake/symbol problems similar to the transfer/manual-review issue.
- If corrupt names are found, add corrected-name columns like the prior BartTorvik cleanup.
- If nothing strange is found, copy the DB into `data_dir` with the other main DB files.

Result:

- Reviewed source DB:
  - `scrapers_web/evanmiya_analytics/evanmiya_output/evanmiya_player_ratings_all_years.db`
- Main table:
  - `evanmiya_player_ratings`
  - rows: `48,680`
  - columns: `39`
- Scanned string/name-like columns including:
  - `name`
  - `team`
  - `player_name_join`
  - player-list/color/class text fields
- Found normal accents/apostrophes only, e.g.:
  - `Carlos Jürgens`
  - `Davonté Lacy`
  - `Francis Lācis`
  - `Viktor Rajković`
  - `Vasja Pandža`
  - `Adante’ Holiman`
- Found no mojibake or junk symbols such as:
  - `Ă`
  - `√`
  - `™`
  - replacement character `�`
  - mojibake curly quote fragments like `‚`
- Did not add any corrected-name columns because no corrupt names were found.
- Copied the DB to:
  - `data_dir/evanmiya_player_ratings_all_years.db`

Validation:

- Source and copied DB both open successfully as DuckDB files.
- Source and copied DB both contain table `evanmiya_player_ratings`.
- Source row count: `48,680`.
- Copied row count: `48,680`.
- Source column count: `39`.
- Copied column count: `39`.
- Source and copied file sizes both `8,663,040` bytes.

### 2026-06-05 22:12:24 CDT

Prompt summary:

- Review `jun_5_autoclass` artifacts for `baseline_model` and `scouting_report_xfmr`.
- Recommend which model to use for a website that lists all HS recruits with multiple projected first-year college playtype probabilities.

Result:

- Compared `metrics_by_split.csv`, metadata, class reports, predicted class distributions, and test probability outputs.
- Baseline `jun_5_autoclass`:
  - test log loss: `1.3136949803894042`
  - test top-1 accuracy: `0.463368`
  - test top-3 accuracy: `0.880114`
  - test macro F1: `0.331985`
  - test weighted F1: `0.412471`
- Scouting `jun_5_autoclass`:
  - test log loss: `1.3267746845927828`
  - test top-1 accuracy: `0.466223`
  - test top-3 accuracy: `0.877260`
  - test macro F1: `0.322351`
  - test weighted F1: `0.408344`
- Recommendation:
  - Use baseline `jun_5_autoclass` as the website default model.
  - Reason: lower held-out test log loss, slightly better top-3 accuracy, better macro/weighted F1, simpler deployment, and no sentence-transformer dependency.
  - Scouting model can be kept as an alternate/experimental model because it had stronger validation metrics, but its held-out test metrics were not better for probability/listing use.

### 2026-06-06 00:55:45 CDT

Prompt summary:

- Start implementing the frontend site in `frontend_site`.
- Follow `frontend_site/codex_instructions/frontend_instructions.md`.
- Recreate the core functionality demonstrated by `collegebasketballportal.com`:
  - player leaderboard / who is in the portal
  - best available players and recommendations
  - transfer portal roster simulator
- Keep implementation concise and frontend-focused.

Result:

- Built a Next.js + TypeScript + Tailwind frontend prototype in `frontend_site`.
- Added reusable app/data structure:
  - `data/players.ts`
  - `data/teams.ts`
  - `lib/data.ts`
  - `components/*`
- Implemented routes:
  - `/` player leaderboard
  - `/portal` in-portal player view
  - `/simulator` transfer portal simulator
  - `/recommendations` team-fit recommendations
  - `/teams/[teamId]` team-specific roster and recommendations page
- Player leaderboard functionality includes:
  - search
  - filters for position, class, status, team, conference, playtype, and minimum BPR
  - All Players / In Portal toggle
  - sortable table columns
  - expandable player detail panels with bio, projected stats, fit explanation, scouting summary, and playtype probabilities
- Portal simulator functionality includes:
  - team selection
  - remove current roster players
  - add portal targets
  - track scholarship count, roster size, projected roster BPR, departures, and additions
- Recommendations view ranks portal players by team-adjusted fit score and displays top role probabilities.
- Added `frontend_site/README.md` with run instructions and data replacement notes.

Validation:

- Installed frontend dependencies with `npm install`.
- Production build passed with `npm run build`.
- Build generated routes for all implemented pages.

Notes:

- Could not directly inspect `collegebasketballportal.com` content through the available browser tooling, so implementation followed the requested functionality and the local frontend instruction file.
- `npm install` reported `5` transitive audit findings; package versions were kept stable for build compatibility.

### 2026-06-06 01:14:11 CDT

Prompt summary:

- Add a best-practice dependency document inside `frontend_site` so `node_modules` does not need to be pushed to GitHub.

Result:

- Added `frontend_site/DEPENDENCIES.md`.
- Document explains:
  - commit `package.json` and `package-lock.json`
  - use `npm ci` after cloning for exact dependency installation
  - use `npm install <package-name>` for dependency changes
  - do not commit `node_modules`
- Added `frontend_site/.gitignore` to exclude:
  - `node_modules/`
  - `.next/`
  - `out/`
  - local env files
  - npm/yarn/pnpm debug logs
  - `.DS_Store`

Validation:

- Confirmed `frontend_site/package-lock.json` already exists and captures the full resolved npm dependency tree.

### 2026-06-06 01:16:22 CDT

Prompt summary:

- Move the frontend-specific ignore rules from `frontend_site/.gitignore` into the existing repo-level `.gitignore`.
- Adjust paths so they apply correctly from the repository root.
- Delete the nested frontend `.gitignore`.

Result:

- Updated `.gitignore` with prefixed frontend rules for:
  - `frontend_site/node_modules/`
  - `frontend_site/.next/`
  - `frontend_site/out/`
  - frontend local env files
  - frontend npm/yarn/pnpm debug logs
- Deleted `frontend_site/.gitignore`.

### 2026-06-06 01:38:41 CDT

Prompt summary:

- Add a light/dark mode toggle to the frontend site.
- Bonus request: automatically detect and follow the user's system color-scheme setting.

Result:

- Added `frontend_site/components/ThemeToggle.tsx`.
- Added a three-state theme control:
  - `System`
  - `Light`
  - `Dark`
- Theme preference is persisted in `localStorage` under `roster-lab-theme`.
- `System` mode follows `prefers-color-scheme` and updates if the OS theme changes.
- Added an inline initialization script in `frontend_site/app/layout.tsx` to apply the stored/system theme before hydration, reducing theme flash.
- Updated Tailwind config to use class-based dark mode and CSS variable-backed colors.
- Updated global CSS with light/dark color variables and dark-mode text/background overrides.
- Added the theme control to the desktop sidebar and mobile header.

Validation:

- `npm run build` passed successfully after the theme changes.

### 2026-06-06 02:21:46 CDT

Prompt summary:

- Process `data_dir/data_cleaning/evan_bv_matching/low_confidence_matches_for_review.csv` after manual `match_flag` review.
- Keep only rows where `match_flag` equals `True`/`TRUE` in the review CSV.
- Remove rows where `match_flag` is empty or not `True` from both:
  - `low_confidence_matches_for_review.csv`
  - `evan_miya_barttorvik_matched.db`
- Move removed rows into `evan_bv_unmatched.csv` in the same directory.

Result:

- Used `(evan_row_id, bvt_row_id)` as the row identity key because `match_flag` exists only in the review CSV, not in the matched DB.
- Initial review CSV row count: `1,843`.
- Rows with `match_flag` equal to `TRUE`: `1,825`.
- Rows with blank/non-true `match_flag`: `18`.
- Wrote the `18` blank/non-true rows to:
  - `data_dir/data_cleaning/evan_bv_matching/evan_bv_unmatched.csv`
- Rewrote `low_confidence_matches_for_review.csv` to contain only the `1,825` `TRUE` rows.
- Deleted the same `18` rows from DuckDB table `evan_miya_barttorvik_matched`.

Backups:

- Created backups in:
  - `data_dir/data_cleaning/evan_bv_matching/backups`
- Backed up both the review CSV and matched DB before modifying them.

Validation:

- Final review CSV row count: `1,825`.
- Final review CSV `match_flag` values: all `TRUE`.
- `evan_bv_unmatched.csv` row count: `18`.
- Matched DB row count changed from `48,680` to `48,662`.
- Confirmed `0` moved unmatched keys remain in `evan_miya_barttorvik_matched.db`.

### 2026-06-06 02:27:06 CDT

Prompt summary:

- Check whether manually confirmed transfer matches from `data_dir/data_cleaning/transfer_cleaning/transfer_null_trid_manual_review.csv` were already moved into the actual transfer DB.
- User clarified the relevant field is `barttorvik_trid`, not `pid`.
- Do not edit DB files.

Result:

- Reviewed documentation for the transfer manual-review generation.
- Documentation shows the transfer manual-review CSV was created on `2026-06-05` and no DB files were edited during that process.
- Current manual-review CSV now contains:
  - total rows: `1,096`
  - `match_flag = TRUE`: `1,093`
  - blank `match_flag`: `3`
  - unique TRUE transfer keys: `1,090`
- Confirmed `candidate_barttorvik_trid` is populated for all `1,093` TRUE rows.
- Checked `data_dir/bv_trans_compl_MAX.db` read-only.
- The transfer DB table `bv_trans_compl_MAX` has `barttorvik_trid`; it does not have a separate `pid` column.

Validation:

- Joined all `1,093` TRUE review rows back to `bv_trans_compl_MAX` by transfer identity fields.
- All `1,093` TRUE rows matched transfer DB rows.
- All `1,093` matched transfer DB rows still have `barttorvik_trid IS NULL`.
- `0` TRUE manual-review rows already have non-null `barttorvik_trid` in the transfer DB.
- Overall transfer DB counts are unchanged from prior transfer documentation:
  - `barttorvik_trid IS NULL`: `5,214`
  - `barttorvik_trid IS NOT NULL`: `11,683`

Conclusion:

- The manually confirmed transfer `barttorvik_trid` values have not yet been moved into the actual transfer DB.
- No DB or CSV files were edited during this check.

### 2026-06-06 02:34:32 CDT

Prompt summary:

- Promote manually confirmed transfer matches from `data_dir/data_cleaning/transfer_cleaning/transfer_null_trid_manual_review.csv` into `data_dir/bv_trans_compl_MAX.db`.
- For transfer rows with current null `barttorvik_trid`, fill `barttorvik_trid` from `candidate_barttorvik_trid` when `match_flag = TRUE`.
- For duplicate TRUE candidate rows, use the `100` confidence / rank-1 candidate.
- Scan all live main `.db` files directly under `data_dir` for weird symbols in name-like columns and clean names only.

Transfer `barttorvik_trid` update:

- Review CSV had:
  - TRUE rows with candidate `barttorvik_trid`: `1,093`
  - unique transfer keys after duplicate resolution: `1,090`
- Duplicate TRUE cases were resolved by highest `route_confidence`, then lowest `candidate_rank_for_transfer`.
- Updated only rows in `bv_trans_compl_MAX` where `barttorvik_trid IS NULL`.
- Backup created:
  - `data_dir/backups/bv_trans_compl_MAX.before_manual_transfer_trid_update_20260606_023243.db`

Transfer validation:

- `bv_trans_compl_MAX` row count stayed `16,897`.
- Null `barttorvik_trid` count changed from `5,214` to `4,124`.
- Non-null `barttorvik_trid` count changed from `11,683` to `12,773`.
- Confirmed `0` selected manual-update rows still have null `barttorvik_trid`.

Name cleanup:

- Scanned live DB files directly under `data_dir`:
  - `bv_trans_compl_MAX.db`
  - `bvt_allyears_MAX.db`
  - `evan_miya_barttorvik_matched.db`
  - `evanmiya_player_ratings_all_years.db`
  - `hs_bv_matched.db`
  - `hs_complete.db`
- Cleaned only VARCHAR columns whose column name contains `name`.
- Cleanup normalized names to ASCII display names:
  - removed diacritics, e.g. `Javonté` -> `Javonte`
  - normalized curly/control apostrophes, e.g. `Tommy O’Neil` -> `Tommy O'Neil`
  - fixed observed mojibake fragments, e.g. `Barry HonorĂŠ` -> `Barry Honore`
- No non-name columns were intentionally modified during the name cleanup.

Name cleanup backups:

- Created `.db` backups in `data_dir/backups` with suffix:
  - `.before_name_ascii_cleanup_20260606_023401.db`

Name cleanup validation:

- Final scan found `0` non-ASCII values in name-like VARCHAR columns across the live main `data_dir` DBs.
- Row counts stayed unchanged:
  - `bv_trans_compl_MAX`: `16,897`
  - `bv_trans_compl_MAX_validation`: `15`
  - `bvt_allyears_MAX`: `81,562`
  - `bvt_allyears_MAX_validation`: `11`
  - `evan_miya_barttorvik_matched`: `48,662`
  - `evanmiya_player_ratings`: `48,680`
  - `hs_bv_matched`: `8,999`
  - `hs_bv_matched_validation`: `6`
  - `year_constraint_failure`: `1,677`
  - `hs_complete`: `13,740`
  - `scouting_report_evaluator_parse`: `1,077`

### 2026-06-06 02:53:50 CDT

Prompt summary:

- Fix frontend dark-mode button/badge styling problems.
- Add high-school recruit vs transfer differentiation throughout the app.
- Remove NIL from the website because the project does not have NIL data.

Result:

- Removed all NIL references from frontend app/data/lib code.
- Added `player_source` to mock players:
  - `transfer`
  - `hs`
  - `roster`
- Added additional dummy high-school recruit rows for UI coverage.
- Added source badges for HS recruits, transfers, and roster players.
- Players page/table:
  - added `Player Type` filter
  - supports all players, HS recruits, transfers, and current roster rows
  - removed NIL sort/header/cell
- Portal page:
  - now passes only transfer portal players into the table
  - HS recruits are not included in the portal tab
- Simulator:
  - additions side can now switch between `Transfers`, `HS`, and `Both`
  - selected additions reset when the target pool changes
  - player rows show source badges
- Recommendations:
  - added `All`, `Transfers`, and `HS` target filters
  - recommendations show source badges so HS recruits and transfers are visually distinct
- Dark mode:
  - changed active/action buttons away from `bg-ink` where it inverted to white in dark mode
  - added dark-aware status badge styles
  - fixed active nav/mobile styles and selected simulator controls

Validation:

- Confirmed no remaining `NIL` / `nil_value_placeholder` references in frontend app, components, data, or lib code.
- `npm run build` passed successfully.

### 2026-06-06 14:45:49 CDT

Prompt summary:

- In `data_dir/bv_trans_compl_MAX.db`, exact empty strings were causing `player_role IS NOT NULL` queries to include blank role cells.
- Convert strictly empty string cells (`''`) anywhere in the DB to SQL `NULL`.
- Do not delete data.
- Validate heavily that only truly empty cells are converted.

Result:

- Scanned all VARCHAR columns in all tables in `data_dir/bv_trans_compl_MAX.db`.
- Found exact empty strings only in table `bv_trans_compl_MAX`:
  - `player_height`: `11`
  - `player_hometown`: `37`
  - `player_role`: `1,343`
- Converted only exact `''` values in those columns to SQL `NULL`.
- Did not convert whitespace/non-empty values.
- Did not edit any other DB files.

Backup:

- `data_dir/backups/bv_trans_compl_MAX.before_empty_string_to_null_20260606_144527.db`

Validation:

- Row counts unchanged:
  - `bv_trans_compl_MAX`: `16,897` -> `16,897`
  - `bv_trans_compl_MAX_validation`: `15` -> `15`
- Remaining exact empty string cells across scanned VARCHAR columns: `0`.
- Null counts after conversion:
  - `player_height`: `5,101`
  - `player_hometown`: `5,256`
  - `player_role`: `6,436`
- Re-ran the user's query shape:
  - `barttorvik_trid IS NOT NULL AND player_role IS NOT NULL`
  - returned rows: `10,336`
  - empty strings in returned `player_role`: `0`
- `player_role` value counts no longer include a blank-string category.

### 2026-06-06 14:53:18 CDT

Prompt summary:

- Investigate why `data_dir/bv_trans_compl_MAX.db` has around 2k rows where `barttorvik_trid IS NOT NULL AND player_role IS NULL`, while `data_dir/bvt_allyears_MAX.db` has only around 100 rows where `barttorvik_trid IS NOT NULL AND role IS NULL`.
- Do not edit DB files.

Result:

- No DB files were edited.
- Confirmed `bvt_allyears_MAX.db` does not have an empty-string role issue:
  - total rows: `81,562`
  - `barttorvik_trid IS NOT NULL`: `81,562`
  - `role IS NULL`: `106`
  - `role = ''`: `0`
  - `trim(role) = ''` while non-null: `0`
- Confirmed transfer DB current state:
  - total rows: `16,897`
  - `barttorvik_trid IS NOT NULL`: `12,773`
  - `player_role IS NULL`: `6,436`
  - `player_role = ''`: `0`
  - `barttorvik_trid IS NOT NULL AND player_role IS NULL`: `2,437`

Breakdown of `bv_trans_compl_MAX` rows with non-null `barttorvik_trid` and null `player_role`:

- By transfer year:
  - `2018 -> 2019`: `37`
  - `2019 -> 2020`: `45`
  - `2020 -> 2021`: `45`
  - `2021 -> 2022`: `72`
  - `2022 -> 2023`: `84`
  - `2023 -> 2024`: `80`
  - `2024 -> 2025`: `78`
  - `2025 -> 2026`: `60`
  - `2026 -> 2027`: `1,936`
- By transfer merge status:
  - `stats_merge_status = both`, `has_stats_enrichment = True`: `1,347`
  - `stats_merge_status = left_only`, `has_stats_enrichment = False`: `1,090`

Join-back investigation:

- Joined the `2,437` transfer rows with null `player_role` back to `bvt_allyears_MAX` by `barttorvik_trid`.
- Role availability:
  - rows with same-old-year role available: `2,013`
  - rows with same-new-year role available: `447`
  - rows with any-year role available: `2,436`
  - rows with no all-years role available at all: `1`
- Distribution:
  - old-year role only: `1,970`
  - new-year role only: `404`
  - both old-year and new-year roles: `43`
  - no same-year role but another-year role exists: `19`
  - no role in any year: `1`

Conclusion:

- The mismatch is not caused by empty strings in `bvt_allyears_MAX`.
- The issue is that `bv_trans_compl_MAX.player_role` was not backfilled from `bvt_allyears_MAX.role` for many rows after `barttorvik_trid` assignment/matching.
- This is especially visible for the `1,090` `left_only` rows from the manual transfer-ID matching workflow.
- If fixing later, the safest rule appears to be:
  - fill null transfer `player_role` from all-years `role` where `barttorvik_trid` matches and `year = barttorvik_year` when available;
  - otherwise use `year = transfer_cycle_season` when available;
  - send the small remaining ambiguous/no-same-year cases to review or use a documented nearest-year rule.

### 2026-06-06 14:10:03 CDT

Prompt summary:

- Insert actual 2026 high-school recruits and their baseline top-3 playtype predictions into the frontend.
- Source prediction file:
  - `models_dir/baseline_model/jun_5_autoclass/outputs/baseline/catboost_baseline_top3_predictions.csv`
- Add autocomplete to search.
- Extract recruit profile pictures from cached 247 profile HTMLs.
- Show player pictures on the website.
- Add a collapsible left sidebar/hamburger control to free horizontal row space.
- Do not edit data/DB files outside the frontend site and frontend scripts.

Result:

- Added `frontend_site/scripts/build_hs_recruits.py`.
- Script reads the baseline prediction CSV and local cached 247 profile HTML.
- Script writes generated frontend data to:
  - `frontend_site/data/hsRecruits.ts`
- Generated `631` actual 2026 HS recruit rows.
- Extracted real cached 247 image URLs for `553` of `631` recruits.
- Excluded 247 default placeholder image URLs; missing images fall back to initials in the UI.
- Added `frontend_site/components/PlayerAvatar.tsx`.
- Player avatars now show in:
  - player leaderboard rows
  - recommendations rows
  - simulator target/current roster rows
- Integrated generated HS recruits into `frontend_site/data/players.ts`.
- Removed previously added dummy HS rows so HS data now comes from the actual prediction output.
- Added native search autocomplete through `datalist` suggestions for player/team search.
- Added desktop sidebar collapse/expand via hamburger button in `frontend_site/components/Shell.tsx`.
- Collapsed sidebar keeps icon navigation visible and increases table width.

Data fields present from prediction CSV:

- Player name/key.
- Signed/enrolled school when available.
- Position, height, weight.
- Stars, rating, national rank, position rank.
- Top-3 predicted playtypes and probabilities.
- Full class probability distribution.

Data fields missing from prediction CSV:

- Real scouting text/summaries.
- Hometown.
- Conference mapping for committed schools.
- Local image files; image URLs are extracted from cached 247 HTML instead.

Validation:

- Generated recruit data count: `631`.
- Real image URL count after excluding default placeholders: `553`.
- Default 247 placeholder image URLs remaining: `0`.
- Confirmed no frontend NIL references remain.
- `npm run build` passed successfully.

### 2026-06-06 14:33:32 CDT

Prompt summary:

- On the Players page, replace the player-type dropdown behavior with a top-level three-way toggle:
  - All
  - HS Recruits
  - Transfers
- Make table filters and columns change based on selected player type.
- For HS recruits:
  - table columns should be Player, POS, Committed School, Stars, Rating, Type
  - remove portal status, BPR, and Fit from HS table view
  - remove predicted playtype from the compact player card row
  - keep playtype probability details in expanded rows
  - replace dummy stat cards in expanded row with HS national rank and HS position rank
- Prefer `hs_complete.db` for HS metadata outside model prediction probabilities.

Result:

- Updated `frontend_site/scripts/build_hs_recruits.py` to read `data_dir/hs_complete.db` in addition to the prediction CSV.
- HS recruit generated data now enriches from `hs_complete` for:
  - committed school
  - position
  - height
  - stars
  - rating
  - national rank
  - position rank
- The frontend still does not query DuckDB at runtime; the build script emits static TypeScript data for the browser.
- Added the top-right Players page toggle in `frontend_site/app/page.tsx`.
- Updated dashboard metrics to reflect the selected mode.
- Updated `frontend_site/components/PlayerTable.tsx`:
  - mode-aware filtering
  - mode-aware filter controls
  - mode-aware table columns
  - HS mode removes portal status/BPR/Fit columns
  - HS mode shows committed school, stars, rating, and type
  - table counts/options now derive from the selected mode pool
- Updated `frontend_site/components/PlayerDetailPanel.tsx`:
  - HS expanded rows retain playtype probabilities
  - HS expanded rows show `Nat. Rank` and `Pos. Rank`
  - HS expanded rows do not show BPR/minutes/points/rebounds/assists stat cards

Validation:

- Regenerated `frontend_site/data/hsRecruits.ts`.
- HS recruit rows: `631`.
- Real image URL rows: `553`.
- Rows with non-uncommitted committed/current school after DB enrichment: `631`.
- Rows with rating/stars/national rank from available source data: `367`.
- `npm run build` passed successfully.

Note:

- `hs_complete.db` provides richer metadata, but not every 2026 generated recruit has rating/stars/rank populated; missing values render as `N/A`.

### 2026-06-06 14:40:20 CDT

Prompt summary:

- Restore each player's top predicted playtype in the compact player row.
- Animate playtype probability bars in the expanded player detail panel so they fill to the projected probability each time the row opens.

Result:

- Updated `frontend_site/components/PlayerTable.tsx` to show the top playtype again in the compact player summary line.
- Updated `frontend_site/components/PlayerDetailPanel.tsx`:
  - added mount-triggered animation state
  - probability bars start at `0%`
  - bars transition to their actual probability width after the expanded panel mounts

Validation:

- `npm run build` passed successfully.

### 2026-06-06 15:20:36 CDT

Prompt summary:

- For 2026 transfer rows in `data_dir/bv_trans_compl_MAX.db` with:
  - `barttorvik_year = 2026`
  - `transfer_cycle_season = 2027`
  - `barttorvik_trid IS NULL`
- Force-match every row to a 2026 BartTorvik all-years player candidate from `data_dir/bvt_allyears_MAX.db`.
- Prioritize matching the transfer `old_team` to the candidate 2026 team, with close player-name matching.
- Use global assignment so every null-trid transfer receives one review candidate.
- Do not edit any DB files.

Result:

- Added repeatable script:
  - `data_dir/data_cleaning/transfer_cleaning/build_2026_null_trid_forced_manual_review.py`
- Script reads both DB files in read-only mode.
- Script uses RapidFuzz score matrices plus SciPy `linear_sum_assignment`.
- Candidate pool:
  - 2026 `bvt_allyears_MAX` rows with non-null `barttorvik_trid`
  - `4,978` candidates
- Target pool:
  - 2026 transfer-cycle `2027` rows with null `barttorvik_trid`
  - `1,885` transfers
- Wrote manual review CSV:
  - `data_dir/data_cleaning/transfer_cleaning/transfer_2026_null_trid_forced_manual_review.csv`
- Wrote summary JSON:
  - `data_dir/data_cleaning/transfer_cleaning/transfer_2026_null_trid_forced_manual_review_summary.json`

Review CSV notes:

- One row per transfer.
- Each assigned candidate has a unique `candidate_barttorvik_trid`.
- `match_flag` and `review_note` are blank for manual review.
- Key scoring columns:
  - `assignment_score`
  - `name_score`
  - `team_score`
  - `confidence_bucket`
  - `assigned_candidate_rank_for_transfer`
  - `best_unconstrained_*` columns showing the target row's best candidate before one-to-one assignment constraints.

Validation:

- Output rows: `1,885`.
- Unique transfer row numbers: `1,885`.
- Unique candidate `barttorvik_trid` values: `1,885`.
- Null candidate `barttorvik_trid` values: `0`.
- Confidence buckets:
  - `very_high`: `457`
  - `high`: `5`
  - `medium`: `57`
  - `low`: `274`
  - `very_low_forced`: `1,092`
- `team_score >= 90`: `876`.
- `team_score >= 75`: `1,344`.
- `name_score >= 90`: `461`.

Important interpretation:

- `very_low_forced` rows are expected because the prompt required a candidate for every transfer, including probable JUCO/non-DI cases that may not have a true 2026 BartTorvik all-years row.
- No DB files were edited.

Follow-up clarification:

- Confirmed the forced match search was limited to `bvt_allyears_MAX.year = 2026`.
- Added `best_unconstrained_candidate_year` to the generated review CSV and script for clarity.
- Rebuilt `transfer_2026_null_trid_forced_manual_review.csv`.
- Validation:
  - assigned `candidate_year`: all `1,885` rows are `2026`
  - `best_unconstrained_candidate_year`: all `1,885` rows are `2026`

### 2026-06-06 15:38:43 CDT

Prompt summary:

- User manually marked true matches in:
  - `data_dir/data_cleaning/transfer_cleaning/transfer_2026_null_trid_forced_manual_review.csv`
- Fill the matched transfer rows' `barttorvik_trid` values in:
  - `data_dir/bv_trans_compl_MAX.db`
- Do not edit any other DB cells or rows.

Result:

- Found `458` rows where `match_flag` was true.
- Validation before update:
  - `458` unique `transfer_row_number` values in true rows.
  - `0` null `candidate_barttorvik_trid` values.
  - `0` duplicate `candidate_barttorvik_trid` values.
  - All `458` target DB rows were still null in `barttorvik_trid`.
  - All `458` target DB rows matched the CSV transfer player name and old team exactly.
- Created backup:
  - `data_dir/backups/bv_trans_compl_MAX.before_2026_forced_trid_fill_20260606_153843.db`
- Updated only `barttorvik_trid` for the `458` confirmed rows.

Post-update validation:

- Current DB row count: `16,897`.
- Backup DB row count: `16,897`.
- Rows matching CSV candidate trid after update: `458`.
- Backup target rows that were null before update: `458`.
- Non-`barttorvik_trid` multiset comparison:
  - current minus backup: `0`
  - backup minus current: `0`
- Full-row multiset comparison:
  - current minus backup: `458`
  - backup minus current: `458`
- Interpretation: exactly `458` rows changed, and only the `barttorvik_trid` column changed.

### 2026-06-06 15:44:32 CDT

Prompt summary:

- For each row in `data_dir/bv_trans_compl_MAX.db` with non-null `barttorvik_trid`, match it to the equivalent-year row in:
  - `data_dir/bvt_allyears_MAX.db`
- Join constraints:
  - `bv_trans_compl_MAX.barttorvik_year = bvt_allyears_MAX.year`
  - `bv_trans_compl_MAX.barttorvik_trid = bvt_allyears_MAX.barttorvik_trid`
  - `bv_trans_compl_MAX.barttorvik_trid = bvt_allyears_MAX.pid`
- Create a new table in `bv_trans_compl_MAX.db` named:
  - `all_years_transfer_matched`
- New table should contain all columns from both source tables.

Result:

- Added repeatable script:
  - `data_dir/data_cleaning/transfer_cleaning/create_all_years_transfer_matched_table.py`
- Confirmed `bvt_allyears_MAX.pid` equals `bvt_allyears_MAX.barttorvik_trid` for every all-years row:
  - rows checked: `81,562`
  - pid/trid equal rows: `81,562`
- Created backup:
  - `data_dir/backups/bv_trans_compl_MAX.before_all_years_transfer_matched_20260606_154432.db`
- Created table:
  - `all_years_transfer_matched`
- Table structure:
  - all-years columns are prefixed with `allyears_`
  - transfer columns are prefixed with `transfer_`
  - total columns: `109`
    - `77` all-years columns
    - `32` transfer columns

Match counts:

- Transfer rows with non-null `barttorvik_trid`: `13,231`.
- Exact ID+year matches inserted into new table: `12,712`.
- Non-null transfer trid rows without equivalent-year all-years match: `519`.

Validation:

- Current `bv_trans_compl_MAX` row count: `16,897`.
- Backup `bv_trans_compl_MAX` row count: `16,897`.
- New matched table row count: `12,712`.
- Rows passing join key validation in new table: `12,712`.
- Rows failing join key validation in new table: `0`.
- Base transfer table multiset comparison vs backup:
  - current minus backup: `0`
  - backup minus current: `0`
- Interpretation: the base transfer table rows/cells were not changed; only the new derived table was added.

### 2026-06-06 Frontend Recruit Detail Edits

Prompt summary:

- Update the frontend player detail dropdown behavior.
- Show only the top 3 playtype probabilities instead of top 4.
- Allow multiple recruit/player rows to be expanded at the same time.

Result:

- Updated `frontend_site/components/PlayerDetailPanel.tsx`.
  - Changed displayed playtype probabilities from top 4 to top 3.
- Updated `frontend_site/components/PlayerTable.tsx`.
  - Replaced single `expandedId` state with a set of expanded player IDs.
  - Expanding one player no longer closes previously expanded players.
  - Clicking an already expanded player still collapses that specific player.

Validation:

- Ran `npm run build` in `frontend_site`.
- Build passed successfully.

### 2026-06-06 HS 2026 Destination Consistency Check

Prompt summary:

- Check `data_dir/hs_complete.db` for class-of-2026 recruit rows with inconsistent destination fields.
- Compare non-null/non-empty values across:
  - `committed_school`
  - `signed_school`
  - `enrolled_institution_247`
- Ignore null/empty/uncommitted values.
- Do not edit DB files.

Result:

- Checked `631` rows where `year = 2026`.
- Non-null destination counts:
  - `committed_school`: `508`
  - `signed_school`: `271`
  - `enrolled_institution_247`: `10`
- Found `1` row with a primary destination inconsistency.
- Wrote review CSV:
  - `data_dir/data_cleaning/hs_2026_school_destination_inconsistencies.csv`

Issue found:

- `player_key`: `46128489`
- `full_name`: `RJ Luis Jr.`
- `committed_school`: `LSU`
- `signed_school`: `UMass`
- `enrolled_institution_247`: null
- `current_school`: `G League`

Notes:

- `current_school` was included as context but not used as a primary inconsistency trigger because it is populated for all 2026 rows and may represent profile/current-team context rather than the signed/committed/enrolled destination fields.
- No DB files were edited.

### 2026-06-06 Frontend HS Recruit Table Cleanup

Prompt summary:

- Fix HS recruit destination display and table behavior.
- Treat prep/high-school current institutions as not being college commitments.
- Remove HS recruits from the site data if committed/signed/enrolled destinations conflict.
- Keep the displayed column name as `Committed School`, but use destination priority:
  - enrolled > signed > committed
- Replace native datalist autocomplete with cleaner autocomplete UI that only opens after typing.
- Search box should search players only.
- Team filter should be an autocomplete text filter instead of a dropdown.
- Default table display should be 20 rows with a bottom selector:
  - 10, 20, 50, 100, All
- Sort buttons should toggle ascending/descending.
- Center HS table values under their column headers.

Result:

- Updated `frontend_site/scripts/build_hs_recruits.py`.
  - Changed prediction CSV path to the active baseline output:
    - `models_dir/baseline_model_hs_playtype/jun_5_autoclass/outputs/baseline/catboost_baseline_top3_predictions.csv`
  - Changed displayed school priority to:
    - `enrolled_institution_247`
    - `signed_school`
    - `committed_school`
    - `Uncommitted`
  - Stopped using `current_school` as a college destination fallback for HS recruits.
  - Excluded recruits with conflicting non-null committed/signed/enrolled destinations.
- Regenerated `frontend_site/data/hsRecruits.ts`.
  - Generated HS recruit rows: `630`.
  - Image rows: `552`.
  - Excluded destination-conflict rows: `1`.
- Verified examples:
  - `Alex Constanza` now displays `Uncommitted`.
  - `Eric Hillsman` now displays `Uncommitted`.
  - `RJ Luis Jr.` is no longer present in generated frontend HS data.
- Updated `frontend_site/components/PlayerTable.tsx`.
  - Replaced native `datalist` with custom autocomplete popovers.
  - Player search now searches player names only.
  - Team filter is now autocomplete text input.
  - Suggestions only show after typing.
  - Added rows selector with default `20`.
  - Added real asc/desc sort toggling.
  - Centered HS columns/cell values.

Validation:

- Did not edit `data_dir/hs_complete.db`.
- Ran `npm run build` in `frontend_site`.
- Build passed successfully.

### 2026-06-06 Frontend Table Polish Follow-Up

Prompt summary:

- Restore the older, cleaner sort icon style instead of text arrow glyphs.
- Make player/team autocomplete controls work as both typing boxes and dropdown selectors.
- Further center HS table values under their headers.

Result:

- Updated `frontend_site/components/PlayerTable.tsx`.
  - Restored lucide `ArrowUpDown` sort icon.
  - Sort direction is indicated by rotating the icon instead of using text arrow symbols.
  - Autocomplete inputs now include a chevron button.
  - Typing filters suggestions.
  - Clicking the chevron opens the scrollable full suggestion list.
  - Clicking into the input alone does not open suggestions.
  - HS numeric cells use flex centering.
  - HS committed-school cells use desktop flex centering.

Validation:

- Ran `npm run build` in `frontend_site`.
- Build passed successfully.

### 2026-06-06 Frontend HS Table Alignment Fix

Prompt summary:

- Fix HS recruit table columns where row values still appeared offset from column headers.

Result:

- Updated `frontend_site/components/PlayerTable.tsx`.
- Applied grid-level centering for HS table header and row tracks using `justify-items-center`.
- Kept the player column left-aligned via `justify-self-start`.
- Removed redundant per-cell centering attempts that were not reliably lining up with grid tracks.

Validation:

- Ran `npm run build` in `frontend_site`.
- Build passed successfully.

### 2026-06-06 Evan Miya Append To Transfer Matched Table

Prompt summary:

- Existing DB/table:
  - `data_dir/bv_trans_compl_MAX.db`
  - table `all_years_transfer_matched`
- Evan Miya matched DB:
  - `data_dir/evan_miya_barttorvik_matched.db`
  - table `evan_miya_barttorvik_matched`
- Append all Evan Miya columns to `all_years_transfer_matched`.
- Join by BartTorvik trid and exact year.
- Preserve existing rows and existing columns/cells.
- Ensure year equality across transfer, all-years, and Evan Miya data.

Result:

- Added repeatable script:
  - `data_dir/data_cleaning/transfer_cleaning/append_evan_miya_to_all_years_transfer_matched.py`
- Created backup:
  - `data_dir/backups/bv_trans_compl_MAX.before_evan_miya_append_20260606_171331.db`
- Verified Evan Miya source uniqueness:
  - duplicate `bvt_barttorvik_trid` + `bvt_year` groups: `0`
- Rebuilt `all_years_transfer_matched` with existing columns plus Evan Miya columns.
- Evan Miya columns are appended with `evan_` prefixes.

Validation:

- Rows before append: `12,712`.
- Rows after append: `12,712`.
- Evan Miya matched rows: `6,923`.
- Rows without Evan Miya match: `5,789`.
- Rows passing trid/year check:
  - `evan_bvt_barttorvik_trid = allyears_barttorvik_trid`
  - `evan_bvt_year = allyears_year`
  - `evan_bvt_year = transfer_barttorvik_year`
  - count: `6,923`
- Bad Evan key rows: `0`.
- Columns before append: `109`.
- Columns after append: `237`.
- Appended Evan columns: `128`.
- Existing-column multiset comparison vs backup:
  - current minus backup: `0`
  - backup minus current: `0`
- Interpretation: existing rows and columns/cells were preserved; only Evan Miya columns were appended to the derived table.

Follow-up audit:

- User questioned why only `6,923` of `12,712` transfer/all-years matched rows received Evan Miya data.
- Audited join coverage by trid and year.

Findings:

- Of the `12,712` transfer/all-years rows:
  - same trid and same year in Evan Miya: `6,923`
  - trid exists in Evan Miya but only in other years: `2,459`
  - trid absent from Evan Miya matched DB entirely: `3,330`
- Evan Miya matched DB is not a complete copy of BartTorvik all-years.
- BartTorvik all-years vs Evan Miya same-year coverage:
  - 2018: `2,876 / 4,703` rows, `61.15%`
  - 2019: `2,801 / 4,739` rows, `59.11%`
  - 2020: `2,875 / 4,733` rows, `60.74%`
  - 2021: `2,715 / 4,970` rows, `54.63%`
  - 2022: `2,891 / 5,011` rows, `57.69%`
  - 2023: `2,951 / 5,043` rows, `58.52%`
  - 2024: `3,006 / 5,002` rows, `60.10%`
  - 2025: `2,996 / 5,060` rows, `59.21%`
  - 2026: `3,046 / 4,978` rows, `61.19%`
- Overall:
  - BartTorvik all-years rows: `81,562`
  - rows with same-year Evan Miya match: `48,662`
  - rows without same-year Evan Miya match: `32,900`

Interpretation:

- The lower transfer/Evan match count is not caused by duplicate keys or row loss in the append.
- It is caused by Evan Miya source coverage being a subset of BartTorvik all-years rows.
- Keeping the strict same-year join is still correct for feature construction; joining by trid only would leak/attach stats from the wrong season.

Follow-up removal:

- User decided Evan Miya columns are not needed for this task.
- Removed only columns prefixed `evan_` from:
  - `data_dir/bv_trans_compl_MAX.db`
  - table `all_years_transfer_matched`
- Created backup:
  - `data_dir/backups/bv_trans_compl_MAX.before_remove_evan_cols_20260606_171815.db`

Validation:

- Rows before removal: `12,712`.
- Rows after removal: `12,712`.
- Columns before removal: `237`.
- Columns after removal: `109`.
- Removed Evan columns: `128`.
- Remaining `evan_` columns: `0`.
- Remaining-column multiset comparison vs backup:
  - current minus backup: `0`
  - backup minus current: `0`
- Interpretation: only the appended Evan Miya columns were removed; all original all-years/transfer columns and rows were preserved.

### 2026-06-06 Future Role Column

Prompt summary:

- Add a derived `future_role` column to `all_years_transfer_matched` in `data_dir/bv_trans_compl_MAX.db`.
- For rows with `allyears_year < 2026`, look up the same BartTorvik trid in `bvt_allyears_MAX` for `year = allyears_year + 1`.
- Populate `future_role` from the next-season `role` only when that next-season role is non-null.
- Leave all `2026` rows blank in `future_role`.
- Do not edit any other DB files.

Result:

- Added repeatable script:
  - `data_dir/data_cleaning/transfer_cleaning/add_future_role_to_all_years_transfer_matched.py`
- Created backup:
  - `data_dir/backups/bv_trans_compl_MAX.before_future_role_add_20260606_175143.db`
- Added new column:
  - `future_role`

Validation:

- Row count unchanged: `12,712`.
- Column count increased from `109` to `110`.
- Non-null `future_role` values: `5,945`.
- `allyears_year = 2026` and `future_role IS NOT NULL`: `0`.
- Existing 109 columns compared against backup:
  - current minus backup: `0`
  - backup minus current: `0`
- Interpretation: only the new `future_role` column was added; all existing data remained unchanged.

### 2026-06-06 Transfer Role Inference Script

Prompt summary:

- Create a standalone inference script for `models_dir/transfer_playtype_prediction/transfer_role_catboost_optuna.py`.
- Run inference only on `all_years_transfer_matched` rows where `allyears_year = 2026` and `future_role` is empty.
- Use the saved CatBoost model in:
  - `models_dir/transfer_playtype_prediction/artifacts/transfer_role_catboost/catboost_transfer_role_model.cbm`
- Write a CSV with the full inference rows plus top-3 predictions and probability columns.
- Do not alter any DB files.

Result:

- Added inference script:
  - `models_dir/transfer_playtype_prediction/transfer_role_catboost_inference.py`
- Output path configured for:
  - `models_dir/transfer_playtype_prediction/outputs/transfer_role_catboost/catboost_transfer_role_future_top3_predictions.csv`

Validation:

- Syntax parsed successfully with no Python parse errors.
- No DB files were modified.

Execution:

- Ran `python3 models_dir/transfer_playtype_prediction/transfer_role_catboost_inference.py`
- Rows scored: `2,377`
- Output saved successfully to:
  - `models_dir/transfer_playtype_prediction/outputs/transfer_role_catboost/catboost_transfer_role_future_top3_predictions.csv`
- Non-fatal sandbox warnings during run:
  - Arrow `sysctlbyname` CPU feature warnings
- No DB files were modified during inference.

### 2026-06-06 Transfer Frontend Wiring

Prompt summary:

- Add the transfer portal prediction dataset to the frontend.
- Mirror the HS recruit treatment for transfers.
- On transfer views, split the team display into origin and destination.
- Remove BPR/Fit columns from the transfer table for now.
- Keep the existing centering/alignment behavior untouched.
- Do not edit `frontend_site/components/PlayerTable_copy.tsx`.

Result:

- Added transfer data generator:
  - `frontend_site/scripts/build_transfer_players.py`
- Added generated transfer dataset:
  - `frontend_site/data/transferPlayers.ts`
- Updated combined player source list:
  - `frontend_site/data/players.ts`
- Updated team search matching to include transfer destinations:
  - `frontend_site/lib/data.ts`
- Updated transfer layout in:
  - `frontend_site/components/PlayerTable.tsx`
- Updated portal page to use the transfer layout:
  - `frontend_site/app/portal/page.tsx`

Validation:

- `npm run build` passed after regeneration of the transfer dataset.
- Transfer mode now uses:
  - player
  - position
  - origin
  - destination
  - status
  - type
- Transfer status options no longer include `enrolled`.

### 2026-06-06 Transfer Height/Class Fix

Prompt summary:

- The transfer frontend was showing too many `N/A` values for height and class year.
- The correct source fields are `allyears_ht` and `allyears_yr` in the transfer prediction CSV.
- Regenerate the frontend transfer dataset so those fields render correctly.

Result:

- Updated `frontend_site/scripts/build_transfer_players.py` to read:
  - `allyears_ht` for height
  - `allyears_yr` for class year
- Regenerated:
  - `frontend_site/data/transferPlayers.ts`

Validation:

- `npm run build` passed.

### 2026-06-07 hs_to_evan_global_matched score-column apostrophe check

Prompt summary:

- Remove leading apostrophes from `name_score`, `team_score`, and `overall_match_score` in `data_dir/hs_to_evan_global_matched.csv`.

Result:

- Checked the raw CSV directly.
- No rows in those three columns contained a leading apostrophe.
- No file rewrite was needed for this prompt.

### 2026-06-07 hs_to_evan_global_matched Excel numeric coercion

Prompt summary:

- Force `name_score`, `team_score`, and `overall_match_score` in `data_dir/hs_to_evan_global_matched.csv` to open as numeric values in Excel instead of text.

Result:

- Rewrote those three columns as Excel-evaluable numeric formulas (`=...`) so Excel should treat them as numbers.
- Created a backup before rewriting the CSV.

### 2026-06-07 hs_to_evan_global_matched remaining true-row sync

Prompt summary:

- Move remaining `match_flag = TRUE` rows out of `data_dir/hs_to_evan_global_matched.csv`.
- Confirm those rows in `data_dir/hs_to_evan_global_matched.db`.

Result:

- Removed `278` `TRUE` rows from the CSV.
- Updated the corresponding DB rows to `match_flag = TRUE`.
- Final counts:
  - DB rows: `13,740`
  - DB `match_flag = TRUE`: `5,275`
- CSV rows: `7,801`
- CSV `match_flag = TRUE`: `0`

### 2026-06-07 247 transfer review TRUE-row move

Prompt summary:

- Move newly marked `match_flag = TRUE` rows from `data_dir/247_bv_transf_matches_to_review.csv` into the matched table in `data_dir/247_bv_transf_matched.db`.
- Remove those rows from the review CSV.

Result:

- Moved `2,299` TRUE rows from review into the matched table.
- Final matched-table rows: `6,663`
- Final matched-table `match_flag = TRUE`: `6,200`
- Final matched-table `247_match_year = 2026`: `1,512`
- Final review CSV rows: `2,551`
- Final review CSV `match_flag = TRUE`: `0`

### 2026-06-07 247 transfer review match_status audit

Prompt summary:

- Check whether rows with `match_status = db1_unmatched_future_role_non_null` in `data_dir/247_bv_transf_matches_to_review.csv` are already present in `data_dir/247_bv_transf_matched.db`.

Result:

- `1,481` rows in the review CSV have `match_status = db1_unmatched_future_role_non_null`.
- None of those rows are present in `transfer_247_bv_matched`.
- No files were edited for this audit.

### 2026-06-07 247 transfer future-role row promotion

Prompt summary:

- Move rows with `match_status = db1_unmatched_future_role_non_null` from `data_dir/247_bv_transf_matches_to_review.csv` into `transfer_247_bv_matched` in `data_dir/247_bv_transf_matched.db`.
- Remove those rows from the review CSV.

Result:

- Moved `1,481` rows into `transfer_247_bv_matched`.
- Final `transfer_247_bv_matched` rows: `8,144`
- Final `transfer_247_bv_matched` `match_flag = TRUE`: `6,200`
- Final `transfer_247_bv_matched` `247_match_year = 2026`: `1,512`
- Final review CSV / `matches_to_review` rows: `1,070`
- Final review CSV / `matches_to_review` `match_status = db1_unmatched_future_role_non_null`: `0`

### 2026-06-07 247 transfer future-role duplicate check

Prompt summary:

- Verify that rows promoted from `match_status = db1_unmatched_future_role_non_null` are not duplicates of already matched transfer rows.

Result:

- Checked against the current matched transfer table by the transfer-side composite key.
- No promoted future-role rows overlap with already matched transfer rows.
- No files were edited for this check.

### 2026-06-07 247 transfer height normalization

Prompt summary:

- Normalize every height column in `data_dir/247_bv_transf_matched.db` into plain foot-inch strings and remove date-like Excel renderings.

Result:

- Updated `db1_allyears_player_height`, `db1_transfer_player_height`, and `247_height` in both `transfer_247_bv_matched` and `matches_to_review`.
- All height fields now use foot-inch style strings such as `6-3`, `7-0`, or `6-10`.
- One outlier `247_height` value of `168-5` was corrected to `6-1` using the aligned all-years / transfer height values from the same row.
- Backups were created before each rewrite/fix step.

### 2026-06-07 247 transfer future_role count check

Prompt summary:

- Count non-null `future_role` values in `transfer_247_bv_matched` in `data_dir/247_bv_transf_matched.db`.

Result:

- Non-null `db1_future_role` values in `transfer_247_bv_matched`: `5,611`

### 2026-06-07 247 transfer future_role null count clarification

Prompt summary:

- Reconcile the `transfer_247_bv_matched` row counts with the number of null `future_role` values.

Result:

- `transfer_247_bv_matched` rows: `8,144`
- Non-null `db1_future_role`: `5,611`
- Null or blank `db1_future_role`: `2,533`
- `247_match_year = 2026` rows: `1,512` and all of them have null `db1_future_role` by design.

### 2026-06-07 247 transfer null future_role top ratings sample

Prompt summary:

- List 2018-2025 rows in `transfer_247_bv_matched` with null `db1_future_role`, sorted by highest `247_rating`.

Result:

- Count of 2018-2025 rows with null `db1_future_role`: `1,021`
- Top examples include:
  - Emmanuel Akot, Arizona, 2019, rating `0.98`
  - Jahvon Quinerly, Villanova, 2019, rating `0.98`
  - Jordan Brown, Nevada, 2019, rating `0.98`
  - Brandon Huntley-Hatfield, N.C. State, 2025, rating `0.98`
  - Enoch Boakye, Villanova, 2025, rating `0.98`
  - Jamir Watkins, Florida St., 2025, rating `0.98`
  - RJ Luis Jr., St. John's, 2025, rating `0.98`
  - Adam Miller, Illinois, 2021, rating `0.97`
  - Ira Lee, Arizona, 2021, rating `0.97`
  - Nimari Burnett, Texas Tech, 2021, rating `0.97`

### 2026-06-07 247 Transfer Match Review Sync

Prompt summary:

- Sync `247_bv_transf_matches_to_review.csv` with `247_bv_transf_matched.db`.
- Confirm `match_flag = true` rows in the DB and remove those confirmed rows from the CSV.
- Remove from the matched DB any non-2026 row where `match_flag = false` or `future_role` is null, while ensuring those rows are present in the review CSV.
- Leave all `247_match_year = 2026` rows in the matched DB.

Result:

- `transfer_247_bv_matched` rows: `4,469`
- `transfer_247_bv_matched` 2026 rows: `1,512`
- `matches_to_review` rows: `4,850`
- CSV and DB review-key sets are synchronized.
- Backups were created before the final sync.

### 2026-06-07 HS to Evan Unmatched Rerun With Enrolled Fallback

Prompt summary:

- The user asked where `data_dir/hs_to_evan_global_matched.csv` came from.
- The file originates from `data_dir/data_cleaning/transfer_cleaning/match_247_others.py`.
- Rerun the matching logic only on the remaining unmatched CSV rows using team-source priority:
  - `signed_school`
  - `enrolled_institution_247`
  - `committed_school`

Result:

- Recomputed the existing unmatched CSV rows with the new fallback order.
- The CSV was rewritten in place only.
- No DB files were modified.

Validation:

- CSV rows: `8,079`
- `match_flag = TRUE`: `7`
- `match_flag = FALSE`: `8,072`
- `auto_exact_100` rows: `7`
- `overall_match_score = 100`: `7`

Backup:

- `data_dir/backups/hs_to_evan_global_matched.before_unmatched_team_fallback_rerun_20260607_013406.csv`

### 2026-06-07 Match DB Integrity Audit

Prompt summary:

- Audit every matched DB for evidence of row-id-based matching or obviously bad matches.
- Do not edit any DB files.

Result:

- Reviewed the relevant match DBs and the scripts that populate them.
- No evidence found that the final match tables were built by reusing persisted row ids as semantic match keys.
- Internal row ids are used in the scripts as temporary bookkeeping keys, while actual matching is driven by names, teams, years, and DOB-based constraints.
- Most final match tables look clean under the core constraints.
- One clear outlier was found in `hs_bv_matched.db`:
  - `Keon Ambrose-Hylton` -> `Keon Ellis` at Alabama, which is a plausible bad match and should be reviewed.
- The transfer table duplicate `trid/year` groups were traced back to duplicated source transfer rows, not to row-id-based matching in the join output.

Validation:

- `hs_bv_matched.db`: `hs_year + 1 = bv_year` violations = `0`
- `hs_to_evan_global_matched.db`: `match_flag = true` rows with `overall_match_score < 70` = `0`
- `hs_to_evan_global_matched.db`: `college_year != hs_year + 1` violations = `0`
- `evan_miya_barttorvik_matched.db`: `year != bvt_year` violations = `0`
- `bv_trans_compl_MAX.db` / `all_years_transfer_matched`: `transfer_barttorvik_year != allyears_year` violations = `0`
- `bv_trans_compl_MAX.db` / `all_years_transfer_matched`: duplicated `allyears_barttorvik_trid/year` groups = `28`

### 2026-06-07 Transfer Duplicate Audit

Prompt summary:

- The user found duplicate `year||player_name||trid` keys in `all_years_transfer_matched`.
- Need to explain whether these came from row-id matching or from the source transfer table.

Result:

- Traced the duplicates back to `bv_trans_compl_MAX`.
- The same 28 `barttorvik_year/player_name/barttorvik_trid` groups are duplicated in the source transfer table as well.
- The duplicated groups are source-shape issues, not row-id-based corruption in the final matched table.
- Several groups represent multiple transfer-destination rows for the same player-season.
- At least one group contains a blank destination row plus a filled destination row, which is why the same player-season appears twice after the join.

Validation:

- Duplicate groups in `all_years_transfer_matched`: `28`
- Duplicate groups in `bv_trans_compl_MAX`: `28`
- Example duplicated groups include:
  - `Chris James` / `70778` / `2021`
  - `Seneca Knight` / `65733` / `2021`
  - `Alex Anderson` / `74401` / `2022`
  - `Jahmar Young, Jr.` / `65660` / `2023`

### 2026-06-07 Transfer Duplicate Deletion Flag

Prompt summary:

- Add `dup_del` to `all_years_transfer_matched`.
- Mark `TRUE` only on the weaker row in duplicate groups; leave ties blank.
- Do not edit any other DB contents.

Result:

- Added `dup_del` to `data_dir/bv_trans_compl_MAX.db` / `all_years_transfer_matched`.
- Flagged the weaker row in duplicate groups using a non-null cell count across the full row.
- Tied duplicate pairs were left blank as requested.

Validation:

- Total rows unchanged: `12,712`
- `dup_del = TRUE`: `9`
- `dup_del IS NULL`: `12,703`
- Duplicate groups remain present: `28`

Backup:

- `data_dir/backups/bv_trans_compl_MAX.before_dup_del_flag_20260607_005255.db`

### 2026-06-07 Transfer Duplicate Flag Expansion

Prompt summary:

- The user wanted one `dup_del = TRUE` flag for each of the 25 duplicate transfer groups they originally listed.
- If the two rows in a group have equal information, either row may be flagged.

Result:

- Expanded `dup_del` in `data_dir/bv_trans_compl_MAX.db` / `all_years_transfer_matched` so each of the 25 requested duplicate groups now has exactly one `TRUE`.
- Existing flags were preserved where already present.
- The remaining 3 duplicate groups that were not in the user’s earlier list were left untouched.

Validation:

- `dup_del = TRUE` total: `25`
- Requested duplicate groups with exactly one flag: `25`
- Unrequested duplicate groups left unchanged: `3`

Backup:

- `data_dir/backups/bv_trans_compl_MAX.before_dup_del_fill_25_20260607_005622.db`

### 2026-06-07 Transfer Duplicate Missing Three

Prompt summary:

- The user found three duplicate groups that were not flagged yet:
  - `2024||Tanahj Pettway||74789`
  - `2024||Tyree Ihenacho||72493`
  - `2026||MJ Yeager||133670`

Result:

- Added flags so each of those three groups now has one `dup_del = TRUE`.
- No other DB columns or tables were changed.

Validation:

- `dup_del = TRUE` total after correction: `28`
- The three newly added groups each have exactly one flag.

Backup:

- `data_dir/backups/bv_trans_compl_MAX.before_dup_del_fill_missing_3_20260607_005814.db`

### 2026-06-07 HS to Evan Match Flag Sync

Prompt summary:

- The CSV `data_dir/hs_to_evan_global_matched.csv` had 337 `match_flag = TRUE` rows that were present in the DB with the same keys but still marked `FALSE`.
- The user asked to safely sync those flags in the DB and then remove those rows from the CSV.

Result:

- Updated `data_dir/hs_to_evan_global_matched.db` so those 337 key-matched rows now have `match_flag = TRUE`.
- Removed the same 337 rows from `data_dir/hs_to_evan_global_matched.csv`.
- No other row values were changed.

Validation:

- DB `match_flag = TRUE` count: `5009`
- CSV `match_flag = TRUE` count after removal: `4672`
- CSV total rows after removal: `13403`

Backups:

- `data_dir/backups/hs_to_evan_global_matched.before_matchflag_sync_20260607_011407.csv`
- `data_dir/backups/hs_to_evan_global_matched.before_matchflag_sync_20260607_011407.db`

### 2026-06-07 Remove All True Rows From HS to Evan CSV

Prompt summary:

- The user wanted every `match_flag = TRUE` row removed from `data_dir/hs_to_evan_global_matched.csv`.
- The DB should not be changed.

Result:

- Removed all `match_flag = TRUE` rows from the CSV.
- Left the DB unchanged.

Validation:

- CSV rows removed: `4672`
- CSV `match_flag = TRUE` rows remaining: `0`
- CSV total rows remaining: `8731`

Backup:

- `data_dir/backups/hs_to_evan_global_matched.before_remove_all_true_20260607_011529.csv`

### 2026-06-07 HS Complete Enrolled Column Check

Prompt summary:

- The user asked to add an enrolled institution column to `hs_complete.db` if it did not already exist.
- The enrolled institution should come from the recruit profile, not the main profile.

Result:

- No schema change was needed.
- `hs_complete.db` already contains `enrolled_institution_247`.

Validation:

- Column present: `enrolled_institution_247`
- No DB edits made for this part

### 2026-06-07 HS to Evan True Sync and Removal

Prompt summary:

- The CSV `data_dir/hs_to_evan_global_matched.csv` still contained 21 `match_flag = TRUE` rows.
- The user asked to sync those flags into the DB first and then remove them from the CSV.

Result:

- Updated `data_dir/hs_to_evan_global_matched.db` so those 21 rows are now `match_flag = TRUE`.
- Removed those 21 rows from the CSV.

Validation:

- DB `match_flag = TRUE`: `5030`
- CSV `match_flag = TRUE`: `0`
- CSV total rows: `8079`

Backups:

- `data_dir/backups/hs_to_evan_global_matched.before_true_sync_and_removal_20260607_012321.csv`
- `data_dir/backups/hs_to_evan_global_matched.before_true_sync_and_removal_20260607_012321.db`

### 2026-06-06 247 Transfer Scraper Expansion

Prompt summary:

- The 247 transfer scraper was only returning about 488 rows for `year=2026`, which was too small for the full transfer portal.
- The goal was to expand the scraper without touching any DB files.
- The existing scraper should stay in the 247 scraper area only.

Result:

- Updated `scrapers_web/247_scrapers/scrape_247_transfers.py` to pull multiple 247 transfer list variants instead of only the ranked overall list:
  - `listType=3` overall
  - `listType=1` latest
  - `listType=2` position
- Added deduping by `player.key` while keeping the ranked overall row first when duplicates exist.
- Cached each list type separately under the 2026 transfer cache tree.

Validation:

- `python3 -m py_compile scrapers_web/247_scrapers/scrape_247_transfers.py` passed.
- No DB files were edited.
- This change is intended to bring the 2026 transfer pull closer to the broader historical corpus already present in `data_pulls/transfer_data_historical.csv`.

### 2026-06-06 Transfer Profile HTML Cache Script

Prompt summary:

- Create a script that caches 247 transfer player profile HTML pages from the transfer output CSV.
- The cache target should be `scrapers_web/cache/transfers/2026/profiles/`.
- Do not run the script; only write it.

Result:

- Added `scrapers_web/247_scrapers/cache_247_transfer_profiles.py`.
- The script reads `scrapers_web/247_scrapers/outputs/transfers_247_enriched_2026.csv`.
- It fetches each `player_profile_url` and caches the HTML to:
  - `scrapers_web/cache/transfers/2026/profiles/{player_key}.html`
- It also writes a small summary CSV to:
  - `scrapers_web/cache/transfers/2026/transfer_profile_cache_summary_2026.csv`

Validation:

- `python3 -m py_compile scrapers_web/247_scrapers/cache_247_transfer_profiles.py` passed.
- Script was not executed.
- Transfer cards now pull height/class from the BartTorvik all-years columns instead of the sparse transfer-only columns.

Follow-up fix:

- The raw transfer `player_profile_url` was returning 404s when fetched directly.
- The script now derives the canonical 247 player profile URL from the transfer URL first.
- If that still fails, it falls back to 247 profile discovery by player name.
- `python3 -m py_compile scrapers_web/247_scrapers/cache_247_transfer_profiles.py` passed after the fix.

### 2026-06-06 Transfer Profile Cache Rerun

Prompt summary:

- Rerun 247 transfer profile caching for all transfer years from 2018 through 2026.
- Use the structured enriched transfer CSVs as the source of truth for the final uploaded database file.
- Build a DuckDB file in `data_dir/247_transfer.db`.

Result:

- Confirmed the first five 2018 transfer profile URLs return `200` with browser-style page headers.
- Updated the cache script to use browser-style page headers for the HTML fetches instead of the transfer API headers.
- Reran the yearly cache pass for 2018-2026 successfully.
- Built `data_dir/247_transfer.db` with table `transfer_profile_cache`.
- The DuckDB table is built from the enriched yearly transfer CSVs, merged with the per-year cache summary metadata.

Validation:

- Combined row count: `7,540`
- Year counts:
  - 2018: `34`
  - 2019: `398`
  - 2020: `428`
  - 2021: `623`
  - 2022: `734`
  - 2023: `945`
  - 2024: `1,229`
  - 2025: `1,637`
  - 2026: `1,512`
- Status code counts in the final DuckDB table:
  - `200`: `7,540`
- `python3 -m py_compile` passed for the cache scripts and the DuckDB builder script.

### 2026-06-07 HS Height Excel Safety

Prompt summary:

- Update `data_dir/hs_to_evan_global_matched.csv` and `data_dir/hs_to_evan_global_matched.db`.
- Make `hs_height` safe for Excel so it does not get auto-interpreted as a date.
- Keep the inches column available as the numeric height field.

Result:

- Prefixed non-null `hs_height` values with an apostrophe in both the CSV and DuckDB table so Excel treats them as text.
- Verified that `hs_height_in` already exists in both files and left it unchanged.
- No other columns or rows were modified.

Backups:

- `data_dir/backups/hs_to_evan_global_matched.before_height_excel_safe_20260607_001058.csv`
- `data_dir/backups/hs_to_evan_global_matched.before_height_excel_safe_20260607_001058.db`

### 2026-06-07 247 Transfer DB Rebuild

Prompt summary:

- The DuckDB file `data_dir/247_transfer.db` needed the full concatenated transfer recruit output, not only cache metadata columns.
- The table should contain the enriched transfer rows across all years.

Result:

- Rebuilt `data_dir/247_transfer.db` from the yearly enriched transfer CSVs.
- `transfer_profile_cache` now contains the full concatenated transfer dataset, not just the cache-status summary.
- Added `transfer_profiles` as a duplicate table pointing at the same combined dataset for convenience.
- Wrote the combined CSV snapshot to `scrapers_web/cache/transfers/transfer_profile_cache_2018_2026.csv`.

Validation:

- Rows: `7,540`
- Year counts:
  - 2018: `34`
  - 2019: `398`
  - 2020: `428`
  - 2021: `623`
  - 2022: `734`
  - 2023: `945`
  - 2024: `1,229`
  - 2025: `1,637`
  - 2026: `1,512`
- `status_code`: `200` for all rows
- Column count in both tables: `39`

### 2026-06-06 Filter Reset Behavior

Prompt summary:

- Any time a filter changes on the frontend, the row count should reset back to 20.
- This should prevent the user from getting stuck at `All` rows after changing filters.

Result:

- Updated `frontend_site/components/PlayerTable.tsx` so every filter change resets the display count to `20`.
- This applies to:
  - search
  - position
  - class
  - status
  - team
  - conference
  - playtype
  - stars
  - min rating / min BPR
  - portal toggle

Validation:

- `npm run build` passed.

### 2026-06-07 all_years_transfer_matched future_role count

Prompt summary:

- Count non-null `future_role` values in `all_years_transfer_matched` from `bv_trans_compl_MAX.db`.

Result:

- Total rows: `12,712`
- Non-null `future_role`: `5,945`
- Null or blank `future_role`: `6,767`
- `allyears_year = 2026` rows: `2,377`

### 2026-06-07 hs_to_evan_global manual-review sync

Prompt summary:

- Move rows marked `match_flag = TRUE` in `data_dir/data_cleaning/hs_to_evan_global_manual_review.csv` into the main matched HS table.
- Update the corresponding rows in `hs_to_evan_global_matched.db`, then remove those rows from the CSV.

Result:

- Accepted rows synced into DB: `77`
- DB total rows: `13,740`
- DB `match_flag = TRUE`: `5,352`
- CSV rows remaining: `8,388`
- CSV `match_flag = TRUE`: `0`

Backups:

- `data_dir/backups/hs_to_evan_global_manual_review.before_match_sync_20260607_040303.csv`
- `data_dir/backups/hs_to_evan_global_matched.before_match_sync_20260607_040303.db`
## 2026-06-07 Evan Miya all-years rescrape

- Updated `scrapers_web/evanmiya_analytics/get_evanmiya_allyears.py` to force the Evan Miya possessions slider to `200` instead of the site default `500`.
- Added a persistent Playwright profile under `/private/tmp/evanmiya_playwright_profile` so the scraper can run in this sandbox without writing to the user home profile.
- Reran the full all-years scrape for seasons `2009-10` through `2025-26`.
- Output files:
  - `scrapers_web/evanmiya_analytics/evanmiya_output/evanmiya_player_ratings_all_years_less_poss.csv`
  - `scrapers_web/evanmiya_analytics/evanmiya_output/evanmiya_player_ratings_all_year_less_poss.db`
- Final merged shape: `48,680 x 39`
- The scraper completed all seasons and wrote per-season checkpoints plus the final CSV/DB.
## 2026-06-07 Darius Garland lookup

- Checked `scrapers_web/evanmiya_analytics/evanmiya_output/evanmiya_player_ratings_all_year_less_poss.db`.
- No exact `Darius Garland` row exists in `evanmiya_player_ratings`.
- Broader `garland` search only returned unrelated players such as `Garland Judkins`, `Tyrone Garland`, `Garland Owens`, and `Colby Garland`.
## 2026-06-07 Evan Miya possessions rerun fix

- The first lowered-possession scrape still reset to the site default after year changes, which meant the year-specific tables were not being expanded correctly.
- I moved the possessions slider application to after each year transition settles in `scrapers_web/evanmiya_analytics/get_evanmiya_allyears.py`.
- Reran the full all-years scrape again.
- Final output:
  - `scrapers_web/evanmiya_analytics/evanmiya_output/evanmiya_player_ratings_all_years_less_poss.csv`
  - `scrapers_web/evanmiya_analytics/evanmiya_output/evanmiya_player_ratings_all_year_less_poss.db`
- Final merged shape: `60,059 x 39`
- Confirmed `Darius Garland` is now present in the new DB:
  - `2018-19`, `Vanderbilt`, `basic_poss = 266`
## 2026-06-07 transfer 247 join count check

- Investigated `models_dir/transfer_playtype_prediction/outputs/match_247_transfer.py`.
- The script left-joins `transfer_247_bv_matched` onto the full prediction CSV by `allyears_pid`; it does not filter to `247_match_year = 2026`.
- Current output CSV inspection:
  - rows: `2,377`
  - non-null `247_player_key`: `1,674`
  - non-null `247_match_year = 2026`: `965`
- `transfer_247_bv_matched` itself has:
  - total rows: `8,144`
  - `247_match_year = 2026` rows: `1,512`
  - non-null `247_player_key` rows: `6,663`
- There is one duplicated `allyears_pid` in the prediction input (`133670` appears twice), but that only explains a single extra row, not the larger count gap.
## 2026-06-07 transfer 247 enrichment fix

- Inspected `models_dir/transfer_playtype_prediction/outputs/match_247_transfer.py`.
- The inference CSV is 2026-only already; the confusion came from the 247 enrichment join attaching historical 247 rows from other years when joining by PID alone.
- Fixed the script so it only enriches from `transfer_247_bv_matched` rows where `"247_match_year" = 2026`.
- Also fixed the input/output paths to resolve relative to the script file, so the join script runs from its own directory reliably.
- Reran the join.
- Result:
  - input rows: `2,377`
  - output rows: `2,377`
  - rows with matched `247_player_key`: `1,512`
  - added 247 columns: `41`
- Output written to:
  - `models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions_with_247_cols.csv`
## 2026-06-07 frontend transfer enrichment update

- Updated the frontend transfer generator to read the enriched transfer CSV with 247 columns:
  - `models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions_with_247_cols.csv`
- Added transfer profile image extraction from:
  - `scrapers_web/cache/transfers/2026/profiles`
- Populated transfer cards with 247 fields:
  - position, height fallback, weight, stars, rating, rank, and 247 status
- Fixed the HS table row alignment bug by restoring the committed-school cell in the HS row render.
- Updated the transfer row layout to include stars and rating columns.
- Added transfer metrics in the detail panel for:
  - 247 rank, stars, rating, status, weight, and height
- Regenerated:
  - `frontend_site/data/transferPlayers.ts`
- Validation:
  - `python3 -m py_compile frontend_site/scripts/build_transfer_players.py`
  - `npm run build`

### 2026-06-07 transfer height and sort control tweak

- Changed the transfer generator height precedence so `allyears_ht` is used first, with 247 height only as a fallback.
- Added sortable transfer `Stars` and `Rating` headers in the transfer table, using the same arrow behavior as the HS table.
- Updated the transfer sort key set so those two columns can sort ascending/descending.
- Regenerated:
  - `frontend_site/data/transferPlayers.ts`
- Validation:
  - `python3 -m py_compile frontend_site/scripts/build_transfer_players.py`
  - `npm run build`

### 2026-06-07 transfer status source and exclusion tweak

- Excluded `Cole Alexander` from Fairleigh Dickinson from the generated transfer frontend data so the site no longer displays that bad match.
- Updated the transfer table status cell to source from `transfer_247_status` so 247 values like `Enrolled` render correctly instead of collapsing to the internal entered/committed enum.
- Expanded the transfer status filter options to include `enrolled` and `withdrawn`.
- Regenerated:
  - `frontend_site/data/transferPlayers.ts`
- Validation:
  - `python3 -m py_compile frontend_site/scripts/build_transfer_players.py`
  - `npm run build`

### 2026-06-07 transfer 247 field regeneration fix

- Reverted the transfer data generator back to row-wise `iterrows()` access so the `247_*` columns survive the build.
- This fixed the earlier regression where `itertuples()` silently renamed digit-prefixed 247 columns and dropped transfer stars/rating/rank/image fields from the generated frontend data.
- Kept the transfer height precedence fix:
  - `allyears_ht` first
  - 247 height as fallback
- Transfer `Stars` and `Rating` remain sortable with the same arrow affordance as the HS table.
- Regenerated:
  - `frontend_site/data/transferPlayers.ts`
- Validation:
  - `python3 -m py_compile frontend_site/scripts/build_transfer_players.py`
  - `npm run build`

### 2026-06-07 transfer status filter fix

- Updated the transfer table status filter so it uses `transfer_247_status` instead of the generic portal status when `playerMode === "transfer"`.
- Added a `withdrawn` badge variant so the transfer table can render the full 247 status set without collapsing everything into entered/committed.
- Kept the HS table untouched.
- Files changed:
  - `frontend_site/components/PlayerTable.tsx`
  - `frontend_site/components/StatusBadge.tsx`
  - `frontend_site/data/players.ts`
- Validation:
  - `python3 -m py_compile frontend_site/scripts/build_transfer_players.py`

### 2026-06-07 11:05:45 CDT Evan Miya less-poss DB compatibility audit

- Compared `data_dir/evanmiya_player_ratings_all_year_less_poss.db` against `data_dir/evanmiya_player_ratings_all_years.db`.
- Both DBs have the same table name, column order, column count, and column types:
  - table: `evanmiya_player_ratings`
  - columns: 39
- Row counts:
  - default/all-years DB: 48,680
  - less-poss DB: 60,059
  - net added rows: 11,379
- The less-poss DB is not an exact row-level superset of the default DB:
  - exact distinct rows from default missing in less-poss: 45,845
  - exact distinct rows in less-poss not in default: 57,224
  - shared natural keys by `season/year/name/team`: 48,622
  - default natural keys missing from less-poss: 58
  - less-poss natural keys not in default: 11,437
- Among shared natural keys, only `rank` changed; player/team metrics were unchanged for the matched player-season rows.
- Possession ranges:
  - default DB min `basic_poss` / `advanced_poss`: 400
  - less-poss DB min `basic_poss` / `advanced_poss`: 200
- Conclusion: downstream code can treat the less-poss DB as schema-compatible, but not as an exact append-only superset because rank is recomputed and 58 old natural keys are absent.

### 2026-06-07 11:13:16 CDT HS-to-Evan unmatched-only matching script

- Located the original full-run HS-to-Evan global matcher at `data_dir/data_cleaning/transfer_cleaning/match_247_others.py`.
- Added a safer unmatched-only script at `data_dir/data_cleaning/transfer_cleaning/match_hs_to_evan_unmatched_only.py`.
- The new script:
  - reads current match status from `data_dir/hs_to_evan_global_matched.db`
  - processes only rows where `match_flag` is not true
  - excludes Evan Miya player-season rows already attached to confirmed HS matches
  - uses the less-possession Evan Miya DB as the candidate source
  - enforces `hs_year + 1 = evan year`
  - scores HS full name vs Evan name and HS signed/enrolled/committed school vs Evan team
  - uses global assignment per HS year to avoid duplicate Evan candidate assignments
  - writes only `data_dir/data_cleaning/hs_to_evan_unmatched_global_review.csv`
- No DB files were edited.
- Validation:
  - `python3 -m py_compile data_dir/data_cleaning/transfer_cleaning/match_hs_to_evan_unmatched_only.py`

### 2026-06-07 11:16:56 CDT HS-to-Evan unmatched-only 2026 exclusion

- Updated `data_dir/data_cleaning/transfer_cleaning/match_hs_to_evan_unmatched_only.py` so unmatched HS rows with `hs_year = 2026` are excluded before assignment.
- Reason: 2026 recruits have not played the target college season yet and should not be included in the Evan Miya matching pass.
- No DB files were edited.
- Validation:
  - `python3 -m py_compile data_dir/data_cleaning/transfer_cleaning/match_hs_to_evan_unmatched_only.py`

### 2026-06-07 11:42:18 CDT New less-possession Evan Miya to unmatched BartTorvik matching

- Added and ran `data_dir/data_cleaning/evan_bv_matching/match_new_less_poss_evan_to_unmatched_bvt.py`.
- Purpose:
  - Match Evan Miya rows newly available in `data_dir/evanmiya_player_ratings_all_year_less_poss.db` against unmatched BartTorvik all-years rows.
  - Append only exact `100/100/100` matches to `data_dir/evan_miya_barttorvik_matched.db`.
  - Send all non-exact matches to manual review.
- Matching logic:
  - New Evan rows are identified by natural key `season/year/name/team` not already present in the matched DB.
  - Already matched BartTorvik rows are excluded by `bvt_year` + `bvt_barttorvik_trid`.
  - Hard constraint: Evan `year = BartTorvik year`.
  - Score uses Evan `name` vs BartTorvik `player_name` and Evan `team` vs BartTorvik `team`.
  - Global assignment is solved independently within each year.
  - Row ids are only bookkeeping after assignment; they are not semantic match keys.
- Inputs:
  - Existing matched rows: 48,662.
  - Less-possession Evan rows: 60,059.
  - New less-possession Evan rows processed: 11,414.
  - Unmatched BartTorvik rows available: 32,900.
- Outputs:
  - Auto-exact CSV: `data_dir/evan_bv_less_poss_auto_exact_appended.csv`
  - Review CSV: `data_dir/evan_bv_less_poss_lower_confidence_review.csv`
  - Backup before append: `data_dir/backups/evan_miya_barttorvik_matched.before_less_poss_append_20260607_114113.db`
- Results:
  - Assignments generated: 11,414.
  - Auto-exact rows appended to `evan_miya_barttorvik_matched`: 8,326.
  - Review rows written: 3,088.
  - New DB row count: 56,988.
- Validation:
  - New appended rows with exact `match_score/name_score/team_score = 100/100/100`: 8,326.
  - New rows with year mismatch: 0.
  - Duplicate `bvt_year/bvt_barttorvik_trid` groups after append: 0.
  - Backup rows missing from current DB: 0.
  - Current rows not in backup: 8,326, matching the append count.

### 2026-06-07 12:05:22 CDT Evan/BVT less-poss manual review confirmations

- Processed `data_dir/evan_bv_less_poss_lower_confidence_review.csv` after manual review.
- Treated only `match_flag = TRUE` rows as confirmed matches.
- Appended confirmed full rows to `data_dir/evan_miya_barttorvik_matched.db` / `evan_miya_barttorvik_matched`.
- Did not insert the helper CSV-only `match_flag` column because the DB schema does not contain it.
- Rewrote the review CSV with unmatched/unconfirmed rows only.
- Backups:
  - `data_dir/backups/evan_bv_less_poss_lower_confidence_review.before_confirmed_append_20260607_120434.csv`
  - `data_dir/backups/evan_miya_barttorvik_matched.before_manual_review_confirmed_append_20260607_120434.db`
- Results:
  - Confirmed rows appended: 3,035.
  - Review CSV rows remaining: 53.
  - DB rows before: 56,988.
  - DB rows after: 60,023.
- Validation:
  - Existing backup rows missing from current DB: 0.
  - Current rows not in backup: 3,035.
  - Duplicate `bvt_year/bvt_barttorvik_trid` groups after append: 0.
  - Remaining review CSV `match_flag = TRUE` rows: 0.

### 2026-06-07 12:18:38 CDT HS/Evan unmatched review confirmations

- Processed `data_dir/hs_to_evan_unmatched_global_review.csv` after manual review.
- Confirmed rows were synced into existing rows in `data_dir/hs_to_evan_global_matched.db`; no rows were appended.
- For synced rows, the script updated match fields and full `college_*` Evan Miya columns from `data_dir/evanmiya_player_ratings_all_year_less_poss.db`.
- Backups:
  - `data_dir/backups/hs_to_evan_unmatched_global_review.before_confirmed_sync_20260607_121756.csv`
  - `data_dir/backups/hs_to_evan_global_matched.before_unmatched_review_confirmed_sync_20260607_121756.db`
- Results:
  - `match_flag = TRUE` rows requested in review CSV: 1,813.
  - Synced into DB: 1,812.
  - One row was left in the review CSV because the DB already had `match_flag = TRUE` for that `hs_row_id` but pointed to a different Evan row:
    - `hs_row_id = 9019`, `James Johnson`, existing DB match to `James Johnson / Quinnipiac`, review CSV candidate `James Johnson / Louisiana Tech`.
  - Review CSV rows remaining: 5,945.
- Final DB counts:
  - total rows: 13,740.
  - 2026 rows: 631.
  - non-2026 rows: 13,109.
  - matched total: 7,164.
  - matched 2026: 0.
  - matched non-2026: 7,164.
  - unmatched total: 6,576.
  - unmatched 2026: 631.
  - unmatched non-2026: 5,945.
- Validation:
  - DB row count before/after stayed 13,740.
  - Matched year constraint violations: 0.
  - Remaining review CSV `match_flag = TRUE` rows: 1, the James Johnson conflict noted above.

### 2026-06-07 12:31:05 CDT HS/Evan additional review confirmations

- Processed another set of manually confirmed rows in `data_dir/hs_to_evan_unmatched_global_review.csv`.
- Ignored the James Johnson conflict row as requested; it remains in the review CSV with `match_flag = False` and was not written over the existing DB match.
- Synced confirmed rows into existing rows in `data_dir/hs_to_evan_global_matched.db`; no rows were appended.
- Updated match fields and full `college_*` Evan Miya columns from `data_dir/evanmiya_player_ratings_all_year_less_poss.db`.
- Backups:
  - `data_dir/backups/hs_to_evan_unmatched_global_review.before_confirmed_sync_20260607_123105.csv`
  - `data_dir/backups/hs_to_evan_global_matched.before_unmatched_review_confirmed_sync_20260607_123105.db`
- Results:
  - Confirmed distinct HS recruits synced: 25.
  - Review CSV rows remaining: 5,920.
  - Remaining review CSV `match_flag = TRUE` rows: 0.
- Final DB counts:
  - total rows: 13,740.
  - matched total: 7,189.
  - matched non-2026: 7,189.
  - 2026 rows: 631.
  - matched 2026: 0.
  - unmatched total: 6,551.
- Validation:
  - DB row count stayed 13,740.
  - Matched year constraint violations: 0.
  - Distinct newly matched HS recruits vs backup: 25.

### 2026-06-07 12:40:47 CDT HS/Evan remove non-2026 unmatched from matched DB

- Moved the storage responsibility for non-2026 unmatched HS/Evan rows out of `data_dir/hs_to_evan_global_matched.db`.
- Verified before deleting that every non-2026 unmatched `hs_row_id` in the DB was already represented in `data_dir/hs_to_evan_unmatched_global_review.csv`.
- Did not append duplicate rows to the manual review CSV because it already contained the exact 5,920 non-2026 unmatched HS rows.
- Deleted only rows from `hs_to_evan_global_matched.db` where `match_flag IS DISTINCT FROM TRUE` and `hs_year <> 2026`.
- Backups:
  - `data_dir/backups/hs_to_evan_global_matched.before_remove_unmatched_non2026_20260607_124047.db`
  - `data_dir/backups/hs_to_evan_unmatched_global_review.before_remove_unmatched_non2026_20260607_124047.csv`
- Results:
  - DB rows before: 13,740.
  - Deleted non-2026 unmatched rows: 5,920.
  - DB rows after: 7,820.
  - Matched rows remaining: 7,189.
  - Unmatched non-2026 rows remaining in DB: 0.
  - Unmatched 2026 rows remaining in DB: 631.
- Validation:
  - Manual review CSV rows: 5,920.
  - Deleted row ids were fully covered by the manual review CSV.
  - Matched year constraint violations: 0.

### 2026-06-07 12:53:51 CDT HS/BV/Evan combined match DB

- Created `data_dir/hs_bv_evan_match.db`.
- Superseded by the corrected full-outer rebuild below.
- Source DBs were not edited:
  - `data_dir/hs_to_evan_match.db` / `hs_to_evan_global_matched`
  - `data_dir/hs_bv_matched.db` / `hs_bv_matched`
- Join strategy:
  - Left join from HS/Evan rows to active HS/BV matched rows using `hs_player_key`.
  - No row-order or row-id matching was used.
  - HS/Evan columns keep their existing names.
  - All HS/BV source columns are included with `bvsrc_` prefixes to avoid overwriting HS/Evan columns.
  - Added helper booleans `has_bv_match` and `has_evan_match`.
- Output tables:
  - `hs_bv_evan_match`
  - `non_2026_evan_without_bv_match`
  - `db_metadata`
- Results:
  - Output rows: 7,820.
  - Rows with Evan match: 7,189.
  - Rows with active BV match: 6,893.
  - Rows without active BV match: 927.
  - 2026 rows: 631.
  - 2026 rows without BV match: 631.
  - Non-2026 rows without active BV match: 296.
- Validation:
  - Duplicate `hs_player_key` rows in output: 0.
  - Evan year constraint violations: 0.
  - 2026 rows with Evan match: 0.
  - 2026 rows with active BV match: 0.

### 2026-06-07 12:57:31 CDT HS/BV/Evan corrected full-outer rebuild

- Rebuilt `data_dir/hs_bv_evan_match.db` after confirming the first build incorrectly used HS/Evan as the base table.
- Source DBs were not edited:
  - `data_dir/hs_bv_matched.db`
  - `data_dir/hs_to_evan_match.db`
- Key overlap before rebuild:
  - HS/BV active rows: 8,999.
  - HS/Evan rows: 7,820.
  - Shared `hs_player_key` rows: 6,893.
  - HS/BV rows without HS/Evan row: 2,106.
  - HS/Evan rows without active HS/BV row: 927.
  - HS/BV 2026 rows: 0.
  - HS/Evan 2026 rows: 631.
- Corrected output:
  - Join type: full outer join on `hs_player_key`.
  - Leading `hs_*` identifier columns are coalesced from BV/Evan sources.
  - Complete HS/BV source columns are prefixed `bvsrc_`.
  - Complete HS/Evan source columns are prefixed `evsrc_`.
  - Added helper columns: `has_bv_match`, `has_evan_row`, `has_evan_match`, `source_presence`.
- Output tables:
  - `hs_bv_evan_match`
  - `evan_without_bv_match`
  - `bv_without_evan_row`
  - `db_metadata`
- Results:
  - Output rows: 9,926.
  - Rows in both sources: 6,893.
  - BV-only rows: 2,106.
  - Evan-only rows: 927.
  - 2026 rows included from HS/Evan side: 631.
  - Non-2026 Evan-only rows: 296.
- Validation:
  - Duplicate `hs_player_key` rows in output: 0.
  - Evan year constraint violations: 0.

### 2026-06-07 12:59:39 CDT HS/BV/Evan remove 2026 inference rows

- Removed the 631 `hs_year = 2026` rows from `data_dir/hs_bv_evan_match.db` only.
- Source DBs were not edited.
- Backup:
  - `data_dir/backups/hs_bv_evan_match.before_remove_2026_20260607_125939.db`
- Results:
  - Rows before: 9,926.
  - Rows after: 9,295.
  - 2026 rows remaining: 0.
  - Rows in both HS/BV and HS/Evan: 6,893.
  - BV-only rows: 2,106.
  - non-2026 Evan-only rows: 296.
- Validation:
  - Duplicate `hs_player_key` rows in output: 0.

### 2026-06-07 13:04:39 CDT HS/Evan remove 2026 rows from match DB

- Removed the 631 `hs_year = 2026` rows from `data_dir/hs_to_evan_match.db` / `hs_to_evan_global_matched`.
- No other DB files were edited.
- Backup:
  - `data_dir/backups/hs_to_evan_match.before_remove_2026_20260607_130439.db`
- Results:
  - Rows before: 7,820.
  - 2026 rows removed: 631.
  - Rows after: 7,189.
  - Matched rows after: 7,189.
  - 2026 rows remaining: 0.
- Validation:
  - Evan year constraint violations: 0.

### 2026-06-07 13:22:00 CDT CollegeBasketballData lineup API puller

- Added rate-limit-aware CollegeBasketballData lineup pull tooling in `data_pulls/cbb_data_api`.
- Files added:
  - `data_pulls/cbb_data_api/pull_cbb_lineups.py`
  - `data_pulls/cbb_data_api/README.md`
- API key handling:
  - The script reads `CBBD_API_KEY` from the shell environment.
  - The API key is not hard-coded into the script or README.
- Request controls:
  - Uses Bearer auth.
  - Caches raw `/teams` and `/lineups/team` responses.
  - Maintains resumable state in `state/lineup_pull_state.json`.
  - Logs request status in `logs/request_log.jsonl`.
  - Enforces `--max-requests`.
  - Uses `--min-delay` between calls.
  - Retries transient `429` and `5xx` responses with backoff.
- Availability controls:
  - Defaults to skipping lineup calls before season `2024`, because public CollegeBasketballData notes indicate lineup/substitution data starts with the 2023-24 season.
  - Supports `--allow-pre-availability` if an older season probe is intentionally needed.
  - Supports `--empty-season-probe-limit` to stop a season after several empty lineup responses.
- Outputs when run:
  - `raw/teams_{season}.json`
  - `raw/lineups_{season}_{team_slug}.json`
  - `outputs/cbb_lineups_all.csv`
  - `outputs/cbb_lineups_all.duckdb`
- Dry-run validation:
  - Command run: `python3 data_pulls/cbb_data_api/pull_cbb_lineups.py --start-season 2010 --end-season 2026 --dry-run`
  - API calls made: 0.
  - Seasons requested: 2010-2026.
  - Seasons skipped with no API calls: 2010-2023.
  - Lineup seasons planned: 2024-2026.
  - Estimated lineup calls: 900.
  - Estimated uncached calls including team-list calls: 903.

### 2026-06-07 14:10:00 CDT CollegeBasketballData lineup API pull run

- Ran the CollegeBasketballData lineup pull using the provided API key with request-budget controls.
- API key was passed via `CBBD_API_KEY` environment variable and was not written into project files.
- Initial run:
  - Started with `--start-season 2010 --end-season 2026 --max-requests 950 --min-delay 1.25`.
  - Skipped known-empty seasons 2010-2023 without API calls.
  - Cached `/teams` responses for 2024, 2025, and 2026.
  - Stopped the run after a local DuckDB CSV parsing issue appeared on names containing commas, such as `Kevin Cross, Jr.`.
  - The API calls themselves were succeeding; the issue was local CSV-to-DuckDB conversion.
- Code fix:
  - Patched `write_duckdb()` in `data_pulls/cbb_data_api/pull_cbb_lineups.py` to explicitly set CSV delimiter, quote, escape, `strict_mode=false`, and `null_padding=true`.
  - Rebuilt outputs from cached raw JSON so no successful API responses were lost.
- Resume run:
  - Resumed with `--max-requests 500 --min-delay 1.25` to stay below the 1,000 request/month free-tier cap.
  - Stopped at the script request cap.
  - The final budget-exhausted pseudo-failure was cleaned from state because no request was made for that team.
- Final outputs:
  - Raw cached lineup files: 983.
  - Request log lines: 986, including team-list calls.
  - CSV: `data_pulls/cbb_data_api/outputs/cbb_lineups_all.csv`.
  - DuckDB: `data_pulls/cbb_data_api/outputs/cbb_lineups_all.duckdb`.
  - State: `data_pulls/cbb_data_api/state/lineup_pull_state.json`.
- Final coverage:
  - 2024: 362 teams, 63,181 lineup rows.
  - 2025: 364 teams, 62,980 lineup rows.
  - 2026: 257 teams, 56,689 lineup rows.
  - Total completed team-season pulls: 983.
  - Total lineup rows: 182,850.
  - Empty responses: 0.
  - Failed responses: 0.
- Validation:
  - CSV row count: 182,850.
  - DuckDB row count: 182,850.
  - Request usage remained below the 1,000 request free-tier limit.

### 2026-06-07 15:30:00 CDT Frontend HS BPR column

- User requested a narrow frontend update on the Players page HS table only:
  - add high school BPR next to the existing HS Rating column,
  - keep the existing visual theme and centering intact,
  - remove the inert `In Portal` button from the transfer-mode table controls,
  - keep RJ Luis Jr. out of the HS data.
- Updated the frontend data generator:
  - `frontend_site/scripts/build_hs_recruits.py`
  - It now merges `models_dir/hs_bpr/catboost_model/catboost_dual_bpr_inference_outputs/dual_bpr_inference_THISONE/dual_bpr_predictions.csv` into the existing HS playtype mock data by `player_key`.
  - It stores the new value as `hs_bpr` without changing the transfer dataset or the existing HS playtype fields.
  - RJ Luis Jr. (`player_key = 46128489`) remains excluded from the generated HS mock data per request.
- Updated frontend types and rendering:
  - `frontend_site/data/players.ts`
  - `frontend_site/components/PlayerTable.tsx`
  - The HS table now shows a sortable `BPR` column immediately after `Rating`.
  - The new sort key supports ascending/descending toggling like the other headers.
  - The `In Portal` button is no longer rendered on the transfer-mode table controls.
- Regenerated the mock HS dataset:
  - `frontend_site/data/hsRecruits.ts`
  - Final generated HS recruit count: 630.
  - Image coverage stayed at 552 players with images.
- Validation:
  - The BPR merge uses `player_key` and preserves the existing HS playtype payload.
  - The HS table generation still uses the prior destination cleanup rule, but the only excluded HS recruit in this pass remains RJ Luis Jr., as requested.

### 2026-06-07 18:06:45 CDT Evan backfill for `table1_with_next_year_bpr`

- User requested a targeted backfill for blank `evan_` fields in `data_dir/table1_with_next_year_bpr.db` using the name/year/team signals already present in the `247_` and `allyears_` columns.
- Implemented a dedicated matcher:
  - `data_dir/data_cleaning/evan_bv_matching/backfill_evan_columns_from_247_allyears.py`
  - It reads the target table and `data_dir/evanmiya_player_ratings_all_year_less_poss.db`, blocks matches by year, and uses one-to-one global assignment within each year.
  - It scores source rows against Evan rows using the `247_` / `allyears_` name variants, the `247_` / `allyears_` / transfer-old team fields, and a stricter confidence gate.
  - It preserves duplicate avoidance by assigning each matched Evan source row to at most one target row.
- Type handling:
  - `evan_advanced_class` was coerced to string during the overwrite path because the source values are text grades (`FR`, `SO`, `JR`, `SR`) while the target table had that column typed as integer.
- Output artifacts:
  - Backup DB: `data_dir/backups/table1_with_next_year_bpr.before_evan_backfill_20260607_180645.db`
  - Match CSV: `data_dir/data_cleaning/evan_bv_matching/evan_backfill_matches.csv`
- Validation:
  - 52 rows were matched and filled successfully.
  - All matches were in 2026 in this pass.
  - The rewritten table now has 2,825 blank `evan_name` rows remaining.
  - The backup file was created before the overwrite, so the original table state is recoverable.

### 2026-06-07 18:15:08 CDT Evan backfill normalization correction

- Revisited the Evan backfill after the initial pass only filled 52 rows.
- Root cause:
  - The matcher normalized the Evan names/teams but was scoring raw `247_` and `allyears_` source strings against those normalized Evan fields.
  - This caused obvious exact rows such as `A'lahn Sumler` and initials-heavy names to score too low.
- Script updates:
  - `data_dir/data_cleaning/evan_bv_matching/backfill_evan_columns_from_247_allyears.py`
  - Normalizes all source-side name and team variants before scoring.
  - Adds team aliases for common cases such as `LIU` to `Long Island`, `BYU`, `UMass`, and `* St.` to `* State`.
  - Changes duplicate prevention to use the real Evan key `(evan_year, evan_name, evan_team)` instead of the mixed-convention `evan_evan_row_id`.
- Backfill runs:
  - First corrected run filled 985 more rows.
  - A weak duplicate fill for `Zack Davidson` -> `Nick Davidson` was cleared after validation.
  - Second corrected run filled 242 more rows after removing the false numeric row-id exclusion.
- Output artifacts:
  - Backup before broad corrected run: `data_dir/backups/table1_with_next_year_bpr.before_evan_backfill_20260607_181223.db`
  - Backup before duplicate repair: `data_dir/backups/table1_with_next_year_bpr.before_clear_duplicate_zack_davidson_20260607_181434.db`
  - Backup before final corrected run: `data_dir/backups/table1_with_next_year_bpr.before_evan_backfill_20260607_181508.db`
  - Latest run CSV: `data_dir/data_cleaning/evan_bv_matching/evan_backfill_matches.csv`
  - Cumulative backfill CSV: `data_dir/data_cleaning/evan_bv_matching/evan_backfill_matches_cumulative.csv`
  - Remaining 2026 review CSV: `data_dir/data_cleaning/evan_bv_matching/evan_backfill_unmatched_2026_review.csv`
- Final validation:
  - Cumulative rows filled by this backfill method: 1,278.
  - 2026 rows filled by this backfill method: 1,255.
  - Remaining blank `evan_name` rows in `table1_with_next_year_bpr`: 1,599.
  - Remaining blank 2026 rows: 257.
  - Duplicate check by `(evan_year, evan_name, evan_team)` returns 0 duplicates.

### 2026-06-07 19:05:21 CDT Append missing 2026 transfer rows into `table1_with_next_year_bpr`

- User noted that `data_dir/bv_trans_compl_MAX.db` table `all_years_transfer_matched` had 2,377 2026 transfer rows, while `data_dir/table1_with_next_year_bpr.db` only had 1,512 rows when querying 2026.
- Implemented a dedicated append script:
  - `data_dir/data_cleaning/transfer_cleaning/append_missing_2026_transfers_to_table1.py`
  - It compares 2026 source rows against target 2026 rows using `allyears_pid`, `allyears_barttorvik_trid`, and `transfer_barttorvik_trid`.
  - It identified 865 source rows missing from the target by all three identifiers.
  - It appends those rows into the target table, preserving the shared `allyears_`, `transfer_`, `future_role`, and `dup_del` source columns.
  - Target-only columns such as `247_`, `evan_`, and `next_year_` are inserted as null.
- Output artifacts:
  - Backup DB: `data_dir/backups/table1_with_next_year_bpr.before_missing_2026_transfer_append_20260607_190521.db`
  - Appended-row CSV: `data_dir/data_cleaning/transfer_cleaning/missing_2026_transfers_appended_to_table1.csv`
- Validation:
  - Source 2026 rows: 2,377.
  - Target 2026 rows before append: 1,512.
  - Rows appended: 865.
  - Target 2026 rows after append: 2,377.
  - Remaining missing source rows by PID/TRID comparison: 0.

### 2026-06-07 19:18:00 CDT Frontend transfer BPR column

- User requested a narrow frontend update to add transfer BPR predictions to the transfer-mode Players table without changing the existing look or other data.
- Updated transfer data generation:
  - `frontend_site/scripts/build_transfer_players.py`
  - It now reads `models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/dual_transfer_bpr_inference_2026_20260607_190712/dual_transfer_bpr_predictions_2026.csv`.
  - It merges `pred_next_year_basic_bpr` into the transfer frontend rows as `transfer_bpr`.
  - The merge key is `transfer_row_number + allyears_barttorvik_trid`; this keeps BartTorvik TRID in the identifier while avoiding a one-to-many merge on the duplicated `MJ Yeager` TRID.
  - It also stores `transfer_barttorvik_trid` on each generated frontend transfer row for traceability.
- Updated frontend types and rendering:
  - `frontend_site/data/players.ts`
  - `frontend_site/components/PlayerTable.tsx`
  - Transfer-mode table now has a sortable `BPR` column after `Rating` and before `Type`.
  - Sorting uses the same up/down arrow `SortButton` pattern as the existing HS and rating columns.
- Regenerated transfer frontend data:
  - `frontend_site/data/transferPlayers.ts`
  - Displayed transfer player count: 2,376.
  - Transfer rows with `transfer_bpr`: 2,376.
  - Count remains 2,376 because the existing builder exclusion for `Cole Alexander` remains in place.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:50:00 CDT Simulator UX refactor

- User requested a simulator UX pass inspired by a roster-management workflow while keeping the existing site theme.
- Rebuilt `frontend_site/components/PortalSimulator.tsx`:
  - Replaced the fixed team `<select>` with a searchable typeahead/dropdown.
  - Team options are built from all institutions appearing in site player data plus existing `teams.ts` entries.
  - Removed the style/needs summary card to save vertical space.
  - Kept the top metric cards but changed roster capacity presentation to 15 roster spots.
  - Added a two-mode workbench toggle:
    - `Current Roster`
    - `Browse Portal`
  - `Current Roster` now uses a defined scrollable roster box with Stay/Leave selectors.
  - `Browse Portal` is a compact portal/HS target browser with `Transfers`, `High School`, and `Both` toggles.
  - Added an `Incoming Players` card that shows selected additions and allows quick removal.
  - Added a projected depth chart grouped by natural `position`:
    - Guards: `PG`, `SG`, `CG`
    - Wings: `SF`, `PF`
    - Bigs: `C`
  - Incoming players in the projected depth chart are highlighted green with a `+` prefix.
  - Added a team skill radar card that aggregates available player skill percentiles across the projected roster and falls back to 50 when no values are available.
- Updated roster limit metadata:
  - `frontend_site/data/teams.ts`
  - Changed mock team roster limits from 13 to 15.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:35:00 CDT Transfer skill radar and PID-matched season stats

- User requested extending the Returning radar experience to as many transfer players as possible without disturbing existing transfer dropdown content.
- Updated transfer data generation:
  - `frontend_site/scripts/build_transfer_players.py`
  - Uses transfer BPR inference `allyears_pid` as the BartTorvik PID/TRID.
  - Joins skill percentiles from `data_dir/player_percentile/cluster_percentile_outputs/players_group_percentiles_from_db.csv` by `allyears_pid = bvt_pid`.
  - Emits the same optional `skill_*_percentile` fields already used by Returning players.
- Added PID-matched transfer season stats:
  - Source DB: `data_dir/evan_miya_barttorvik_matched.db`.
  - Source table: `evan_miya_barttorvik_matched`.
  - Match rule: `year = 2026` and `allyears_pid = bvt_pid`.
  - Added `season_basic_bpr`, `season_gp`, `season_mp`, `season_oreb`, `season_dreb`, `season_treb`, `season_ast`, `season_stl`, `season_blk`, `season_pts`, and `season_ft_pct` when matched.
- Regenerated transfer frontend data:
  - `frontend_site/data/transferPlayers.ts`.
  - Transfer rows with BPR predictions: 2,376.
  - Transfer rows with all five non-null skill percentiles: 1,841.
  - Transfer rows with PID-matched 2026 season stats: 1,845.
- Updated transfer dropdown rendering:
  - `frontend_site/components/PlayerDetailPanel.tsx`.
  - Existing transfer profile, playtype probability, and `247 Rank`/`247 Stars` cards remain in place.
  - Transfer season stats strip and animated skill radar are appended below existing transfer dropdown content when data exists.
  - Returning and HS behavior was not changed by this update.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:25:00 CDT Returning skill percentile radar

- User requested a visually stronger Returning dropdown with a pentagon radar plot for skill percentiles.
- Data source:
  - `data_dir/player_percentile/cluster_percentile_outputs/players_group_percentiles_from_db.csv`.
  - Joined to Returning players by `bvt_pid`.
  - Percentile fields used:
    - `spacing_percentile`
    - `facilitating_percentile`
    - `rim_protection_percentile`
    - `defense_percentile`
    - `finishing_percentile`
- Updated Returning generation:
  - `frontend_site/scripts/build_returning_players.py`
  - Emits `skill_spacing_percentile`, `skill_facilitating_percentile`, `skill_rim_protection_percentile`, `skill_defense_percentile`, and `skill_finishing_percentile`.
  - Regenerated `frontend_site/data/returningPlayers.ts`.
  - Returning rows: 1,898.
  - Returning rows with all five non-null skill percentiles: 1,894.
  - Verified Cameron Boozer's spacing percentile was merged from the percentile source.
- Updated frontend type:
  - `frontend_site/data/players.ts`
  - Added optional `skill_*_percentile` fields.
- Updated Returning dropdown UI:
  - `frontend_site/components/PlayerDetailPanel.tsx`
  - Returning dropdown now displays the compact `2025-26 Season Stats` strip beside an animated pentagon `Skill Percentiles` radar.
  - Radar vertices: Spacing, Facilitating, Rim Protection, Defense, Finishing.
  - Radar grid and polygon scale open from the center when the dropdown mounts.
  - Percentile values are rounded to one decimal and displayed in color-coded badges.
  - Transfer and HS dropdowns were not changed by this radar update.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:12:00 CDT Transfer detail card trim

- User requested simplifying transfer dropdown stat/profile cards.
- Updated `frontend_site/components/PlayerDetailPanel.tsx`:
  - Transfer dropdown right-side metric cards now show only `247 Rank` and `247 Stars`.
  - Removed the visible cards for `247 Rating`, `247 Status`, `Weight`, and `Height`.
  - HS and Returning detail panels were not changed.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:05:00 CDT Returning stats strip cleanup and transfer stat revert

- User requested a cleaner Returning dropdown layout inspired by a compact season-stat strip and asked to remove the `2025-2026 Stats` section from transfer dropdowns.
- Updated Returning stat data:
  - `frontend_site/scripts/build_returning_players.py`
  - Added `season_ft_pct` from `bvt_FT_per`.
  - Regenerated `frontend_site/data/returningPlayers.ts`.
  - Returning rows with `season_ft_pct`: 1,898.
  - Verified Cameron Boozer has FT% populated from the source data.
- Updated Returning dropdown UI:
  - `frontend_site/components/PlayerDetailPanel.tsx`
  - Returning dropdowns now render a compact `2025-26 Season Stats` strip instead of the boxed card grid.
  - Displayed fields: PPG, RPG, APG, SPG, BPG, GP, MP, FT, and BPR.
- Reverted transfer stat additions:
  - `frontend_site/scripts/build_transfer_players.py`
  - Removed the previously added `season_*` transfer fields from generation.
  - Regenerated `frontend_site/data/transferPlayers.ts`.
  - Confirmed generated transfer data no longer contains `season_basic_bpr` or `season_ft_pct`.
  - Transfer dropdown rendering is back to its previous profile/247/playtype content.
- Updated shared `Player` type:
  - `frontend_site/data/players.ts`
  - Keeps optional `season_*` fields for Returning data, including `season_ft_pct`.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 20:55:00 CDT Returning dropdown 2025-2026 stats panel

- User requested simplifying Returning player dropdowns so they no longer show the profile copy/empty filler and instead show only a `2025-2026 Stats` section.
- Updated Returning data generation:
  - `frontend_site/scripts/build_returning_players.py`
  - Added season stat fields from the same-school prediction source:
    - `season_basic_bpr` from `basic_bpr`.
    - `season_gp` from `bvt_GP`.
    - `season_mp` from `bvt_mp`.
    - `season_oreb`, `season_dreb`, `season_treb`, `season_ast`, `season_stl`, `season_blk`, `season_pts` from the matching `bvt_` columns.
  - Regenerated `frontend_site/data/returningPlayers.ts`.
  - Returning rows with `season_basic_bpr`: 1,898.
- Updated transfer data generation opportunistically without deleting any existing transfer dropdown content:
  - `frontend_site/scripts/build_transfer_players.py`
  - Added the same season stat fields from transfer BPR inference where available:
    - `season_basic_bpr` from `evan_basic_bpr`.
    - Box/counting stats from `allyears_gp`, `allyears_mp`, `allyears_oreb`, `allyears_dreb`, `allyears_treb`, `allyears_ast`, `allyears_stl`, `allyears_blk`, `allyears_pts`.
  - Regenerated `frontend_site/data/transferPlayers.ts`.
  - Transfer rows with `season_basic_bpr`: 1,255.
- Updated detail rendering:
  - `frontend_site/components/PlayerDetailPanel.tsx`
  - Returning dropdowns now render only the `2025-2026 Stats` grid.
  - Transfer dropdowns keep their existing 247/profile/playtype sections and append the `2025-2026 Stats` cards when data exists.
  - HS rendering was not changed.
- Updated shared `Player` type:
  - `frontend_site/data/players.ts`
  - Added optional `season_*` fields used by Returning and transfer stat cards.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 20:40:00 CDT Returning player image backfill and playtype cleanup

- User clarified this update is only for Returning players; HS and transfer frontend data/rendering should remain unchanged.
- Updated Returning data generation:
  - `frontend_site/scripts/build_returning_players.py`
  - Returning players now emit `playtype_probabilities: {}` instead of a fake one-role probability.
  - The role is still kept as `returning_role` and displayed on the Returning mini-card.
- Added cached image lookup for Returning players:
  - Looks up Returning `bvt_pid` in `data_dir/hs_bv_matched.db` table `hs_bv_matched`.
  - Uses `hs_player_key` and `hs_year` to read cached profile HTML under `scrapers_web/cache/hs/{hs_year}/profiles/{hs_player_key}.html`.
  - Also honors `hs_dob_247_source_profile_file` when present.
  - Extracts `og:image` or `twitter:image` from cached 247 profile HTML.
- Regenerated Returning data:
  - Output: `frontend_site/data/returningPlayers.ts`.
  - Returning rows: 1,898.
  - Cached profile images filled: 742.
  - All 1,898 Returning rows now have empty `playtype_probabilities`.
- Updated Returning frontend display:
  - `frontend_site/components/PlayerTable.tsx` uses `returning_role` directly on the mini-card so role remains visible even without playtype probabilities.
  - `frontend_site/components/PlayerDetailPanel.tsx` hides the Playtype Probabilities section for Returning players.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 19:37:16 CDT Same-school next-year Evan/BartTorvik table

- User requested a new table inside `data_dir/evan_miya_barttorvik_matched.db` where each row pairs a player's old-year stats with that same player's next-year stats only when the player stayed at the same institution.
- Added reproducible builder script:
  - `data_dir/data_cleaning/evan_bv_matching/create_same_school_next_year_table.py`
  - Source table: `evan_miya_barttorvik_matched`.
  - Output table: `evan_miya_barttorvik_same_school_next_year`.
  - The output table contains all original source columns twice, prefixed as `old_` and `next_`, for 256 total columns.
  - Match rule: `next_year.year = old_year.year + 1`, `old_year.year <> 2026`, exact same `team`, and same `bvt_barttorvik_trid` or same `bvt_pid`.
- Backup created before writing:
  - `data_dir/backups/evan_miya_barttorvik_matched.before_same_school_next_year_20260607_193716.db`
- Final output:
  - Rows in `evan_miya_barttorvik_same_school_next_year`: 27,705.
  - Old years covered: 2010-2025.
  - Next years covered: 2011-2026.
- Validation:
  - Output columns: 256.
  - Rows with `old_year = 2026`: 0.
  - Rows where `next_year != old_year + 1`: 0.
  - Rows where `old_team != next_team`: 0.
  - Duplicate old player-year groups by `(old_year, old_team, old_bvt_barttorvik_trid, old_bvt_pid)`: 0.

### 2026-06-07 20:25:00 CDT Frontend Returning players table

- User requested adding same-school returning players to the Players page only, by relabeling the existing `All` toggle as `Returning`.
- Added generated Returning dataset:
  - Builder: `frontend_site/scripts/build_returning_players.py`.
  - Output: `frontend_site/data/returningPlayers.ts`.
  - Source CSV: `models_dir/same_school_bpr/catboost_same_school_bpr_inference_outputs/catboost_same_school__2026_20260607_201623/catboost_same_school_predictions_2026.csv`.
  - Transfer exclusion source: `models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/dual_transfer_bpr_inference_2026_20260607_190712/dual_transfer_bpr_predictions_2026.csv`.
  - Exclusion rule: remove same-school rows whose `bvt_pid` appears in transfer predictions as `allyears_pid`.
- Filtering result:
  - Same-school source rows: 3,743.
  - Transfer PID rows excluded from Returning dataset: 1,845.
  - Returning frontend rows generated: 1,898.
  - Verified `Flory Bidunga` is excluded from `returningPlayers.ts`.
  - Transfer frontend data was not edited or filtered; transfer pages remain unaffected.
- Frontend rendering changes:
  - `frontend_site/app/page.tsx` now uses `returningPlayers` only for the `Returning` toggle while keeping HS and transfer toggles pointed at their existing generated datasets.
  - `frontend_site/components/PlayerTable.tsx` renders the default/Returning mode with columns: Player, POS, Team, Status, BPR, dropdown.
  - Returning player mini-card omits weight.
  - Status displays a dedicated `Returning` badge.
  - No projected OBPR/DBPR fields are generated or displayed because the same-school output only includes predicted BPR.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:15:00 CDT Transfer frontend bad match exclusion

- User identified a bad transfer match: `Najimi George` was paired to the 247 profile for `George Kimble III`, which made the generated frontend data show an incorrect Auburn transfer entry.
- Traced the bad source row in `models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions_with_247_cols.csv`:
  - `transfer_player_name`: `Najimi George`
  - `transfer_old_team`: `New Haven`
  - `allyears_pid` / `allyears_barttorvik_trid`: `134675`
  - incorrect `247_full_name`: `George Kimble III`
  - incorrect `247_destination_school`: `Auburn`
  - incorrect `247_player_key`: `46156626`
- Added a targeted frontend generator exclusion in `frontend_site/scripts/build_transfer_players.py`:
  - `("najimi george", "new haven")`
  - This removes only that generated transfer row and does not alter the underlying CSVs or any unrelated transfer records.
- Regenerated `frontend_site/data/transferPlayers.ts`.
- Final generated transfer count: `2,375`.
- Verification:
  - `frontend_site/data/transferPlayers.ts` no longer contains `Najimi George`, `George Kimble III`, `transfer-1241`, or `46156626`.
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:35:00 CDT Simulator search, filters, and compact layout pass

- Updated `frontend_site/components/PortalSimulator.tsx` to make the simulator denser and easier to operate.
- Added Current Roster search:
  - Search matches player name, team, position, class year, and role/playtype text.
  - Header now shows filtered count vs total roster count.
- Added Browse Targets search and filters:
  - Search matches the same player/team/position/role fields.
  - Filters added for `Class` and `POS`.
  - Sort added for `BPR ↓`, `BPR ↑`, and `Name A-Z`.
  - Target count now updates based on active filters.
- Compact layout changes:
  - Reduced summary-card height/padding and clamped detail text to one line.
  - Reduced team/reset control height.
  - Reduced workbench tab height.
  - Reduced roster/target row padding and list height to keep the roster square, depth chart, and team skill radar visible together more often.
  - On very wide screens, the projected depth chart and team radar can sit side-by-side.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 21:50:00 CDT Simulator compact top-area revision

- User wanted the simulator page compressed further while keeping the newly added search/filter behavior unchanged.
- Updated `frontend_site/app/simulator/page.tsx`:
  - Removed the explanatory paragraph under `Transfer Portal Simulator`.
  - Reduced the header bottom margin.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Moved the four quick roster facts directly under the team search control.
  - Made the quick roster facts much smaller.
  - Added red styling to the roster-spots text/card border when the projected roster exceeds the 15-player limit.
  - Removed the separate full-width summary-card row so the roster/workbench area moves up.
  - Put `Team Skills Radar` above `Projected Depth Chart`.
  - Tightened roster/target rows, search/filter controls, incoming-player card padding, depth-chart padding, and radar size to make the roster square, pentagon, and depth chart fit together better.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 22:05:00 CDT Simulator metric placement cleanup

- User wanted the simulator mini metrics moved under the roster/search area and simplified further.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Removed the mini metrics from directly under the team combobox.
  - Rendered the same metrics strip inside the active workbench panel directly under roster search or target filters.
  - Changed roster detail text to concise `x/15 spots`.
  - Changed `Projected BPR` metric label to `Proj Avg BPR` and removed the `Avg...` detail line.
  - Removed player-name detail text from departures/arrivals; those cards now only show counts.
  - Renamed the fourth metric to `Arrivals`.
  - Kept existing roster and target search/filter behavior unchanged.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 22:15:00 CDT Simulator metric strip final placement

- User clarified the four mini metric cards should sit below the entire roster/browser workbench, not inside the roster search panel.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Moved the metric strip to render immediately after the active `RosterDecisionList` or `TargetBrowser` component in the left column.
  - Removed metric-strip props from `RosterDecisionList` and `TargetBrowser`.
  - Kept the metric text concise: `x/15 spots`, `Proj Avg BPR`, count-only `Departures`, and count-only `Arrivals`.
  - Kept existing roster search and target search/filter behavior unchanged.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 22:25:00 CDT Simulator workbench height expansion

- User wanted the roster/browser workbench area expanded so the four metric cards sit lower and the left-column empty space is filled.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Changed both roster and target player scroll areas from `max-h-[340px]` to fixed `h-[520px]`.
  - This keeps the metric strip below a taller roster/portal workbench and pushes it toward the bottom of the visible layout.
  - Search/filter behavior remains unchanged.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 22:30:00 CDT Simulator workbench height trim

- User noted the previous `520px` roster/browser workbench height pushed the metric strip too far down.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Reduced both roster and target player scroll areas from `h-[520px]` to `h-[455px]`.
  - This keeps the workbench expanded while bringing the four metric cards back into view.
  - Search/filter behavior remains unchanged.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 22:40:00 CDT Simulator final viewport fit pass

- User wanted the metric strip scooted up slightly so it is not cut off, and wanted the depth chart condensed to reduce page-level scrolling.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Reduced roster and target scroll panes from `h-[455px]` to `h-[430px]`.
  - Added internal depth-chart scrolling with `max-h-[315px]`.
  - Narrowed depth-chart player rows with `max-w-sm` and a compact name/BPR grid so the large empty gap between player name and BPR is removed.
  - Reduced depth-chart row font size and vertical spacing.
  - Roster and target search/filter behavior remains unchanged.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 22:50:00 CDT Simulator depth-chart column layout

- User wanted the simulator right column widened slightly and the depth chart to use horizontal space instead of pushing down the page.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Rebalanced the main simulator grid to `xl:grid-cols-[minmax(520px,1.03fr)_minmax(520px,.97fr)]`, keeping the left workbench slightly larger while giving the right analysis column more room.
  - Converted projected depth chart groups into a 3-column layout for Guards, Wings, and Bigs on the same row at large viewport sizes.
  - Kept internal depth-chart scrolling for longer scenarios.
  - Tightened depth-chart player rows further with compact name/BPR columns.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 23:00:00 CDT Simulator browse-pane height alignment

- User noted the Browse Portal pane was taller than the Current Roster pane, causing the four metric cards to drop off frame when switching tabs.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Tightened Browse Portal tab/header/filter vertical padding.
  - Reduced Browse Portal target rows slightly.
  - Set the target list scroll area to `h-[412px]` so the overall browse panel height aligns more closely with the roster panel.
  - Current roster pane remains `h-[430px]` because it has fewer header/filter rows.
  - Existing search/filter behavior remains unchanged.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-07 23:10:00 CDT Simulator collapsible target filters and status filter

- User noted the default Browse Portal pane still pushed the four metric cards slightly below frame and requested hidden filters behind a toggle.
- Updated `frontend_site/components/PortalSimulator.tsx`:
  - Added a `Filters` toggle next to target search.
  - Class, POS, Status, and BPR/name sort controls are hidden until `Filters` is opened.
  - Added a transfer status filter using the same canonical portal statuses as the Players page (`entered`, `committed`, `enrolled`, `withdrawn`).
  - Status filtering only applies to transfer players; HS targets remain visible when status is not relevant.
  - Tightened Browse Portal default height to `h-[395px]`; when filters are open the target list becomes `h-[360px]` so the overall pane height stays controlled.
  - Existing search behavior remains unchanged.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-08 00:05:00 CDT Transfer frontend source correction and simulator BPR alignment

- User found a bad transfer institution/BPR mismatch for Jaylen Wharton and asked for transfer data to come only from the approved transfer model outputs.
- Root cause:
  - `frontend_site/scripts/build_transfer_players.py` had previously allowed transfer display teams to fall back to unsafe 247 matched columns from a `_with_247_cols` role file.
  - The Jaylen Wharton row was incorrectly carrying a bad 247 match (`Jalen Langsy`), which polluted the UI with `Northwestern College` and `South Alabama` even though the transfer/BartTorvik fields identified Jaylen as Northern Illinois to Prairie View A&M.
  - The simulator target cards displayed `projected_bpr`, while the Players transfer table displayed `transfer_bpr`, so the same transfer could show different BPR values.
- Updated transfer frontend generation:
  - `frontend_site/scripts/build_transfer_players.py` now reads role/playtype data from `models_dir/transfer_playtype_prediction/outputs/catboost_transfer_role_future_top3_predictions.csv`.
  - It now reads BPR and destination-adjusted transfer fields from `models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/dual_transfer_bpr_inference_2026_20260607_190712/destination_adjusted_transfer_predictions_2026.csv`.
  - Transfer display institutions now use transfer/BartTorvik fields only: origin/current/previous = `transfer_old_team` fallback `allyears_team`; destination/new/committed = `transfer_new_team`.
  - 247 source/destination school fields are no longer used for transfer display teams.
  - Transfer position now uses `transfer_player_role` fallback `allyears_role`, not an unsafe 247 position fallback.
  - Hidden transfer joins to percentile/season-stat side sources were removed from the transfer generator so transfer rows are generated from the two approved transfer CSVs only.
  - `projected_bpr` is set to rounded `transfer_bpr` when a transfer BPR exists, keeping simulator averages/cards aligned with transfer-table BPR values.
- Updated simulator BPR display/sort:
  - `frontend_site/components/PortalSimulator.tsx` target cards now display transfer BPR from `transfer_bpr`, matching the Players transfer table.
  - Transfer target BPR sorting also uses `transfer_bpr`; missing transfer BPR sorts last and displays as `N/A`.
- Regenerated `frontend_site/data/transferPlayers.ts`.
- Verification:
  - Generated transfer rows: 2,375.
  - Rows with transfer BPR: 1,416.
  - Jaylen Wharton now generates as position `C`, current/previous team `Northern Illinois`, destination/committed team `Prairie View A&M`, transfer BPR `-2.450132590395242`, projected BPR `-2.5`.
  - Jaylen row no longer contains `Northwestern College`, `South Alabama`, or `Jalen Langsy`.
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-08 00:25:00 CDT Transfer metadata and radar restoration without team/BPR drift

- User noted the previous source cleanup removed transfer profile images, 247 stars/ratings, and transfer radar pentagons.
- Updated `frontend_site/scripts/build_transfer_players.py` again to restore auxiliary display data while keeping transfer teams and BPR locked to the correct sources:
  - Transfer origin/current/previous still comes only from `transfer_old_team` fallback `allyears_team` in `catboost_transfer_role_future_top3_predictions.csv`.
  - Transfer destination/new/committed still comes only from `transfer_new_team` in `catboost_transfer_role_future_top3_predictions.csv` / `destination_adjusted_transfer_predictions_2026.csv`.
  - Transfer BPR still comes from `pred_next_year_basic_bpr` in `destination_adjusted_transfer_predictions_2026.csv`.
  - `projected_bpr` still equals rounded `transfer_bpr` when transfer BPR is available, so Players table and simulator target cards stay consistent.
- Restored safe 247 metadata:
  - Joined `data_dir/247_bv_transf_matched.db`, table `transfer_247_bv_matched`, on `allyears_pid = db1_allyears_pid` for `db1_allyears_year = 2026`.
  - Used 247 metadata only when the matched 247 full name exactly normalizes to the transfer player name and the match has `name_score >= 95` and `overall_match_score >= 90`.
  - Restored profile image, 247 player key, stars, transfer rating/rating, transfer rank, transfer status, weight, and safe 247 position fallback.
  - 247 source/destination schools remain unused for transfer display teams.
- Restored transfer radar pentagons:
  - Rejoined `data_dir/player_percentile/cluster_percentile_outputs/players_group_percentiles_from_db.csv` on `allyears_pid = bvt_pid`, filtered to `year = 2026`.
  - Restored spacing, facilitating, rim protection, defense, and finishing percentiles for transfer detail panels.
- Regenerated `frontend_site/data/transferPlayers.ts`.
- Verification:
  - Generated transfer rows: 2,375.
  - Rows with transfer BPR: 1,416.
  - Rows with safe 247 metadata/profile key: 1,213.
  - Rows with profile image: 1,213.
  - Rows with 247 stars/rating: 753.
  - Rows with radar percentiles: 1,840.
  - Transfer rows with rounded `transfer_bpr` not matching `projected_bpr`: 0.
  - Flory Bidunga verified with image, 5 stars, 0.98 rating, rank 1, Kansas to Louisville, BPR 6.7, radar percentiles present.
  - John Blackwell verified with image, 5 stars, 0.98 rating, rank 3, Wisconsin to Duke, BPR 6.5, radar percentiles present.
  - Jaylen Wharton remains protected from the bad 247 metadata match; his teams/BPR remain Northern Illinois to Prairie View A&M and -2.5, and his row does not contain `Northwestern College`, `South Alabama`, or `Jalen Langsy`.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-08 00:40:00 CDT Transfer row universe changed to BPR prediction file

- User clarified that every displayed transfer must have a predicted BPR from `destination_adjusted_transfer_predictions_2026.csv`, column `pred_next_year_basic_bpr`.
- Root cause:
  - `frontend_site/scripts/build_transfer_players.py` was still using `catboost_transfer_role_future_top3_predictions.csv` as the transfer row universe.
  - That role file has 2,377 candidate transfer rows, while `destination_adjusted_transfer_predictions_2026.csv` has 1,417 rows and all 1,417 have `pred_next_year_basic_bpr` populated.
  - Therefore the frontend showed many extra transfer candidates that had role predictions but no BPR prediction.
- Fix:
  - Changed `frontend_site/scripts/build_transfer_players.py` so `destination_adjusted_transfer_predictions_2026.csv` is now the canonical/base transfer row universe.
  - The script now raises if any row in that BPR source has missing `pred_next_year_basic_bpr`.
  - The script now joins role/playtype columns from `catboost_transfer_role_future_top3_predictions.csv` as auxiliary display data only.
  - The script now raises if any generated transfer player is missing `transfer_bpr`.
  - Existing safe 247 metadata join and 2026 radar percentile join remain auxiliary only and do not change transfer origin, destination, or BPR.
- Regenerated `frontend_site/data/transferPlayers.ts`.
- Verification:
  - Source BPR rows: 1,417.
  - Source non-null `pred_next_year_basic_bpr`: 1,417.
  - Displayed transfer rows after existing exclusions: 1,416. The one-row difference is the existing hard exclusion for Najimi George / New Haven requested earlier.
  - Displayed transfer rows with `transfer_bpr`: 1,416.
  - Displayed transfer rows missing `transfer_bpr`: 0.
  - Displayed transfer rows where rounded `transfer_bpr` does not equal `projected_bpr`: 0.
  - Safe 247 metadata rows retained: 993.
  - 247 stars/ratings rows retained: 656.
  - Radar percentile rows retained: 1,185.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-08 00:50:00 CDT Transfer BPR source corrected to complete dual prediction CSV

- User clarified the complete transfer BPR source is `models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/dual_transfer_bpr_inference_2026_20260607_190712/dual_transfer_bpr_predictions_2026.csv`, not the destination-adjusted subset.
- Source audit:
  - `dual_transfer_bpr_predictions_2026.csv` has 2,377 rows.
  - All 2,377 rows have non-null `pred_next_year_basic_bpr`.
  - It includes the required transfer keys and team columns: `transfer_row_number`, `allyears_barttorvik_trid`, `allyears_pid`, `transfer_player_name`, `transfer_old_team`, `transfer_new_team`, and `allyears_team`.
  - It matches all 2,377 rows in `catboost_transfer_role_future_top3_predictions.csv` on `transfer_row_number + allyears_barttorvik_trid`.
- Updated `frontend_site/scripts/build_transfer_players.py`:
  - `BPR_PREDICTIONS` now points to `dual_transfer_bpr_predictions_2026.csv`.
  - This complete BPR CSV remains the canonical/base transfer row universe.
  - Role/playtype CSV remains auxiliary for role probabilities only.
  - Safe 247 metadata and 2026 radar percentile joins remain auxiliary and do not alter transfer teams or BPR.
- Regenerated `frontend_site/data/transferPlayers.ts`.
- Verification:
  - Generated displayed transfer rows: 2,375.
  - The two-row difference from the 2,377 source rows is from existing hard exclusions: Cole Alexander / Fairleigh Dickinson and Najimi George / New Haven.
  - Displayed transfers with `transfer_bpr`: 2,375.
  - Displayed transfers missing `transfer_bpr`: 0.
  - Displayed transfer rows where rounded `transfer_bpr` does not equal `projected_bpr`: 0.
  - Safe 247 metadata rows: 1,213.
  - 247 stars/ratings rows: 753.
  - Radar percentile rows: 1,840.
  - Flory Bidunga, Jaylen Wharton, and John Blackwell spot checks retained correct teams/BPR behavior; Flory and John retained image/stars/rating/radar where safe.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-08 01:05:00 CDT Transfer dropdown layout cleanup

- User wanted the transfer dropdown to look cleaner like the returning-player dropdown, without changing transfer data sourcing.
- Updated `frontend_site/components/PlayerDetailPanel.tsx`:
  - Added a transfer-specific detail layout instead of using the generic three-column profile/playtype/metric layout.
  - Transfer dropdown now renders as two cleaner cards: a transfer profile card and the existing skill percentile radar card.
  - Transfer profile card groups source badge, origin-to-destination, projected role, 247 rank/stars/rating, BPR, scouting text, and playtype probability bars.
  - Data sourcing was not changed in this pass.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-08 01:15:00 CDT Transfer stars removed and transfer rating source tightened

- User requested removing 247 stars from transfers only, while leaving HS recruit stars unchanged.
- User also requested transfer rating to use `247_transfer_rating` only, not generic `247_rating`.
- Updated `frontend_site/scripts/build_transfer_players.py`:
  - `transfer_247_stars` is no longer emitted for transfer players.
  - `transfer_247_rating` now comes only from `metadata_247_transfer_rating` / `247_transfer_rating`.
  - No fallback to generic `247_rating` remains for transfer rows.
- Updated `frontend_site/components/PlayerTable.tsx`:
  - Removed transfer Stars column and transfer stars sorting from transfer mode.
  - HS recruit stars column/filter/sorting remain unchanged.
- Updated `frontend_site/components/PlayerDetailPanel.tsx`:
  - Removed the transfer 247 Stars metric from transfer dropdown cards.
  - Renamed the transfer rating card to `Transfer Rating`.
- Regenerated `frontend_site/data/transferPlayers.ts`.
- Verification:
  - Displayed transfer rows: 2,375.
  - Transfer rows with `transfer_bpr`: 2,375.
  - Transfer rows with `transfer_247_stars`: 0.
  - Transfer rows with `transfer_247_rating`: 439.
  - Flory Bidunga, Milan Momcilovic, and John Blackwell retain `transfer_247_rating = 0.98` and have no transfer stars field.
- Validation:
  - `npx tsc --noEmit` passed in `frontend_site`.
  - `npm run build` passed in `frontend_site`.

### 2026-06-08 01:23:30 CDT Portal sidebar nav removal

- User clarified they only wanted the sidebar `Portal` tab gone because the `Players` page already covers all three player pools.
- Updated `frontend_site/components/Shell.tsx`:
  - Removed the `Portal` nav item from the shared `navItems` array.
  - Removed the unused `ListFilter` icon import.
  - This removes `Portal` from both desktop sidebar and mobile nav because both are driven by the same array.
- Did not delete `frontend_site/app/portal/page.tsx`; the route still exists if manually visited, but it is no longer linked in navigation.
- Validation:
  - Ran `npm run build` from `frontend_site`.
  - Next.js production build completed successfully.

### 2026-06-08 01:33:21 CDT Dummy seed and recommendations UI cleanup

- User identified leftover dummy roster data visible in the simulator, specifically `Sam Okoro`.
- Verified `Sam Okoro` was only present in the old static seed list in `frontend_site/data/players.ts`; generated frontend datasets did not contain that player.
- Updated `frontend_site/data/players.ts`:
  - Cleared the old `basePlayers` mock/seed array.
  - Real generated transfer, returning, and high-school data remain untouched via `transferPlayers` and `hsRecruitPlayers` imports.
- Updated `frontend_site/components/Shell.tsx`:
  - Removed the `Recommendations` nav item from the sidebar/mobile nav.
  - Removed the now-unused `Target` icon import from that file.
- Updated `frontend_site/app/teams/[teamId]/page.tsx`:
  - Removed the bottom `Recommended Portal Fits` section and its `RecommendationsBoard` import.
  - Kept the team roster/commitments table and top metrics intact.
- Validation:
  - Confirmed `Sam Okoro` and other old visible mock seed names no longer appear in frontend app/data code, except unrelated real generated rows such as `Andre Mills` in `returningPlayers.ts`.
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-08 02:13:14 CDT Frontend institution alias canonicalization

- User requested a frontend-side institution alias system to reduce redundant school names across site display/filtering, with Braylon Mullins/Connecticut vs UConn as the explicit validation example.
- Copied the current dedupe CSV into the frontend data directory:
  - `frontend_site/data/current_site_teams_for_dedupe.csv`
- Important note: the source CSV currently has zero filled `canonical_replacement` values, so this pass seeded exact safe aliases in code instead of applying unavailable manual CSV replacements.
- Added `frontend_site/data/teamAliases.ts`:
  - Defines `institutionAliases` and `canonicalizeInstitution()`.
  - Includes `Connecticut -> UConn`.
  - Includes exact `St.` abbreviation aliases only where the full `State` version also exists in the current site team list, such as `Iowa St. -> Iowa State` and `Long Beach St. -> Long Beach State`.
  - Does not use broad string replacement, so names like `St. Bonaventure` are not changed accidentally.
- Updated `frontend_site/data/players.ts`:
  - Applies canonical institution names when the combined `players` export is assembled.
  - Normalizes only institution fields: `current_team`, `previous_team`, `new_team`, and `committed_team`.
  - Generated transfer, returning, and HS source files remain untouched.
- Updated `frontend_site/lib/data.ts`:
  - Canonicalizes incoming team filter/team-page lookups as well, so team matching remains robust if an alias is passed in.
- Validation:
  - Braylon Mullins raw generated `current_team` is `Connecticut`, and canonical frontend value is now `UConn`.
  - This makes Braylon match the UConn team page/simulator roster lookup.
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-08 02:24:56 CDT Institution alias equivalence correction and Players metric-card removal

- User clarified that matched institutions are stored in `frontend_site/data/current_site_teams_for_dedupe.csv` under `identical_school`, not `canonical_replacement`.
- Regenerated `frontend_site/data/teamAliases.ts` from both `identical_school` and `canonical_replacement` as equivalence groups:
  - Every alias in a matched group maps to one canonical display name.
  - If a group includes a configured `teams.ts` site team, that team name is preferred as the canonical display value.
  - Otherwise the most common current spelling in the site data is used as the canonical display value.
  - Example: both `Connecticut` and `UConn` now canonicalize to `UConn`.
  - Example: `Miami`, `Miami (Fla.)`, and `Miami FL` canonicalize to `Miami`; `Miami (OH)` and `Miami OH` canonicalize separately to `Miami (OH)`.
- Revalidated Braylon Mullins:
  - Raw generated `current_team` remains `Connecticut`.
  - Frontend canonicalized value is `UConn`.
  - This should make him match the UConn team page/simulator roster lookup alongside the other UConn players.
- Updated `frontend_site/app/page.tsx`:
  - Removed the four top metric cards from the Players tab for Returning, HS Recruits, and Transfers.
  - Removed now-unused metric helper functions/imports.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Frontend folder rename scare check

- User briefly renamed `frontend_site`, macOS prompted about updating imports, user declined, then renamed the directory back to `frontend_site`.
- Checked repo state:
  - `frontend_site` directory exists at the repo root.
  - Active app route files are present:
    - `frontend_site/app/page.tsx`
    - `frontend_site/app/players/page.tsx`
    - `frontend_site/app/rosters/page.tsx`
    - `frontend_site/app/optimizer/page.tsx`
    - `frontend_site/app/teams/page.tsx`
  - Red `D` entries in Git status correspond to files intentionally deleted earlier:
    - old `/portal`, `/recommendations`, `/simulator`, old `/teams/[teamId]`, and unused `RecommendationsBoard`.
  - `frontend_site/package.json` package name is now `roster-lab`; this is safe for a private app and does not need to match the directory name.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.
  - Build route table still shows:
    - `/`
    - `/players`
    - `/rosters`
    - `/optimizer`
    - `/teams`

### 2026-06-11 Teams route simplified

- User observed that the Teams dropdown state is independent from the URL and requested removing the team ID from the route if feasible.
- Verified:
  - The old `/teams/[teamId]` route only used `teamId` for initial dropdown selection.
  - After load, team selection is controlled by local dropdown state and does not update the URL.
- Updated:
  - Added canonical route `frontend_site/app/teams/page.tsx`.
  - Removed `frontend_site/app/teams/[teamId]/page.tsx`.
  - Updated `frontend_site/components/Shell.tsx` Teams nav link from `/teams/uconn` to `/teams`.
  - Updated `frontend_site/components/ReadOnlyTeamsView.tsx` to initialize from the first seeded team instead of a route param.
- No roster sourcing, Teams page dropdown behavior, roster display logic, or team data logic was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.
  - Build route table now shows `/teams` instead of `/teams/[teamId]`.

### 2026-06-11 Players HS/transfer default BPR sort

- User requested HS Recruits and Transfers tabs default to descending BPR instead of descending rating.
- Updated `frontend_site/components/PlayerTable.tsx`:
  - HS Recruit tab default sort key changed from `hs_rating` to `hs_bpr`.
  - Transfer tab default sort key changed from `transfer_247_rating` to `transfer_bpr`.
  - Sort direction remains descending.
- No displayed data, data sourcing, filters, or sortable column behavior was otherwise changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Players reset filters and sidebar copy

- User requested a `Reset Filters` button for all toggles on the Players page and a sidebar subtitle copy change.
- Updated `frontend_site/components/PlayerTable.tsx`:
  - Added a `Reset Filters` button to the player filter panel.
  - Button uses the same reset-style icon treatment as other pages.
  - Reset clears search/filter state for the current player tab:
    - player search
    - position
    - status
    - team search
    - class
    - conference
    - playtype
    - stars
    - uncommitted-only
    - portal-only back to tab default
    - pagination/display count
    - expanded rows
  - Did not change data sourcing, player rows, sorting columns, or tab behavior.
- Updated `frontend_site/components/Shell.tsx`:
  - Changed sidebar subtitle from `Transfer portal operations` to `Recruiting operations`.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Optimizer roster-size tooltip

- User requested a small information icon to the left of `Roster Size` in the optimizer target controls.
- Updated `frontend_site/components/RosterOptimizer.tsx`:
  - Added a small `Info` icon next to the `Roster Size` label.
  - Hovering the icon displays:
    - `Optimizer only runs if total roster count equals 15. Adjust positional limits with +/- buttons or manually adjust in text fields until roster count is 15.`
  - No optimizer math, data sourcing, roster behavior, or layout beyond this tooltip was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Dummy team metadata and obsolete fit cleanup

- User requested safe removal of remaining dummy team metadata and obsolete fit-rating logic without changing active website behavior or data sourcing.
- Verified active use before editing:
  - `frontend_site/data/teams.ts` is used only as a seeded list for team IDs/names in dropdown/default-team flows.
  - No active page/model used the old `conference`, `roster_limit`, `scholarships_used`, `style`, or `needs` fields from `teams.ts`.
  - `frontend_site/lib/data.ts` still had obsolete `getRecommendations()` / `teamAdjustment()` fit-score logic, but it was only referenced by the unused `RecommendationsBoard` component from the removed recommendations route.
- Updated:
  - `frontend_site/data/teams.ts`
    - Kept only `team_id` and `team_name`.
    - Removed dummy `conference`, `roster_limit`, `scholarships_used`, `style`, and `needs`.
  - `frontend_site/lib/data.ts`
    - Removed obsolete `getRecommendations()`.
    - Removed hardcoded `teamAdjustment()` fit-score boosts.
  - `frontend_site/components/RecommendationsBoard.tsx`
    - Removed the unused old recommendations component.
  - `frontend_site/components/PlayerTable.tsx`
    - Removed only the HS Recruit view's `Rating` filter input.
    - Did not remove HS rating data, rating display, sorting, or sourcing.
  - `frontend_site/data/data_sources.txt`
    - Updated documentation so `teams.ts` is listed only as team ID/name metadata.
    - Removed the obsolete recommendations/fit-adjustment documentation block.
- No optimizer math, roster logic, recruit/transfer data sourcing, generated player data, or visible page structure was intentionally changed beyond the requested HS rating filter removal.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Transfer-out roster membership and full optimizer eligibility

- User requested a narrow, high-risk data-display logic fix:
  - Do not change generated data or data sourcing.
  - Remove transfer-out players from their old team roster views.
  - Prevent transfer-out players from being recommended back to their old team in Full Roster Optimization.
  - Keep those same players visible in Manual Optimizer and Single Player Optimization.
- Pre-check:
  - Scanned transfer source/destination team names for close non-equal names.
  - Found close but distinct school pairs:
    - Jacksonville -> Jacksonville State.
    - Northeastern -> Northwestern.
  - The implementation uses exact canonical team equality only, so close names are not merged.
- Updated:
  - `frontend_site/lib/data.ts`
    - Added transfer roster membership helpers.
    - `getTeamPlayers()` now treats transfers as destination-first:
      - Include a transfer on the destination/new/committed team.
      - Exclude a transfer from the source/current/previous team unless the destination is the same canonical school.
  - `frontend_site/components/RosterOptimizer.tsx`
    - Added a Full Roster Optimization-only candidate filter using `isTransferOutgoingFromTeam()`.
    - Manual Optimizer and Single Player Optimization still receive the full candidate pool.
    - Also filters stale loaded optimizer payload IDs through the same outgoing-transfer rule so old localStorage cannot re-add a transferred-out player to the loaded roster.
- Example checked:
  - Elyjah Freeman raw transfer row is Auburn -> Texas, committed.
  - Under the new logic, he is excluded from Auburn's roster and Auburn's Full Roster Optimization candidates.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.
  - Re-ran `npm run build` after adding the stale optimizer-payload guard; production build completed successfully.

### 2026-06-11 Optimizer target max text inputs restored

- User noticed the editable text/number fields for optimizer max position targets had disappeared.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Change:
  - Reintroduced editable numeric inputs for the Guard/Forward/Center target max values.
  - Kept the existing +/- buttons.
  - Manual target edits clear the current optimizer result and preserve existing validation styling.
- No data sources, roster sourcing, optimizer math, or other frontend sections were changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Optimizer target input behavior cleanup

- User requested cleanup of the restored optimizer max-position inputs.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Changes:
  - Removed native browser up/down spinners by switching the target inputs from number inputs to text inputs with numeric parsing.
  - Leading zero behavior is normalized, so typing/backspacing does not leave values like `05`.
  - Removed automatic position target balancing from the +/- buttons.
  - The optimizer can no longer run unless Guard + Forward + Center targets total exactly 15.
- No data sources, roster sourcing, optimizer math, or other frontend sections were changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Manual/single optimizer metric callout cleanup

- User requested removing the small third-line category text from green metric boxes in Manual Optimizer and Single Player Optimization only.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Change:
  - Added a `hideAffects` option to `MetricCallout`.
  - Applied it only to:
    - manual candidate pool metric boxes.
    - single-player optimization metric rows.
  - Full Roster Optimization metric callouts were left unchanged.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Full roster recommended sets scroll pane

- User requested making the Full Roster Optimization recommended sets list a scroll-down pane about the height of the first card.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Change:
  - Wrapped the non-compact `RecommendedSets` list in an internal scroll area.
  - The list no longer stretches the page as multiple recommended set cards render.
  - No data sourcing or optimizer logic changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Teams page header dummy artifact removal and scan

- User noticed Teams page headers still showed dummy/static team metadata for teams present in early mock data, e.g. UConn showing `Big East` while other teams showed `Read-only roster scouting view.`
- Updated:
  - `frontend_site/components/ReadOnlyTeamsView.tsx`
- Change:
  - Teams page subtitle now always displays:
    - `Read-only roster scouting view.`
  - Removed the conditional display of `team?.conference` from the Teams page header.
- Artifact scan findings shared with user:
  - `frontend_site/data/teams.ts` still contains hand-written early team metadata:
    - `conference`
    - `roster_limit`
    - `scholarships_used`
    - `style`
    - `needs`
    - hardcoded teams: UConn, Duke, Indiana, UCLA, Providence.
  - `frontend_site/lib/data.ts` still contains `teamAdjustment()` with hardcoded fit-score boosts for Indiana, UCLA, UConn, and Providence.
  - `frontend_site/data/data_sources.txt` documents those `teams.ts` and `teamAdjustment()` sources because they currently exist.
  - `frontend_site/codex_instructions/frontend_instructions.md` still contains original mock/dummy build instructions, but this is an instruction/archive file and not active app runtime data.
  - `frontend_site/components/RosterOptimizer_old.tsx` is a backup file containing older UI logic and should be ignored unless user wants backups cleaned.
- No generated player data or data sourcing files were changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Route rename cleanup

- User requested route-name cleanup without changing page content or frontend behavior:
  - Main player page should be `/players`.
  - Roster Management page should be `/rosters`.
  - Optimizer and Teams routes were already correctly named.
  - Old route names should be removed.
- Updated routes:
  - Added `frontend_site/app/players/page.tsx` with the existing player leaderboard content.
  - Added `frontend_site/app/rosters/page.tsx` with the existing roster management content.
  - Replaced `frontend_site/app/page.tsx` with a redirect to `/players`.
  - Removed old active route files:
    - `frontend_site/app/portal/page.tsx`
    - `frontend_site/app/recommendations/page.tsx`
    - `frontend_site/app/simulator/page.tsx`
  - Updated active navigation/internal links:
    - Sidebar Players link now points to `/players`.
    - Sidebar Roster Management link now points to `/rosters`.
    - Optimizer back links now point to `/rosters`.
- No page content, data sourcing, optimizer logic, or component behavior was intentionally changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.
  - Build route table now shows:
    - `/`
    - `/optimizer`
    - `/players`
    - `/rosters`
    - `/teams/[teamId]`
  - Old active routes `/portal`, `/recommendations`, and `/simulator` are no longer in the build output.

### 2026-06-11 Data source inventory source-by-source rewrite

- User said the `data_sources.txt` documentation was useful but wanted each upstream source to list its own contribution directly, instead of listing sources as a group and then describing contributions as a group.
- Updated:
  - `frontend_site/data/data_sources.txt`
- Documentation change:
  - Rewrote the upstream sections for:
    - returning/current-roster players.
    - transfer players.
    - high-school recruits.
  - Each upstream CSV/DB/cache path now has its own `Contributes:` list immediately below it.
- No frontend code, generated player data, data sourcing logic, or app behavior was changed.
- Validation:
  - No build run; documentation-only text file change.

### 2026-06-11 Data source glossary added

- User asked for a glossary at the bottom of `data_sources.txt` because some upstream sources are referenced in multiple site sections.
- Updated:
  - `frontend_site/data/data_sources.txt`
- Documentation change:
  - Added an `Upstream source glossary` section at the bottom.
  - Each upstream source appears once with a complete combined list of contributions across the frontend data pipeline.
  - Included model CSVs, DBs, cache directories, draft CSV, alias CSV, and runtime generated data modules where relevant.
- No frontend code, generated player data, data sourcing logic, or app behavior was changed.
- Validation:
  - No build run; documentation-only text file change.

### 2026-06-11 Optimizer court rotation and editable target counts

- User reviewed the new basketball court and requested:
  - rotate the half-court 90 degrees.
  - scale it down proportionally so it fits the optimizer court panel.
  - adjust player locations to match basketball positions after rotation.
  - make optimizer max position targets editable text/number boxes while keeping +/- controls.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Court changes:
  - Changed the court panel to a landscape 16:9 layout.
  - Rotated the generated `basketball-court` SVG layer 90 degrees.
  - Scaled the SVG layer inside the panel to reduce cropping.
  - Updated formation anchors for the rotated court:
    - guard at top of key.
    - guard at wing.
    - forward inside wing/slot.
    - forward baseline/short corner.
    - center in paint.
- Target controls:
  - Position targets now show editable numeric inputs for Guard/Forward/Center max counts.
  - Existing +/- buttons remain.
  - Manual input can temporarily create an invalid total above 15.
  - Invalid target rows turn red and show a prompt asking the user to enter another number.
  - Existing optimizer validation still disables running when target totals exceed 15 or current counts exceed targets.
- No player data, optimizer math, or data sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-11 Frontend data source inventory document

- User asked for an unused documentation-only text file under `frontend_site/data` listing every frontend data source and which displayed/derived data points come from each source.
- Added:
  - `frontend_site/data/data_sources.txt`
- Contents:
  - Documents active runtime data modules:
    - `players.ts`
    - `returningPlayers.ts`
    - `transferPlayers.ts`
    - `hsRecruits.ts`
    - `draftPlayers.ts`
    - `teams.ts`
    - `teamAliases.ts`
  - Documents upstream builder inputs for:
    - returning players.
    - transfers.
    - high-school recruits.
    - draft status.
    - institution aliases.
  - Lists the player fields and displayed/derived data points each source supplies.
  - Includes optimizer-derived metrics and localStorage state as derived/runtime sources.
- No frontend app code, generated player data, or data sourcing logic was changed.
- Validation:
  - No build run; documentation-only text file change.

### 2026-06-11 Optimizer half-court rebuilt from provided court instructions

- User added:
  - `frontend_site/codex_instructions/codex_basketball_court_instructions.md`
  - `frontend_site/codex_instructions/HalfCourt.jsx`
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Court rendering:
  - Kept using the `basketball-court` package.
  - Replaced the previous court theme/options with the exact court theme and package options from the new instruction file:
    - `width: 900`
    - `type: "nba"`
    - `halfCourt: true`
    - `horizontal: true`
    - `theme: "plain"`
    - `ftCircleDashCount: 18`
  - Added the SVG string replacements from the instruction:
    - `class="court-svg"`
    - `role="img"`
    - `aria-label="Clean NBA half court"`
    - `preserveAspectRatio="xMidYMid meet"`
    - rounded outer rect.
  - Scaled the court into the existing optimizer court panel using an absolute SVG background layer.
- Player positioning:
  - Replaced ad hoc player offsets with the requested role-based anchor formation:
    - guard at top of key.
    - guard at wing.
    - forward inside wing/elbow slot.
    - forward baseline/short corner.
    - center inside paint.
  - Preserved existing player card UI and bench/addition behavior.
- No optimizer math, player data, recruit/transfer sourcing, or roster logic was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 22:55 CDT Optimizer court switched to `basketball-court` package

- User clarified that the optimizer court should use the npm `basketball-court` package instead of a hand-built SVG.
- Updated:
  - `frontend_site/package.json`
  - `frontend_site/package-lock.json`
  - `frontend_site/components/RosterOptimizer.tsx`
- Installed:
  - `basketball-court@1.1.2`
- Optimizer court rendering:
  - Replaced the custom hand-drawn SVG line layer in `CourtLineup` with a generated half-court SVG from `basketball-court`.
  - Kept the existing player placement, starter/bench selection, drag/drop behavior, and roster optimization logic unchanged.
  - Added a site-themed court style object using the package-supported keys:
    - `global`
    - `court`
    - `centerCircle`
    - `restrainCircle`
    - `hcline`
    - `tpline`
    - `lane`
    - `innerLane`
    - `ftCircleHigh`
    - `ftCircleLow`
    - `restricted`
    - `backboard`
    - `rim`
  - The generated court uses dark-theme-friendly slate/emerald strokes and sits behind the existing player bubbles.
- Notes:
  - Did not touch the unused roster optimizer `_backup.tsx`.
  - Did not change data sourcing, optimizer math, recruit data, transfer data, or roster logic.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 Optimizer court reference-style half-court

- User asked to use the basketball-court reference style instead of manually improvised geometry, using only half of the court and matching the site theme.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Visual change:
  - Reworked the optimizer court SVG into a top-down half-court based on the reference:
    - top baseline basket
    - court outline
    - half-court line and partial center circle
    - three-point arc with corner lines
    - lane and inner lane
    - free-throw circle with dashed upper half
    - restricted arc, rim, backboard, and lane marks
  - Adjusted starter bubble positions for the top-down half-court.
  - Kept dark/emerald site-compatible colors.
  - No player data or optimizer logic changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 Optimizer court SVG redesign

- User said the revised court still looked weird and provided a side-oriented half-court reference.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Visual change:
  - Replaced stacked CSS court lines with a single SVG court drawing for cleaner geometry.
  - Court now follows a side-oriented reference:
    - left-side hoop/backboard
    - rectangular lane
    - free-throw circle
    - large three-point arc
    - lane hash marks
    - partial center circle on the far side
  - Kept the site-compatible dark blue/emerald theme instead of the reference image colors.
  - Adjusted starter bubble positions to fit the side-oriented court.
  - Player data/selection logic was not changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 Optimizer court cleanup

- User said the court looked off and requested removing the free-throw lines.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Visual change:
  - Removed the free-throw semicircle and lane hash marks from the optimizer court.
  - Kept the outer boundary, three-point arc, lane, restricted area, backboard, hoop, and player placement unchanged.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 Optimizer hidden fits tab removal

- User requested removing the `Hidden Fits` tab from the optimizer bottom results panel and noted an unused roster optimizer backup file should be left alone.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Behavior/layout change:
  - Full roster optimization result tabs now show only:
    - `Recommended Sets`
    - `Individual Fits`
  - Removed the visible `Hidden Fits` tab and its rendered panel from the bottom results UI.
  - Did not edit or touch the unused backup TSX file.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 Optimizer court visual redesign

- User requested that the optimizer basketball court look more like a real half-court while still fitting the dark UI.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Visual change:
  - Replaced the prior tan court block with a darker UI-matched court.
  - Added structured half-court markings:
    - outer boundary
    - three-point arc
    - lane/key
    - free-throw semicircle
    - restricted area
    - backboard and hoop
    - lane hash marks
  - Player placement/data logic was not changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 Frontend numeric display precision

- User asked whether the website was rounding display values to one decimal and requested changing display values to two decimals without changing frontend behavior/data.
- Updated display-only formatting in React components:
  - `frontend_site/components/PlayerDetailPanel.tsx`
  - `frontend_site/components/PlayerTable.tsx`
  - `frontend_site/components/PlayerTable_copy.tsx`
  - `frontend_site/components/PortalSimulator.tsx`
  - `frontend_site/components/ReadOnlyTeamsView.tsx`
  - `frontend_site/components/RecommendationsBoard.tsx`
  - `frontend_site/components/RosterOptimizer.tsx`
- Behavior change:
  - Explicit one-decimal display calls (`toFixed(1)`) now render two decimals.
  - BPR/stat helper calls that requested one decimal now request two decimals.
  - No model outputs, generated data, or sourcing logic were changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 GitHub large-file push cleanup

- User hit GitHub push rejection for files over the 100 MB hard limit and warnings for files over 50 MB.
- Updated:
  - `.gitignore`
- Added ignore coverage for:
  - `models_dir/kmeans_players/kmeans_cluster_outputs/kmeans_player_assignment_explanations_*.csv`
  - `models_dir/same_school_bpr/catboost_transfer_bpr_refactored_outputs/`
  - Existing `*autogluon*` rule covers the Autogluon output model files.
- Removed generated large files from Git tracking with `git rm -r --cached`; local copies remain on disk.
- Amended the unpushed local commit so the rejected large blobs are not included in the push range.
- Verification:
  - `git ls-tree -r --long HEAD | awk '$4 >= 50000000 {print $4, $5}'` returned no files.
  - `git rev-list --objects origin/main..HEAD | git cat-file ...` returned no blobs over 50 MB.

### 2026-06-10 Manual optimizer additions panel placement

- User requested moving the manual remove-player/additions panel under the player search panel in the Manual Optimizer tab.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Behavior/layout change:
  - `Manual Additions` now appears in the left manual candidate column below the candidate pool.
  - Selected players are stacked one per row instead of side-by-side.
  - The selected-player list has a capped scroll area for longer manual selections.
  - The duplicate/right-column additions panel was removed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 05:20:00 CDT Optimizer metric explanation: Flory Bidunga, Sam Orme, and recommendation labels

- User asked why Flory Bidunga can show a negative Total Rating impact despite being 90th percentile in Rim Protection.
- Explanation:
  - Candidate card value is the selected ranking metric.
  - If metric says Total Rating, it is sum of all five category changes, not just Rim Protection.
  - `Affects: Rim Protection` indicates the category with the best improvement.
  - A player can improve Rim Protection but lower total if Spacing/Facilitating/Defense declines outweigh rim/finishing gains.
- User asked about Best Overall Fit vs Total Gain.
- Current implementation:
  - Best Overall Fit and Total Gain are effectively equivalent for a fixed current roster.
  - Best Overall sorts by final total rating.
  - Total Gain sorts by final total minus current total.
  - Current total is constant across candidates/sets, so primary ranking is the same. Tie-breakers are also effectively equivalent.
- User asked why Sam Orme can show a stronger individual Auburn score than Flory Bidunga but not be in the optimized roster.
- Explanation:
  - Individual cards are one-player marginal scores: current roster plus that one candidate.
  - Full roster optimization ranks multi-player combinations under position/roster constraints.
  - A player with a better solo delta can be excluded if the selected combination fills limited slots better or if another player pairing produces a better total set score.
- No code changed.


### 2026-06-10 05:20:00 CDT Optimizer metric explanation: Flory Bidunga and Best Overall vs Total Gain

- User asked why Flory Bidunga can show a negative `Total Rating` impact despite being 90th percentile in Rim Protection.
- Explanation:
  - The green candidate card value is the selected ranking metric.
  - If the metric says `Total Rating`, it is the sum of all five category changes, not just Rim Protection.
  - `Affects: Rim Protection` indicates the category with the best improvement for that player.
  - Therefore a player can improve Rim Protection but still have negative total impact if he lowers Spacing / Facilitating / Defense enough.
- User also asked about `Best Overall Fit` vs `Total Gain`.
- Current implementation detail:
  - For a fixed current roster, `Best Overall Fit` and `Total Gain` are effectively equivalent right now.
  - `Best Overall Fit` sorts by final total rating.
  - `Total Gain` sorts by final total rating minus current total rating.
  - Since current total rating is constant across candidates/sets, both produce the same primary ranking.
  - Tie-breakers are also effectively equivalent in the current implementation.
- No code was changed in this explanatory pass.

### 2026-06-10 05:12:00 CDT Full roster tab placement and mode selector revert

- User requested:
  - move Recommended Sets / Individual Fits / Hidden Fits under the pentagon panel.
  - move Back / Reset to the upper-right page area.
  - revert hamburger mode selector back to three separate toggles.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Full Roster Optimization:
  - Results tabs and their content now live in the right column under `Roster Rating Overlay`.
  - Court/bench remains alone in the left column.
- Page actions:
  - Back / Reset row was pulled upward toward the top-right page area.
- Mode selector:
  - Reverted from hamburger dropdown back to the three-button segmented toggle:
    - Full Roster Optimization.
    - Manual Optimizer.
    - Single Player Optimization.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 05:08:00 CDT Individual Fits position filter

- User requested the Full Roster Optimization `Individual Fits` tab stop stacking Guards, Forwards, and Centers on top of each other.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Individual Fits:
  - Added a position filter segmented control:
    - Guards.
    - Forwards.
    - Centers.
  - The panel now shows only the selected position group at a time.
  - Defaults to Guards.
  - Keeps the top 10 display within the selected group.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 04:58:00 CDT Manual candidate pagination and optimizer mode hamburger

- User requested removing the top-10 cap so GMs can inspect how any eligible player changes the roster dynamic.
- Updated:
  - `frontend_site/lib/optimizer.ts`
  - `frontend_site/components/RosterOptimizer.tsx`
- Fit calculation:
  - Removed the top-10-per-position cap from `buildIndividualFits`.
  - All eligible candidates now receive individual fit calculations.
- Manual Candidate Pool:
  - Added pagination with `20` candidates per page.
  - Added bottom navigator:
    - visible range.
    - current page / total pages.
    - Prev / Next buttons.
  - Filter/search/sort changes reset the manual candidate page back to page 1.
- Optimizer header:
  - Added a page-level top-right Back / Reset action row.
  - Replaced the wide three-tab mode selector with a compact hamburger-style dropdown.
  - Full Roster Optimization still shows the target controls and Run Optimizer in a compact right-side panel.
  - Manual Optimizer and Single Player Optimization no longer show target controls.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 04:48:00 CDT Manual optimizer HS filter diagnosis

- User asked why High School shows no players in the Manual Optimizer candidate pool.
- Diagnosis:
  - HS candidate data exists.
  - Local check found:
    - `630` total HS recruits.
    - `121` uncommitted HS recruits.
    - `121` uncommitted HS recruits with BPR plus all five optimizer skill percentiles.
  - The empty UI is caused by ranking/filter order:
    - `buildIndividualFits` currently returns only the top 10 fits per position across all candidate sources.
    - Manual Candidate Pool then applies the source filter afterward.
    - Since those top fits are dominated by transfers, filtering that already-capped list to `High School` can produce zero rows.
- No code was changed in this diagnostic pass.

### 2026-06-10 04:40:00 CDT Optimizer header structured two-panel control card

- User requested the first optimizer page use a cleaner two-panel header/control structure, similar to a provided reference but without decorative graphics.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Loaded roster header:
  - Converted the header into a two-panel card.
  - Left panel:
    - loaded roster label.
    - team name.
    - roster count.
    - optimizer-field warning.
    - mode toggle underneath the roster text.
  - Right panel:
    - Back and Reset buttons pinned at the top.
    - In Full Roster Optimization only:
      - target rows.
      - Run Optimizer button.
    - In Manual Optimizer and Single Player Optimization:
      - only Back and Reset show.
- Target rows:
  - Changed target controls from cramped two-by-two tiles into clearer stacked rows inside the right-side control panel.
  - Kept labels readable and buttons large enough to use.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 04:32:00 CDT Optimizer header/control cleanup and court bubble sizing

- User requested the optimizer shell be cleaned up after the control bar layout degraded.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Loaded roster header:
  - Moved the optimizer mode toggle underneath the loaded roster/team text.
  - Kept the roster text, warning, and toggle together in the left side of the header.
- Right-side controls:
  - Moved Back, Reset, and full-roster-only controls into a compact right-side card aligned with the loaded roster header.
  - Full Roster Optimization shows:
    - Back.
    - Reset.
    - target counts.
    - Run Optimizer.
  - Manual Optimizer and Single Player Optimization show only:
    - Back.
    - Reset.
  - Target controls now render as a compact two-by-two square in that right-side card instead of a wide strip.
- Court:
  - Reduced player bubble width and internal avatar/text sizing.
  - Moved court spots slightly farther apart to reduce overlap between bubbles.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 04:22:00 CDT Optimizer target row and court width correction

- User reported the target controls were still stacking and the full-roster radar panel was pushed off page.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Target controls:
  - Forced target cards into four columns instead of responsive two-column stacking.
  - Used compact readable labels for position cards:
    - Guard.
    - Forward.
    - Center.
  - Kept Roster Size visible in the same row.
  - Tightened target card widths and text sizing so all four cards stay beside each other.
- Full Roster Optimization layout:
  - Reduced the court visual max width and height.
  - Adjusted court arc dimensions to fit the smaller court.
  - Changed full-roster grid column minimums so the radar panel stays within the viewport instead of being pushed off page.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 04:15:00 CDT Optimizer control readability and full-roster column correction

- User rejected the compressed target controls and requested cleaner layout across all optimizer modes.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Header / mode controls:
  - Restored the loaded-roster header to only roster identity plus mode toggle.
  - Reordered mode toggle to:
    - Full Roster Optimization.
    - Manual Optimizer.
    - Single Player Optimization.
- Global optimizer controls:
  - Moved Back, Reset, Run Optimizer, and Targets into their own full-width control card below the header.
  - Restored readable labels and larger hit targets in the target controls.
  - Targets now use horizontal responsive cards with full labels instead of tiny/truncated boxes.
- Full Roster Optimization:
  - Forced the page back to dual columns at normal desktop width.
  - Left column:
    - Optimized Roster Court.
    - recommendation tabs and set/fit cards under the court.
  - Right column:
    - Roster Rating Overlay.
- Single Player Optimization:
  - Removed the radar/court panel again.
  - Page now contains only Recommendation View plus the single-player fit panel, per user request.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 04:05:00 CDT Optimizer alignment correction: header controls, single-player controls, and court-first full view

- User requested follow-up layout fixes after reviewing the latest optimizer state.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
- Header controls:
  - Moved Back, Reset, Run Optimizer, and Targets into the loaded-roster header card.
  - Targets are now a compact horizontal strip instead of a tall side panel.
  - This aligns the control area with the team/header rectangle.
- Full Roster Optimization:
  - Recommended sets, individual fits, and hidden fits were moved back under the court.
  - The right side is now reserved for the Roster Rating Overlay.
  - The full-view grid gives the radar side a wider minimum width to avoid cramped/overflowed metric rows.
- Radar overlay:
  - Metric rows now use `minmax(0, 1fr)` so they shrink inside the card instead of pushing beyond the border.
- Single Player Optimization:
  - Removed the global Recommendation View block above the page.
  - Recommendation View now sits in the same left column as the Single Player Optimization list, matching the Manual Optimizer layout.
- Manual Optimizer:
  - Keeps the same left-column Recommendation View plus Manual Candidate Pool arrangement from the prior pass.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 03:45:00 CDT Optimizer rating math explanation requested

- User requested the exact math for how the Optimizer determines the category rating a player adds on the page.
- Current implementation reference:
  - `frontend_site/lib/optimizer.ts`
  - `calculateTeamRatings`
  - `ratingChanges`
  - `buildIndividualFits`
- Formula:
  - Current roster category rating:
    - `sum(player_bpr * player_category_percentile) / sum(abs(player_bpr))`
  - Final roster category rating after adding candidate:
    - `sum(player_bpr * player_category_percentile, including candidate) / sum(abs(player_bpr), including candidate)`
  - Candidate category gain displayed on page:
    - `final_category_rating - current_category_rating`
  - Candidate total gain:
    - `sum(final_category_rating across five categories) - sum(current_category_rating across five categories)`
  - Candidate weakest-category gain:
    - `min(final_category_ratings) - min(current_category_ratings)`

### 2026-06-10 03:55:00 CDT Optimizer layout follow-up: manual pool, dual panels, and top-fit behavior

- User requested additional optimizer layout fixes and asked to restore the top-fit emphasis.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
  - `frontend_site/lib/optimizer.ts`
- Manual Candidate Pool:
  - Moved Recommendation View into the same left column as Manual Candidate Pool.
  - Made the Manual Candidate Pool column self-sized instead of stretching to match the right column.
  - This prevents the large blank area at the bottom of the candidate pool.
  - Candidate pool now renders ranked fit rows from the fit map instead of all raw candidates.
  - Empty state now says no ranked fits match the filters.
- Top-fit behavior:
  - Restored `buildIndividualFits` to return top 10 ranked fits per position.
  - This keeps the UI focused on best fits instead of showing every eligible player.
- Full Roster Optimization:
  - Reworked dual-panel layout:
    - left panel prioritizes Optimized Roster Court.
    - right panel contains Roster Rating Overlay and recommendation tabs/cards below it.
  - Recommendation cards use a compact mode in the right panel.
  - Bench grid now uses fewer/wider columns so bench player names have more room.
- Single Player Optimization:
  - Restored dual-panel layout.
  - Left panel shows ranked one-player fits.
  - Right panel shows the rating overlay and court for the top visible one-player fit.
- Top controls:
  - Made the top-right target/settings column narrower.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 03:40:00 CDT Optimizer dual-panel restoration and manual metric coverage fix

- User requested another optimizer layout pass and noted missing metric boxes for some manual candidates.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
  - `frontend_site/lib/optimizer.ts`
- Full Roster Optimization:
  - Restored a dual-panel results layout.
  - Left panel contains result tabs and recommendation lists.
  - Right panel contains the roster rating overlay and optimized court.
- Top controls:
  - Moved `Back` and `Reset` into a compact top-right action stack.
  - Moved roster target controls into that top-right stack.
  - Made target controls much smaller.
  - Moved `Run Optimizer` under the compact target controls.
- Manual Candidate Pool:
  - Fixed missing candidate impact boxes for players like John Blackwell.
  - Root cause:
    - `buildIndividualFits` only returned the top 10 fits per position.
    - Manual rows outside that top 10 had no fit object, so no green metric box rendered.
  - Fix:
    - `buildIndividualFits` now returns all ranked fits.
    - Display components still slice where a top-N view is intended.
  - Shrunk compact metric boxes so they take less room in candidate rows.
- Rating overlay:
  - Replaced typed `->` text with a lucide arrow icon in the before/after rating rows.
- Data-source note:
  - No generated player data or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 03:25:00 CDT Optimizer controls, manual candidate ranking, and court label cleanup

- User requested a final optimizer polish pass while leaving the Teams page structure otherwise unchanged.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
  - `frontend_site/components/ReadOnlyTeamsView.tsx`
  - `frontend_site/components/RecommendationsBoard.tsx`
- Optimizer load/reset behavior:
  - Removed the previous `Reload Roster` button.
  - Added two top actions:
    - `Back to Roster Management`
    - `Reset`
  - Reset now reloads the current saved Roster Management scenario, clears optimizer results/manual picks, and restores default target counts.
  - Opening `/optimizer` directly now derives the payload from the saved Roster Management state when available.
  - This makes the Optimizer nav link and `Load to Optimizer` produce the same loaded roster state.
- Run Optimizer button:
  - Now only appears in Full Roster Optimization mode.
  - It is hidden in Single Player Optimization and Manual Optimizer modes.
- Target allotments:
  - Position target +/- controls now keep the total target at 15 by redistributing across the other positions.
  - Increasing one position takes a slot from the currently largest other target group.
  - Decreasing one position gives a slot to the currently largest other target group.
- Removed optimizer current-ratings card:
  - Removed the `Current Team Ratings` panel from the Optimizer page because the radar/overlay already carries that information.
- Radar labels:
  - Added vertex labels to the optimizer comparison radar so users can identify each category.
- Manual Candidate Pool:
  - Recommendation View now ranks/sorts the manual candidate pool instead of controlling the Manual Roster Impact summary.
  - Each candidate row now shows a small impact callout next to the `Add` button.
  - Removed the top-right impact callout from Manual Roster Impact because candidate-level impact is now shown in the pool.
  - Reworked candidate rows from full-width buttons to normal row containers to avoid scroll/cropping weirdness.
- Court labels:
  - Court slots now use only:
    - `Guard` for #1 and #2.
    - `Forward` for #3 and #4.
    - `Center` for #5.
  - Removed more specific labels like Point Guard, Shooting Guard, Small Forward, and Power Forward.
- Team description cleanup:
  - Removed generated style/needs copy from the read-only Teams header.
  - Removed the same generated style/needs line from the Recommendations header.
- Data-source note:
  - No player data generation or recruit/transfer sourcing was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 02:45:00 CDT Optimizer spacing pass, weighted roster radar, and read-only Teams page

- User requested more usable space for Manual Optimizer, weighted roster radar validation, and a non-editable Teams page that mirrors Roster Management.
- Updated:
  - `frontend_site/components/RosterOptimizer.tsx`
  - `frontend_site/components/PortalSimulator.tsx`
  - `frontend_site/components/ReadOnlyTeamsView.tsx`
  - `frontend_site/app/teams/[teamId]/page.tsx`
- Optimizer layout:
  - Moved the prior side controls above the main optimizer panels.
  - Manual Optimizer now gives the candidate pool and results area more horizontal room.
  - Manual Optimizer result column now places the court above the rating overlay for easier drag/drop interaction.
- Manual candidate pool:
  - Added source filter:
    - All Sources.
    - Transfers.
    - HS Recruits.
  - Added position filter:
    - All Positions.
    - Guards.
    - Forwards.
    - Centers.
  - Tightened/widened candidate rows so the pool no longer has a large blank area blocking candidate visibility.
- Roster Management radar:
  - Changed the Team Skills Radar in Roster Management to use the shared optimizer weighted formula:
    - player skill percentile weighted by projected BPR.
    - denominator is total absolute projected BPR.
  - This keeps roster-management radar math aligned with Optimizer.
- Teams page:
  - Rebuilt `/teams/[teamId]` as a read-only Roster Management style page.
  - Added a team dropdown.
  - Added summary rating cards, non-editable current roster list, weighted Team Skills Radar, and a depth chart.
  - No add/remove/stay/leave controls are exposed on Teams.
- UConn weighted radar validation:
  - Default UConn roster count after draft exclusions:
    - `19`
  - Players with complete usable BPR plus all five skill percentiles:
    - `15`
  - Total absolute BPR denominator:
    - `59.23`
  - Weighted radar values:
    - Spacing: `56.3`
    - Facilitating: `53.4`
    - Rim Protection: `56.1`
    - Defense: `50.9`
    - Finishing: `48.1`
  - Players included in the weighted calculation:
    - Silas Demary Jr. (`8.32`)
    - Braylon Mullins (`6.25`)
    - Solo Ball (`5.45`)
    - Jayden Ross (`5.42`)
    - Malachi Smith (`5.24`)
    - Eric Reibe (`3.95`)
    - Isaiah Shaw (`-0.27`)
    - Jaye Nash (`0.81`)
    - Jaylin Stewart (`2.77`)
    - Najai Hines (`5.19`)
    - Nikolas Khamenia (`4.18`)
    - Nils Machowski (`2.24`)
    - Oskar Giltay (`2.84`)
    - Junior County (`2.99`)
    - Colben Landrew (`3.32`)
- Data-source note:
  - No generated player data or recruit/transfer sourcing files were changed in this pass.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-08 02:31:07 CDT Canonical institution display path fix

- User clarified aliases should be display-normalized across player types while raw generated data can remain separate.
- Root cause of previous no-op:
  - `frontend_site/app/page.tsx` was importing raw `returningPlayers`, `transferPlayers`, and `hsRecruitPlayers` directly.
  - `frontend_site/data/players.ts` also did not include `returningPlayers` in its canonicalized combined export.
  - Therefore Braylon Mullins and other returners bypassed `canonicalizeInstitution()` entirely on the Players page.
- Updated `frontend_site/data/players.ts`:
  - Added `returningPlayers` to the canonicalized combined `players` export.
  - Raw generated files remain unchanged.
- Updated `frontend_site/app/page.tsx`:
  - Removed direct raw data imports.
  - The page now imports only the canonicalized `players` export from `@/data/players`.
  - Returning mode uses `players.filter((player) => player.player_source === "roster")`, so returners use canonicalized institution names.
- Alias behavior:
  - Does not assume returners/transfers are always opposite aliases.
  - Uses the CSV-derived equivalence groups for all player types and all normalized institution fields.
  - Supports multi-alias groups such as Miami aliases.
- Validation:
  - Braylon Mullins raw generated team is still `Connecticut`.
  - The Players page display path now canonicalizes him to `UConn`.
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-09 23:18:25 CDT Transfer frontend 247 display fallback and height cleanup

- User asked to inspect the frontend site data path because Eric Reibe displayed with missing profile image, missing 247 rating, and corrupted height text (`1-Jul`) despite having correct 247 data.
- Data-source tracing:
  - `frontend_site/scripts/build_transfer_players.py` generates `frontend_site/data/transferPlayers.ts`.
  - It already reads the user-specified dual BPR file:
    - `models_dir/transfer_bpr/catboost_transfer_bpr_dual_inference_outputs/dual_transfer_bpr_inference_2026_20260607_190712/dual_transfer_bpr_predictions_2026.csv`
  - It also reads `data_dir/247_bv_transf_matched.db` for 247 metadata, but only applied those 247 display fields when `safe_247_metadata_match()` passed.
- Eric Reibe root cause:
  - Eric's dual BPR row contains correct 247 values:
    - `247_player_key = 46139349`
    - `247_avatar_url = https://s3media.247sports.com/Uploads/Assets/883/343/13343883.jpg`
    - `247_transfer_rating = 0.93`
    - `247_rating = 0.93`
    - `247_transfer_rank = 66`
    - `247_height = 7-1`
  - The frontend dropped those fields because the DB metadata gate required `overall_match_score >= 90`; Eric's score was `87.5` due to `team_score = 50`, even though `name_score = 100`, `match_flag = True`, and the row was marked `matched_247_to_db1`.
  - His bad height came from `allyears_ht = 1-Jul`, an Excel-style date corruption of `7-1`, and the builder preferred `allyears_ht` before cleaner transfer/247 height fields.
- Updated `frontend_site/scripts/build_transfer_players.py`:
  - Kept origin/destination logic gated by the stricter existing `safe_247_metadata_match()` rule.
  - Added a display-only 247 fallback from the dual BPR CSV when:
    - `247_player_key` exists,
    - `match_flag` is truthy,
    - and `247_full_name` exactly normalizes to the transfer player name.
  - Uses that display-only fallback for profile image, position, height, weight, stars, rating, rank, player key, and 247 status.
  - Added `247_height` to the metadata query.
  - Changed height selection to prefer trusted 247/transfer height fields before `allyears_ht`.
  - Added a month-name height normalizer for corrupted values such as `1-Jul -> 7-1`, `10-Jun -> 6-10`, and `11-May -> 5-11`.
  - Changed generated `transferPlayers.ts` output to `JSON.parse(...) as Player[]` to avoid TypeScript's "union type too complex to represent" error after more optional fields became populated.
- Updated `frontend_site/scripts/build_returning_players.py`:
  - Added the same month-name height normalizer for returning-player heights.
- Regenerated:
  - `frontend_site/data/transferPlayers.ts`
  - `frontend_site/data/returningPlayers.ts`
- Validation:
  - Before cleanup, generated frontend data had 98 transfer rows and 69 returning-player rows with month-name height corruption; HS recruit data had 0.
  - After regeneration:
    - transfer rows with bad month-style heights: 0.
    - returning rows with bad month-style heights: 0.
    - HS recruit rows with bad month-style heights: 0.
  - Eric Reibe generated transfer row now has:
    - profile image populated from 247.
    - `height = 7-1`.
    - `weight = 260`.
    - `transfer_247_rating = 0.93`.
    - `transfer_247_rank = 66`.
    - `transfer_247_player_key = 46139349`.
    - `current_team = Connecticut`.
    - `new_team = USC`.
  - `python frontend_site/scripts/build_transfer_players.py` completed successfully:
    - players: 2,375.
    - with BPR: 2,375.
    - with 247 metadata/display fields: 1,510.
    - with skill percentiles: 1,840.
  - `python frontend_site/scripts/build_returning_players.py` completed successfully:
    - players: 1,898.
    - source rows: 3,743.
    - excluded transfer rows: 1,845.
    - with projected BPR: 1,898.
    - with images: 742.
    - with skill percentiles: 1,894.
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-09 23:41:55 CDT NBA draft prospect CSV frontend-player matching

- User asked to annotate `frontend_site/data/2026_nba_draft_prospects.csv` by matching as many draft prospects as possible to frontend site players, without changing frontend site behavior yet.
- Initial instruction emphasized matching to Returning players, but user clarified Keyshawn Hall is an exception because he appears on the Transfer page.
- No frontend site code or generated player data was edited for this step.
- Edited only:
  - `frontend_site/data/2026_nba_draft_prospects.csv`
- Added frontend match/audit columns:
  - `frontend_match_status`
  - `frontend_match_source`
  - `frontend_match_generated_file`
  - `frontend_match_player_name`
  - `frontend_match_current_team`
  - `frontend_match_new_team`
  - `frontend_match_player_id`
  - `frontend_match_personal_identifier`
  - `frontend_match_returning_bvt_pid`
  - `frontend_match_transfer_barttorvik_trid`
  - `frontend_match_name_score`
  - `frontend_match_team_score`
  - `frontend_match_notes`
- Matching sources:
  - `frontend_site/data/returningPlayers.ts`
  - `frontend_site/data/transferPlayers.ts`
- Matching logic:
  - Conservative normalized name + team matching.
  - Handles suffix differences such as `Darius Acuff` vs `Darius Acuff Jr.`.
  - Handles curly apostrophes such as `Ja’Kobi Gillespie`.
  - Handles common team aliases such as `UConn -> Connecticut`, `Southern Methodist -> SMU`, `Miami (FL) -> Miami FL`, `Miami (Ohio) -> Miami OH`, and `N.C. State -> N.C. State`/North Carolina State.
  - Handles accidental adjacent duplicate name tokens such as `Tyler Nickel Nickel -> Tyler Nickel`.
- Validation:
  - CSV row count stayed 88.
  - Column count increased from 8 to 21.
  - Matched rows: 74.
  - Unmatched rows: 14.
  - Matched frontend source counts:
    - 65 `roster` / Returning rows.
    - 9 `transfer` rows.
  - Confirmed examples:
    - Cameron Boozer / Duke -> `returning-134971`, `frontend_match_personal_identifier = 134971`.
    - Nate Ament / Tennessee -> `returning-134712`, `frontend_match_personal_identifier = 134712`.
    - Keyshawn Hall / Auburn -> `transfer-1372`, `frontend_match_personal_identifier = 76060`, `frontend_match_transfer_barttorvik_trid = 76060`.
    - Peter Suder / Miami (Ohio) -> `transfer-3276`, `frontend_match_personal_identifier = 77037`.
    - Ernest Udeh Jr. / Miami (FL) -> `transfer-3448`, `frontend_match_personal_identifier = 76673`.
    - Tyler Nickel Nickel / Vanderbilt -> `transfer-2493`, `frontend_match_personal_identifier = 76761`.
  - Remaining unmatched rows are mostly international/G League/non-site prospects or players absent from generated frontend player data:
    - Mohammad Amini.
    - Bassala Bagayoko.
    - Pavle Bačko.
    - Sergio De Larrea.
    - Francesco Ferrari.
    - Marc-Owen Fodzo Dada.
    - Vsevolod Ishchenko.
    - Jack Kayil.
    - Malique Lewis.
    - Karim Lopez.
    - Jayden Quaintance.
    - Luigi Suigo.
    - Noam Yaacov.
    - Reynan dos Santos.

### 2026-06-10 00:01:11 CDT Draft tab migration for matched prospects

- User asked to move every matched NBA draft prospect from the frontend Returning/Transfer tabs into a new `Draft` tab, without changing the existing data sourcing or player detail panels.
- Implemented Draft as a display/status flag over the existing player records:
  - Returning players remain `player_source = "roster"` internally.
  - Transfer players remain `player_source = "transfer"` internally.
  - This preserves each player's existing expanded detail panel behavior and data fields.
- Added:
  - `frontend_site/data/draftPlayers.ts`
    - Contains the 73 unique frontend player IDs matched from `frontend_site/data/2026_nba_draft_prospects.csv`.
    - The CSV had 74 matched rows because `Tyler Nickel` / `Tyler Nickel Nickel` both map to `transfer-2493`.
- Updated:
  - `frontend_site/data/players.ts`
    - Imports `draftPlayerIds`.
    - Adds optional `draft_status?: boolean` to `Player`.
    - Sets `draft_status` during canonical player mapping when a player's frontend ID is in `draftPlayerIds`.
  - `frontend_site/app/page.tsx`
    - Adds the `Draft` toggle next to `Returning`, `HS Recruits`, and `Transfers`.
    - Removes draft-flagged players from the Returning/HS/Transfer tab inputs.
    - Feeds only draft-flagged players into the Draft tab.
  - `frontend_site/components/PlayerTable.tsx`
    - Adds `draft` to `PlayerMode`.
    - Adds Draft table mode with only:
      - player mini card.
      - position.
      - team.
      - status badge showing `Draft`.
      - BPR.
    - Uses projected BPR for returning draft players and transfer BPR for transfer draft players.
    - Keeps the original expanded dropdown panel unchanged by preserving the original player source.
  - `frontend_site/lib/data.ts`
    - Excludes `draft_status` players from transfer portal players, HS player helpers, and team roster/player lookups.
    - This removes draft entrants from the team portal simulator rosters/targets, including examples like Duke's Cameron Boozer and Isaiah Evans.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.
  - Verified draft ID coverage against the annotated CSV:
    - matched CSV rows: 74.
    - unique matched frontend player IDs: 73.
    - IDs in `draftPlayers.ts`: 73.
    - missing IDs: none.
    - extra IDs: none.
    - duplicate frontend match in CSV: `transfer-2493`.
  - Confirmed `returning-134971` (Cameron Boozer) and `returning-76818` (Isaiah Evans) are in `draftPlayers.ts`.

### 2026-06-10 00:31:12 CDT HS recruit skill percentile pentagons

- User asked to add pentagon/radar skill percentiles to HS recruit dropdowns using:
  - `data_dir/player_percentile/hs_freshman_prior_percentile_outputs/hs_2026_projected_skill_percentiles.csv`
- User warned that `player_key` is the 247 player key, not necessarily the frontend ID.
- Verified the frontend HS recruit records already store:
  - `hs_player_key`
  - frontend `player_id` values like `hs-<player_key>`
- Implemented the join through the HS generator on `player_key`, not by display name:
  - `frontend_site/scripts/build_hs_recruits.py`
    - Added `HS_SKILL_PERCENTILES` source.
    - Reads the five percentile columns:
      - `spacing_percentile`
      - `facilitating_percentile`
      - `rim_protection_percentile`
      - `defense_percentile`
      - `finishing_percentile`
    - Merges by `player_key`.
    - Adds a duplicate-key guard.
    - Adds a row-count guard so the merge cannot silently duplicate or drop HS rows.
    - Emits the existing frontend skill fields for HS recruits:
      - `skill_spacing_percentile`
      - `skill_facilitating_percentile`
      - `skill_rim_protection_percentile`
      - `skill_defense_percentile`
      - `skill_finishing_percentile`
  - `frontend_site/components/PlayerDetailPanel.tsx`
    - Added an HS-specific dropdown branch.
    - Keeps the existing HS dropdown profile, playtype probability, and rank content.
    - Adds the existing `SkillRadar` pentagon panel beside that content when skill fields exist.
    - Uses HS subtitle `Projected freshman skill percentiles`.
    - Returning and transfer radar subtitle/behavior remains unchanged.
- Regenerated:
  - `frontend_site/data/hsRecruits.ts`
- Validation:
  - Percentile source rows: 367.
  - Unique `player_key` values in percentile source: 367.
  - Duplicate keys: 0.
  - Frontend HS recruits after regeneration: 630.
  - HS recruits with at least one skill percentile: 366.
  - The one source-row difference is consistent with the generator's existing excluded HS player key list.
  - Example matched record:
    - `Dink Pate`, `hs_player_key = 46103857`, now has all five skill percentile fields.
  - Example unmatched/no-radar record:
    - `Brayden Fogle`.
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 00:36:06 CDT HS dropdown visual restoration after pentagon add

- User showed that adding the HS pentagon made the HS recruit dropdown lose the more polished animated/card treatment compared with transfer dropdowns.
- Updated:
  - `frontend_site/components/PlayerDetailPanel.tsx`
- Replaced the ad hoc HS dropdown layout with a dedicated `HsProfileCard` patterned after `TransferProfileCard`:
  - Header and HS recruit badge.
  - Committed/current school chip.
  - Projected role callout.
  - Metric cards for:
    - national rank.
    - position rank.
    - stars.
    - HS BPR.
  - Scouting/fit copy.
  - Animated playtype probability bars using the same loading/width transition style as transfer dropdowns.
- Kept the HS skill percentile pentagon beside the profile card.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 00:40:21 CDT Skill radar vertex labels

- User asked to add small text labels to the pentagon/radar vertices across the website, without changing any data.
- Updated only:
  - `frontend_site/components/PlayerDetailPanel.tsx`
- Added labels in the shared `SkillRadar` SVG so they apply anywhere the pentagon appears:
  - returning players.
  - transfer players.
  - HS recruits.
- Labels are placed just outside the radar's outer vertices.
- Added small helper functions:
  - `radarAxisLabel`
    - Shortens `Rim Protection` to `Rim Prot.` to reduce SVG label crowding.
  - `radarLabelAnchor`
    - Aligns labels based on their side of the chart.
- No data generation or source files were changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 00:44:46 CDT Returning stats compaction and radar label tightening

- User suggested two layout improvements:
  - Returning player season stats should be consolidated into two rows so the stats card uses space better.
  - Radar vertex labels were bleeding into adjacent sections and should be moved closer to the vertices and made smaller.
- Updated only:
  - `frontend_site/components/PlayerDetailPanel.tsx`
- Returning season stats changes:
  - Split stats into:
    - primary row: `PPG`, `RPG`, `APG`, `SPG`, `BPG`.
    - secondary row: `GP`, `MP`, `FT`, `BPR`.
  - Added a horizontal divider between the two rows.
  - Centered stat items within each row.
  - Preserved BPR emphasis styling.
- Radar label changes:
  - Moved labels closer to the polygon by reducing label radius offset.
  - Reduced label text size.
  - Shortened crowded labels:
    - `Facilitating` -> `Facil.`
    - `Rim Protection` -> `Rim`
    - `Finishing` -> `Finish`
  - No radar data or percentile values were changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 00:48:32 CDT Returning BPR blue emphasis

- User asked to add the same blue highlighted BPR box used in HS and transfer dropdowns to returning players and draft players.
- Updated only:
  - `frontend_site/components/PlayerDetailPanel.tsx`
- Changed the emphasized `ReturningStat` style from the default border to:
  - `border-sky-300`
  - `dark:border-sky-600`
- This applies to returning player dropdowns.
- Draft players retain their original detail source:
  - returning draft players use the returning dropdown and inherit this blue BPR styling.
  - transfer draft players already used the transfer dropdown blue BPR styling.
- No data changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.

### 2026-06-10 02:07:10 CDT Roster Gap Optimizer frontend implementation

- User said they edited `frontend_site/codex_instructions/roster_gap_optimizer_questions.md` and asked to start implementing the optimizer on the frontend.
- User emphasized:
  - Do not edit recruit data sourcing.
  - Only one small Players-page HS view fix should be made for uncommitted recruits.
  - Most edits should add the Optimizer page and functionality.
- Read:
  - `frontend_site/codex_instructions/roster_gap_optimizer_questions.md`
  - `frontend_site/codex_instructions/roster_gap_optimizer_codex_spec.md`
- Installed required frontend solver dependency:
  - `glpk.js`
  - Initial sandboxed install failed due DNS/network restriction.
  - Re-ran `npm install glpk.js` with approved network access.
  - Updated `frontend_site/package.json` and `frontend_site/package-lock.json`.
- Added optimizer normalization and calculation helpers:
  - `frontend_site/lib/optimizer.ts`
    - Uses existing generated `Player` objects only; no generated recruit sourcing changed.
    - Normalizes optimizer IDs in memory:
      - transfer: `optimizer_player_id = "transfer:" + transfer_barttorvik_trid`
      - HS recruit: `optimizer_player_id = "hs:" + hs_player_key`
      - returning/current roster: `returning:<returning_bvt_pid>` or fallback roster ID.
    - Normalizes position groups to `G`, `F`, `C`.
    - Uses five active percentile categories:
      - `spacing_percentile`
      - `facilitating_percentile`
      - `rim_protection_percentile`
      - `defense_percentile`
      - `finishing_percentile`
    - Maps from existing frontend fields:
      - `skill_spacing_percentile`
      - `skill_facilitating_percentile`
      - `skill_rim_protection_percentile`
      - `skill_defense_percentile`
      - `skill_finishing_percentile`
    - Excludes optimizer candidates missing required fields.
    - Candidate rules:
      - transfers only if status is `entered` or `committed`.
      - HS recruits only if uncommitted.
      - returning players are current-roster context only, not recommendation candidates.
    - Team rating formula uses:
      - `sum(projected_bpr * skill_percentile) / sum(abs(projected_bpr))`
    - Implements ranking helpers for recommended sets, individual fits, and hidden fits.
- Added optimizer roster localStorage handoff:
  - `frontend_site/lib/optimizerStorage.ts`
    - Storage key: `roster-lab-optimizer-roster`
    - Stores selected `teamName`, active roster `playerIds`, and `loadedAt`.
- Updated Roster Management:
  - `frontend_site/components/PortalSimulator.tsx`
    - Added `Load to Optimizer` button.
    - Saves the active roster management state:
      - default team roster
      - minus user removals
      - plus transfer/HS additions
    - Routes to `/optimizer`.
  - `frontend_site/app/simulator/page.tsx`
    - Renamed visible page title from `Transfer Portal Simulator` to `Roster Management`.
- Updated navigation:
  - `frontend_site/components/Shell.tsx`
    - Renamed sidebar item `Simulator` to `Roster Management`.
    - Changed icon to a clipboard-style icon.
    - Added new `Optimizer` tab with a science-style icon.
- Added new Optimizer route and UI:
  - `frontend_site/app/optimizer/page.tsx`
  - `frontend_site/components/RosterOptimizer.tsx`
- Optimizer UI/functionality:
  - Loads roster from Roster Management localStorage payload.
  - Shows loaded team and roster count.
  - Target controls default to:
    - `G = 5`
    - `F = 6`
    - `C = 4`
    - total max `15`.
  - Enforces:
    - target total cannot exceed 15.
    - optimizer disabled if active roster has more than 15 players.
    - optimizer disabled if current G/F/C count exceeds target G/F/C count.
  - Shows red warning messages for invalid states.
  - Hides/disables ratings and single-player optimization when roster exceeds 15.
  - Uses `glpk.js` browser solver to solve MILP roster-addition models.
  - Applies top-200-per-position cap after eligibility and needed-position filtering.
  - Runs multiple objective variants:
    - total contribution.
    - each five-category specialist objective.
    - current-weakness objective.
    - weakness-balanced objective.
  - Iteratively excludes prior selected sets to collect alternate solutions.
  - Exact-ranks solution sets after GLPK by:
    - final total rating.
    - final weakest category.
    - added projected BPR.
  - Displays:
    - full recommended sets.
    - top individual fits by position.
    - hidden fits.
  - Supports sorting/view modes:
    - Best Overall Fit.
    - Total Gain.
    - Weakest Category Gain.
    - Added BPR.
    - category-specific gains for all five active categories.
  - Supports category filter:
    - All Categories.
    - Spacing.
    - Facilitating.
    - Rim Protection.
    - Defense.
    - Finishing.
  - Shows marginal gains and before/after category deltas.
  - Full roster mode includes a clean half-court lineup:
    - top 2 guards in spots 1 and 2.
    - top 2 forwards in spots 3 and 4.
    - top center in spot 5.
    - remaining players shown under the court.
  - Single-player mode hides the court and shows a scrollable single-player recommendation pane.
- Small HS Players-page fix:
  - `frontend_site/components/PlayerTable.tsx`
    - In HS Recruit view, uncommitted recruits display team as `N/A` instead of `Uncommitted`.
    - Added an `Uncommitted` checkbox filter in HS Recruit view.
    - No HS recruit data source was changed.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.
  - New route appears in build output:
    - `/optimizer`

### 2026-06-10 02:34:25 CDT Optimizer iteration: persistence, manual mode, court, and overlay polish

- User reviewed the first optimizer run and requested focused improvements while keeping the rest of the site unchanged.
- Updated:
  - `frontend_site/components/PortalSimulator.tsx`
  - `frontend_site/components/RosterOptimizer.tsx`
- Roster Management persistence:
  - Added local persistence for:
    - selected team.
    - removed/staying/leaving IDs.
    - added player IDs.
    - target pool.
    - roster/browse workbench tab.
  - Storage key:
    - `roster-lab-roster-management-state`
  - State now survives navigating away from and back to Roster Management.
  - Switching schools or clicking Reset clears the scenario as requested.
- Over-limit return flow:
  - Optimizer now shows a `Back to Roster Management` button when loaded roster size exceeds 15.
  - Because Roster Management state is persisted, this returns to the prior stay/leave/add state instead of resetting it.
- Optimized roster court:
  - Reworked the court into a cleaner half-court style.
  - Reduced player tag size.
  - Improved text contrast so names/BPR are readable.
  - Kept player headshots visible.
  - Uses 1/2 as the top two guards, 3/4 as top forwards, and 5 as top center.
- Roster rating overlay:
  - Kept original baseline pentagon as gray.
  - Changed edited/final overlay from a fully colored polygon to:
    - subtle edited polygon outline/fill.
    - five vertex dots.
    - dot is green when that category improved vs baseline.
    - dot is red when that category declined vs baseline.
- Added Manual Optimizer mode:
  - Top optimizer mode toggle now has:
    - Full Roster Optimization.
    - Single Player Optimization.
    - Manual Optimizer.
  - Manual mode shows a scrollable transfer/uncommitted-HS candidate pane.
  - Users can click `Add` or drag candidates onto the court/bench area.
  - Manual additions are added to the current loaded roster.
  - Manual mode has no roster limit or positional limit.
  - Manual mode recalculates:
    - final team ratings.
    - category deltas.
    - total gain.
    - weakest-category gain.
    - added BPR.
  - Manual mode updates the court and rating overlay live.
- Recommendation filters:
  - The `Recommendation View` control is now available only in:
    - Single Player Optimization.
    - Manual Optimizer.
  - It is hidden in Full Roster Optimization.
  - Primary dropdown now only includes:
    - Best Overall Fit.
    - Total Gain.
    - Weakest Category Gain.
    - Added BPR.
  - Category dropdown appears only when primary mode is:
    - Total Gain.
    - Weakest Category Gain.
  - Category dropdown contains:
    - All Categories.
    - Spacing.
    - Facilitating.
    - Rim Protection.
    - Defense.
    - Finishing.
  - Full roster set display defaults back to Best Overall Fit when filter controls are hidden.
- No generated data or recruit sourcing files were changed for this iteration.
- Validation:
  - Ran `npm run build` from `frontend_site`; production build completed successfully.
