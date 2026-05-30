from pathlib import Path
import re
import time
import duckdb
import pandas as pd
from bs4 import BeautifulSoup


# -----------------------------
# CONFIG
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# If this script is inside:
# uiuc_proj/scrapers_web/outputs/query_tests.py
# then parents[2] should be:
# uiuc_proj

CACHE_ROOT = PROJECT_ROOT / "scrapers_web" / "cache" / "hs"

OUTPUT_DB = PROJECT_ROOT / "scrapers_web" / "outputs" / "actual_db_files" / "hs_recruit_skill_ratings.db"
OUTPUT_TABLE = "hs_recruit_skill_ratings"

OUTPUT_CSV = PROJECT_ROOT / "scrapers_web" / "outputs" / "hs_recruit_skill_ratings.csv"


# -----------------------------
# HELPERS
# -----------------------------
def clean_skill_name(skill_name: str) -> str:
    """
    Converts skill names into safe column names.

    Examples:
        "Scorer/Finisher" -> "skill_scorer_finisher"
        "Athleticism" -> "skill_athleticism"
    """
    skill_name = skill_name.strip().lower()
    skill_name = re.sub(r"[^a-z0-9]+", "_", skill_name)
    skill_name = skill_name.strip("_")
    return f"skill_{skill_name}"


def parse_skill_ratings_from_html(html: str) -> dict:
    """
    Extracts skill ratings from the scouting-report skills section.
    """
    result = {"skill_rating": False}

    soup = BeautifulSoup(html, "html.parser")

    scouting_section = soup.select_one("section.scouting-report#evaluation")
    if scouting_section is None:
        return result

    skills_section = scouting_section.select_one("section.skills")
    if skills_section is None:
        return result

    skill_items = skills_section.select("li")

    for item in skill_items:
        text_tag = item.select_one("span.text")
        rating_tag = item.select_one("b")

        if text_tag is None or rating_tag is None:
            continue

        skill_name = text_tag.get_text(strip=True)
        rating_text = rating_tag.get_text(strip=True)

        if not skill_name or not rating_text:
            continue

        try:
            rating_value = int(rating_text)
        except ValueError:
            continue

        col_name = clean_skill_name(skill_name)
        result[col_name] = rating_value
        result["skill_rating"] = True

    return result


def get_year_and_recruit_key(html_path: Path) -> tuple[int | None, str]:
    """
    Given:
        uiuc_proj/scrapers_web/cache/hs/2013/profiles/andrew_wiggins.html

    Returns:
        2013, "andrew_wiggins"
    """
    recruit_key = html_path.stem

    try:
        year = int(html_path.parents[1].name)
    except ValueError:
        year = None

    return year, recruit_key


# -----------------------------
# MAIN
# -----------------------------
def main():
    print(f"Project root: {PROJECT_ROOT}", flush=True)
    print(f"Cache root: {CACHE_ROOT}", flush=True)
    print(f"Cache root exists: {CACHE_ROOT.exists()}", flush=True)

    html_files = sorted(CACHE_ROOT.glob("*/profiles/*.html"))

    print(f"Found {len(html_files):,} cached HTML files", flush=True)

    if not html_files:
        print("No HTML files found. Check CACHE_ROOT.", flush=True)
        return

    rows = []
    skill_pages_found = 0
    start_time = time.time()

    for i, html_path in enumerate(html_files, start=1):
        if i == 1 or i % 250 == 0:
            elapsed = time.time() - start_time
            print(
                f"Processed {i:,}/{len(html_files):,} files | "
                f"skill pages: {skill_pages_found:,} | "
                f"elapsed: {elapsed:.1f}s | "
                f"current: {html_path.name}",
                flush=True
            )

        year, recruit_key = get_year_and_recruit_key(html_path)

        try:
            html = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"Could not read {html_path}: {e}", flush=True)
            continue

        skill_data = parse_skill_ratings_from_html(html)

        if skill_data.get("skill_rating"):
            skill_pages_found += 1

        row = {
            "year": year,
            "recruit_key": recruit_key,
            "html_path": str(html_path),
            **skill_data
        }

        rows.append(row)

    print("Finished parsing HTML files.", flush=True)
    print("Building DataFrame...", flush=True)

    df = pd.DataFrame(rows)

    if df.empty:
        print("No rows created.", flush=True)
        return

    df["skill_rating"] = df["skill_rating"].fillna(False).astype(bool)

    skill_cols = sorted([
        col for col in df.columns
        if col.startswith("skill_") and col != "skill_rating"
    ])

    ordered_cols = [
        "year",
        "recruit_key",
        "html_path",
        "skill_rating",
        *skill_cols
    ]

    df = df[ordered_cols]

    print("\nSkill-rating pages found:", flush=True)
    print(df["skill_rating"].value_counts(dropna=False), flush=True)

    print("\nSkill columns:", flush=True)
    print(skill_cols, flush=True)

    print("\nSaving CSV...", flush=True)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)

    print("Saving DuckDB...", flush=True)
    OUTPUT_DB.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(OUTPUT_DB))
    con.execute(f'DROP TABLE IF EXISTS "{OUTPUT_TABLE}"')
    con.register("skill_df", df)
    con.execute(f'CREATE TABLE "{OUTPUT_TABLE}" AS SELECT * FROM skill_df')
    con.close()

    total_elapsed = time.time() - start_time

    print("\nDone.", flush=True)
    print(f"Total elapsed: {total_elapsed:.1f}s", flush=True)
    print(f"Saved CSV to: {OUTPUT_CSV}", flush=True)
    print(f"Saved DuckDB database to: {OUTPUT_DB}", flush=True)
    print(f"Table name: {OUTPUT_TABLE}", flush=True)


if __name__ == "__main__":
    main()