devtools::install_github("andreweatherman/cbbdata")
install.packages("duckdb")
install.packages("DBI")

library(cbbdata)
library(duckdb)
library(DBI)
library(dplyr)


# to register
cbbdata::cbd_create_account(username = 'emaggyar12', email = 'emaggyar12@gmail.com', password = 'basketballauburn123', confirm_password = 'basketballauburn123')
cbbdata::cbd_login(username = 'emaggyar12', password = 'basketballauburn123')

# Functions to push and retrieve data from db files
push_data <- function(duck_db_path, table_name, df) {
  con <- dbConnect(duckdb(), dbdir = duck_db_path)

  tryCatch({
    dbWriteTable(
      conn = con,
      name = table_name,
      value = df,
      overwrite = TRUE
    )
  }, finally = {
    dbDisconnect(con, shutdown = TRUE)
  })
}


get_data <- function(duck_db_path, table_name) {
  con <- dbConnect(duckdb(), dbdir = duck_db_path)

  tryCatch({
    df <- dbReadTable(con, table_name)
    return(df)
  }, finally = {
    dbDisconnect(con, shutdown = TRUE)
  })
}

# TODO: get every team name since 2008
# TODO: Loop through team name and years in order to gather all player data since 2008

# Gathering all Barttovik player stats from 2008-2025 and storing in .db file
all_player_seasons <- cbd_torvik_player_season()

all_player_seasons_desc <- all_player_seasons %>%
  arrange(desc(year))

head(all_player_seasons_desc)
tail(all_player_seasons_desc)
nrow(all_player_seasons_desc)

push_data(
  duck_db_path = "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/api_pulls/bartovik_t_rank_players.db",
  table_name = "btvk_players",
  df = all_player_seasons_desc
)

