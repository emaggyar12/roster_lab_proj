import time
from pathlib import Path
import requests
import pandas as pd
import duckdb

PROJECT_ROOT = '/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj'

def scrape_all_years_tovik():
    out_dir = Path("/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/data_pulls/torvik_player_csvs")
    out_dir.mkdir(parents=True, exist_ok=True)

    combined_csv_path = out_dir / "torvik_player_stats_2008_2026_combined.csv"

    years = range(2010, 2027)

    all_dfs = []

    for year in years:
        url = f"https://barttorvik.com/getadvstats.php?year={year}&csv=1"
        file_path = out_dir / f"torvik_player_stats_{year}.csv"

        print(f"Downloading {year}...")

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        with open(file_path, "wb") as f:
            f.write(response.content)

        print(f"Reading {year}...")

        df = pd.read_csv(file_path, header=None)
        df["year_pulled"] = year

        all_dfs.append(df)

        time.sleep(1)

    combined_df = pd.concat(all_dfs, ignore_index=True)

    combined_df.to_csv(combined_csv_path, index=False)

    print("Done.")
    print(f"Combined CSV saved to: {combined_csv_path}")
    print(f"Rows: {combined_df.shape[0]}")
    print(f"Columns: {combined_df.shape[1]}")

def push_data(duck_db_path, df_name, df):
    with duckdb.connect(duck_db_path) as con:
        con.register("tmp_df", df)
        con.execute(f"DROP TABLE IF EXISTS {df_name};")
        con.execute(f"CREATE TABLE {df_name} AS SELECT * FROM tmp_df;")

def get_data(duck_db_path, df_name):
    with duckdb.connect(duck_db_path) as con:
        df = con.execute(f"SELECT * FROM {df_name}").df()

    return df

if __name__ == '__main__':
    # Pushing the csv as a duck db file
    # all_players_df = pd.read_csv(f'{PROJECT_ROOT}/data_pulls/bvt_allyears.csv')

    # push_data(duck_db_path=f'{PROJECT_ROOT}/bvt_allyears.db', df_name='bvt_allyears', df=all_players_df)

    # TODO Pushing transfer csv into a db file
    historical_hs_df = pd.read_csv(f'{PROJECT_ROOT}/data_pulls/hs_recruit_historical.csv')

    push_data(duck_db_path=f'{PROJECT_ROOT}/hs_recruit_historical.db', df_name='hs_rec_historical', df=historical_hs_df)

    # TODO Push recruit numerical csv into a db file
    transfer_df = pd.read_csv(f'{PROJECT_ROOT}/data_pulls/transfer_data_historical.csv')

    push_data(duck_db_path=f'{PROJECT_ROOT}/transfer_data_historical.db', df_name='transfer_historical', df=transfer_df)


