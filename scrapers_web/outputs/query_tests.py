import os
import duckdb

path = "actual_db_files/hs_recruits_247_2010_2026_combined_complete.db"  # change this

print("Current folder:", os.getcwd())
print("File exists:", os.path.exists(path))
print("File size:", os.path.getsize(path) if os.path.exists(path) else "missing")

con = duckdb.connect(path)

tables = con.execute("SHOW TABLES").fetchdf()
print("\nTables:")
print(tables)

if tables.empty:
    print("\nNo tables found in this DuckDB file.")
else:
    table_name = 'hs_recruits_enriched'

    df = con.execute(f"""
    SELECT full_name, profile_lookup_url, profile_url_api
    FROM {table_name}
    WHERE full_name = 'Drew Lock'
    """).fetchdf()

    print(df)