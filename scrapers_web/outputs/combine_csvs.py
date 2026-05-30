import pandas as pd
from pathlib import Path

folder = Path("/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/scrapers_web/missing_data")  # change this
output_path = "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/scrapers_web/missing_data_combined.csv"

csv_files = list(folder.glob("*.csv"))

dfs = []

for file in csv_files:
    df = pd.read_csv(file)
    df["source_file"] = file.name  # optional: keeps track of where each row came from
    dfs.append(df)

combined_df = pd.concat(dfs, ignore_index=True)

combined_df.to_csv(output_path, index=False)

print(f"Combined {len(csv_files)} CSV files into {output_path}")