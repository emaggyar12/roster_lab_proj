library(hoopR)
library(dplyr)
library(readr)
library(purrr)

draft_year <- 2026

anthro <- nba_draftcombineplayeranthro(season_year = draft_year)$Results
stats  <- nba_draftcombinestats(season_year = draft_year)$DraftCombineStats
drills <- nba_draftcombinedrillresults(season_year = draft_year)$Results

prospects <- anthro %>%
  select(
    PLAYER_ID,
    FIRST_NAME,
    LAST_NAME,
    PLAYER_NAME,
    POSITION,
    HEIGHT_WO_SHOES,
    HEIGHT_WO_SHOES_FT_IN,
    HEIGHT_W_SHOES,
    HEIGHT_W_SHOES_FT_IN,
    WEIGHT,
    WINGSPAN,
    WINGSPAN_FT_IN,
    STANDING_REACH,
    STANDING_REACH_FT_IN,
    BODY_FAT_PCT,
    HAND_LENGTH,
    HAND_WIDTH
  ) %>%
  left_join(
    stats %>%
      select(
        PLAYER_ID,
        SEASON,
        PLAYER_NAME,
        POSITION,
        everything()
      ),
    by = "PLAYER_ID",
    suffix = c("", "_stats")
  ) %>%
  left_join(
    drills %>%
      select(
        PLAYER_ID,
        STANDING_VERTICAL_LEAP,
        MAX_VERTICAL_LEAP,
        LANE_AGILITY_TIME,
        MODIFIED_LANE_AGILITY_TIME,
        THREE_QUARTER_SPRINT,
        BENCH_PRESS
      ),
    by = "PLAYER_ID"
  ) %>%
  distinct(PLAYER_ID, .keep_all = TRUE) %>%
  arrange(PLAYER_NAME)

print(prospects)

write_csv(prospects, "nba_2026_draft_combine_prospects.csv")