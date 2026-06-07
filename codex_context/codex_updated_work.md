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
