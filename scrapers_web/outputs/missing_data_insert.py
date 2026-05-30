import duckdb
from pathlib import Path

old_db_path = Path("/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/scrapers_web/outputs/actual_db_files/hs_recruits_247_2010_2026_combined.db")          # change this
csv_path = Path("/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/scrapers_web/missing_data_combined.csv")    # change this
target_table = "hs_recruits_enriched"                # change this

new_db_path = old_db_path.with_name(old_db_path.stem + "_complete.db")

con = duckdb.connect(str(new_db_path))

# Attach old database as read-only source
con.execute(f"""
    ATTACH '{old_db_path}' AS old_db (READ_ONLY)
""")

# Load CSV as temp view
con.execute(f"""
    CREATE OR REPLACE TEMP VIEW hw_updates AS
    SELECT *
    FROM read_csv_auto('{csv_path}')
""")

# Get tables from old database
tables_df = con.execute("SHOW TABLES FROM old_db").fetchdf()
tables = tables_df.iloc[:, 0].tolist()

print("Tables found:", tables)

# Copy all tables into the new database
for table in tables:
    if table == target_table:
        print(f"Creating updated table: {table}")

        con.execute(f"""
            CREATE OR REPLACE TABLE "{table}" AS
            SELECT
                t.* REPLACE (
                    COALESCE(t.height, CAST(u.height AS VARCHAR)) AS height,
                    COALESCE(t.weight, CAST(u.weight AS VARCHAR)) AS weight
                )
            FROM old_db.main."{table}" AS t
            LEFT JOIN hw_updates AS u
            ON t.year = u.year
            AND t.player_key = u.player_key
            AND t.full_name = u.full_name
            AND t.position = u.position
        """)
    else:
        print(f"Copying unchanged table: {table}")

        con.execute(f"""
            CREATE OR REPLACE TABLE "{table}" AS
            SELECT *
            FROM old_db.main."{table}"
        """)

# Validation: print rows that got filled
filled_rows = con.execute(f"""
    SELECT
        t.year,
        t.player_key,
        t.full_name,
        t.position,
        old_t.height AS old_height,
        t.height AS new_height,
        old_t.weight AS old_weight,
        t.weight AS new_weight
    FROM "{target_table}" AS t
    JOIN old_db.main."{target_table}" AS old_t
      ON t.year = old_t.year
     AND t.player_key = old_t.player_key
     AND t.full_name = old_t.full_name
     AND t.position = old_t.position
    WHERE
        (old_t.height IS NULL AND t.height IS NOT NULL)
        OR
        (old_t.weight IS NULL AND t.weight IS NOT NULL)
""").fetchdf()

print("\nRows filled:")
print(filled_rows)

print(f"\nNew complete database written to: {new_db_path}")

con.close()