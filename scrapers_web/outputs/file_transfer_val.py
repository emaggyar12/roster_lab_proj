import duckdb
from pathlib import Path

old_db_path = Path("actual_db_files/hs_recruits_247_2010_2026_combined.db")
new_db_path = Path("actual_db_files/hs_recruits_247_2010_2026_combined_complete.db")
table_name = "hs_recruits_enriched"

ignored_columns = {"height", "weight"}

con = duckdb.connect()

con.execute(f"ATTACH '{old_db_path}' AS old_db")
con.execute(f"ATTACH '{new_db_path}' AS new_db")

# -----------------------------
# Row count check
# -----------------------------
old_count = con.execute(f"""
    SELECT COUNT(*)
    FROM old_db.main."{table_name}"
""").fetchone()[0]

new_count = con.execute(f"""
    SELECT COUNT(*)
    FROM new_db.main."{table_name}"
""").fetchone()[0]

print("Old row count:", old_count)
print("New row count:", new_count)

if old_count == new_count:
    print("PASS: Row counts match.")
else:
    print("FAIL: Row counts do not match.")

# -----------------------------
# Get columns from old table
# -----------------------------
columns_df = con.execute(f"""
    DESCRIBE old_db.main."{table_name}"
""").fetchdf()

all_columns = columns_df["column_name"].tolist()

compare_columns = [
    col for col in all_columns
    if col not in ignored_columns
]

print("\nComparing columns:")
print(compare_columns)

# Build SELECT list
select_cols = ", ".join([f'"{col}"' for col in compare_columns])

# Rows in old but not in new
old_minus_new = con.execute(f"""
    SELECT {select_cols}
    FROM old_db.main."{table_name}"

    EXCEPT

    SELECT {select_cols}
    FROM new_db.main."{table_name}"
""").fetchdf()

# Rows in new but not in old
new_minus_old = con.execute(f"""
    SELECT {select_cols}
    FROM new_db.main."{table_name}"

    EXCEPT

    SELECT {select_cols}
    FROM old_db.main."{table_name}"
""").fetchdf()

print("\nRows present in OLD but different/missing in NEW:")
print(old_minus_new)

print("\nRows present in NEW but different/missing in OLD:")
print(new_minus_old)

if (
    old_count == new_count
    and old_minus_new.empty
    and new_minus_old.empty
):
    print("\nPASS: Row counts match and all non-height/weight data is identical.")
else:
    print("\nFAIL: Validation failed.")
    print(f"Old row count: {old_count}")
    print(f"New row count: {new_count}")
    print(f"OLD minus NEW rows: {len(old_minus_new)}")
    print(f"NEW minus OLD rows: {len(new_minus_old)}")

con.close()