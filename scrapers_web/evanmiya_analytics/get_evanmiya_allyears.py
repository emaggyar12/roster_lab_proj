import json
import re
import time
from pathlib import Path

import duckdb
import pandas as pd
from playwright.sync_api import sync_playwright


URL = "https://evanmiya.com/?player_ratings"

OUT_DIR = Path("evanmiya_output")
OUT_DIR.mkdir(exist_ok=True)

CSV_OUT = OUT_DIR / "evanmiya_player_ratings_all_years_less_poss.csv"
DB_OUT = OUT_DIR / "evanmiya_player_ratings_all_year_less_poss.db"
TABLE_NAME = "evanmiya_player_ratings"

MAX_ATTEMPTS_PER_TABLE = 4
MIN_POSSESSIONS = 200
PLAYWRIGHT_USER_DATA_DIR = Path("/private/tmp/evanmiya_playwright_profile")


# ---------------------------------------------------------------------
# Year helpers
# ---------------------------------------------------------------------

def season_label_from_later_year(later_year: int) -> str:
    """
    2010 -> 2009-10
    2026 -> 2025-26
    """
    start = later_year - 1
    end_2 = str(later_year)[-2:]
    return f"{start}-{end_2}"


def later_year_from_season_label(season: str) -> int:
    """
    2009-10 -> 2010
    2025-26 -> 2026
    """
    start_str, end_str = season.split("-")
    start_year = int(start_str)

    century = start_year // 100 * 100
    later_year = century + int(end_str)

    if later_year < start_year:
        later_year += 100

    return later_year


# ---------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------

def normalize_colname(col: str) -> str:
    col = str(col).strip()
    col = col.replace("%", "pct")
    col = col.replace("+", "plus")
    col = col.replace("-", "_")
    col = col.replace("/", "_")
    col = re.sub(r"\s+", "_", col)
    col = re.sub(r"[^a-zA-Z0-9_]", "", col)
    col = re.sub(r"_+", "_", col)
    return col.strip("_").lower()


def normalize_player_name(name: str) -> str:
    if pd.isna(name):
        return ""

    name = str(name).lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def find_player_name_col(df: pd.DataFrame) -> str:
    candidates = [
        "player",
        "player_name",
        "name",
        "full_name",
    ]

    cols_lower = {str(c).lower(): c for c in df.columns}

    for candidate in candidates:
        if candidate in cols_lower:
            return cols_lower[candidate]

    for c in df.columns:
        cl = str(c).lower()
        if "player" in cl or "name" in cl:
            return c

    raise RuntimeError(f"Could not find player name column. Columns: {list(df.columns)}")


def raw_table_matches_view(df: pd.DataFrame, view: str) -> bool:
    """
    Basic tables do NOT contain position/role/class.
    Advanced tables DO contain position/role/class.
    """
    cols = {normalize_colname(c) for c in df.columns}
    advanced_markers = {"position", "role", "class"}

    view_lower = view.lower()

    if view_lower == "basic":
        return not bool(cols & advanced_markers)

    if view_lower == "advanced":
        return advanced_markers.issubset(cols)

    raise ValueError(f"Unknown view: {view}")


# ---------------------------------------------------------------------
# WebSocket capture
# ---------------------------------------------------------------------

class ShinyTableCapture:
    def __init__(self):
        self.latest_df = None
        self.latest_msg_id = 0
        self.latest_raw = None
        self.frames = []

    def handle_websocket(self, ws):
        print(f"[WEBSOCKET OPENED] {ws.url}")

        def frame_received(payload):
            text = str(payload)

            if "player_ratings_page-player_data" not in text:
                return

            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                return

            values = msg.get("values", {})
            table_obj = values.get("player_ratings_page-player_data")

            if not table_obj:
                return

            try:
                data = table_obj["x"]["tag"]["attribs"]["data"]
            except KeyError:
                return

            df = pd.DataFrame(data)

            if len(df) > 0:
                self.latest_msg_id += 1
                msg_id = self.latest_msg_id

                self.latest_df = df
                self.latest_raw = msg
                self.frames.append(
                    {
                        "msg_id": msg_id,
                        "df": df.copy(),
                        "columns": list(df.columns),
                    }
                )

                print(f"Captured table #{msg_id}: {df.shape}")

        ws.on("framereceived", frame_received)


def wait_for_any_new_table(
    capture: ShinyTableCapture,
    previous_msg_id: int,
    timeout_sec: int = 30,
) -> pd.DataFrame:
    """
    Wait for any player ratings table strictly after previous_msg_id.
    This is used only to let Shiny finish processing an intermediate control change.
    """
    start = time.time()

    while time.time() - start < timeout_sec:
        newest = None

        for frame in capture.frames:
            if frame["msg_id"] > previous_msg_id:
                newest = frame

        if newest is not None:
            return newest["df"].copy()

        time.sleep(0.25)

    raise TimeoutError("Timed out waiting for any new player ratings table over WebSocket.")


def wait_for_new_table_matching_view(
    capture: ShinyTableCapture,
    previous_msg_id: int,
    view: str,
    timeout_sec: int = 90,
) -> pd.DataFrame:
    """
    Wait for a player ratings table strictly after previous_msg_id that has
    the expected Basic/Advanced column shape. Wrong-view frames are ignored.

    Important: this function never looks at frames with msg_id <= previous_msg_id.
    That prevents stale tables from earlier seasons from being reused.
    """
    start = time.time()
    seen_wrong = set()

    while time.time() - start < timeout_sec:
        for frame in capture.frames:
            msg_id = frame["msg_id"]

            if msg_id <= previous_msg_id:
                continue

            df = frame["df"]

            if raw_table_matches_view(df, view):
                return df.copy()

            if msg_id not in seen_wrong:
                seen_wrong.add(msg_id)
                print(f"Skipping table #{msg_id}; it does not match requested view={view}")

        time.sleep(0.25)

    raise TimeoutError(f"Timed out waiting for {view} player ratings table over WebSocket.")


# ---------------------------------------------------------------------
# Direct Shiny controls
# ---------------------------------------------------------------------

def get_current_year(page) -> str:
    return page.evaluate(
        """
        () => {
            const el = document.getElementById('player_ratings_page-year');
            if (!el) return null;
            if (el.selectize) return el.selectize.getValue();
            return el.value;
        }
        """
    )


def get_current_view_value(page) -> str:
    return page.evaluate(
        """
        () => {
            const checked = document.querySelector('input[name="player_ratings_page-advanced"]:checked');
            return checked ? checked.value : null;
        }
        """
    )


def view_to_value(view: str) -> str:
    view_lower = view.lower()

    if view_lower == "basic":
        return "1"
    if view_lower == "advanced":
        return "2"

    raise ValueError(f"Unknown view: {view}")


def set_shiny_selectize(page, select_id: str, value: str):
    """
    Uses Selectize's JS API and tells Shiny the input changed.
    """
    page.evaluate(
        """
        ({selectId, value}) => {
            const el = document.getElementById(selectId);

            if (!el) {
                throw new Error(`Could not find select: ${selectId}`);
            }

            if (!el.selectize) {
                throw new Error(`Select exists but has no selectize object: ${selectId}`);
            }

            el.selectize.setValue(value, true);
            el.dispatchEvent(new Event("change", { bubbles: true }));

            if (window.Shiny) {
                Shiny.setInputValue(selectId, value, {priority: "event"});
            }
        }
        """,
        {"selectId": select_id, "value": value},
    )


def set_year(page, season: str):
    print(f"Setting year: {season}")
    set_shiny_selectize(page, "player_ratings_page-year", season)
    page.wait_for_timeout(1500)


def set_view(page, view: str):
    """
    Basic -> value 1
    Advanced -> value 2
    """
    value = view_to_value(view)

    print(f"Setting view: {view}")

    selector = f'input[name="player_ratings_page-advanced"][value="{value}"]'
    page.locator(selector).check(force=True)

    page.evaluate(
        """
        ({name, value}) => {
            if (window.Shiny) {
                Shiny.setInputValue(name, value, {priority: "event"});
            }
        }
        """,
        {"name": "player_ratings_page-advanced", "value": value},
    )

    page.wait_for_timeout(1500)


def set_min_possessions(page, value: int = MIN_POSSESSIONS):
    """
    Force the Evan Miya possessions slider to a lower threshold.
    """
    print(f"Setting minimum possessions: {value}")

    page.evaluate(
        """
        ({value}) => {
            const el = document.getElementById('player_ratings_page-poss_filter');
            if (!el) {
                throw new Error('Could not find possession filter slider: player_ratings_page-poss_filter');
            }

            if (el.noUiSlider) {
                el.noUiSlider.set(value);
            } else {
                el.value = value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }

            if (window.Shiny) {
                Shiny.setInputValue('player_ratings_page-poss_filter', value, { priority: 'event' });
            }
        }
        """,
        {"value": value},
    )
    page.wait_for_timeout(1500)


# ---------------------------------------------------------------------
# Scrape one season/view
# ---------------------------------------------------------------------

def clean_view_df(df: pd.DataFrame, season: str, view: str) -> pd.DataFrame:
    df = df.copy()

    df.columns = [normalize_colname(c) for c in df.columns]

    df.insert(0, "season", season)
    df.insert(1, "year", later_year_from_season_label(season))

    name_col = find_player_name_col(df)
    df["player_name_join"] = df[name_col].apply(normalize_player_name)

    view_lower = view.lower()
    prefix = "basic_" if view_lower == "basic" else "advanced_"

    protected = {
        "season",
        "year",
        "player_name_join",
        name_col,
        "player",
        "player_name",
        "name",
        "team",
        "adj_team",
        "rank",
    }

    rename_map = {}

    for c in df.columns:
        if c not in protected and not c.startswith(prefix):
            rename_map[c] = f"{prefix}{c}"

    df = df.rename(columns=rename_map)

    return df


def pull_one_view(page, capture: ShinyTableCapture, season: str, view: str) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print(f"Pulling season={season}, view={view}")

    # Do not trust the visual/DOM state alone. Shiny can leave the DOM checked
    # before the corresponding table frame has arrived. To avoid stale frames:
    #   1. Put the app on the requested season.
    #   2. Force a view transition away from the requested view.
    #   3. Set the requested view and only accept a frame that arrives after that.
    # This makes the final accepted table caused by the final requested-view event.

    opposite_view = "Advanced" if view.lower() == "basic" else "Basic"

    # Step 1: set the desired year. If this emits a frame, let it complete.
    year_baseline = capture.latest_msg_id
    set_year(page, season)
    try:
        _ = wait_for_any_new_table(
            capture=capture,
            previous_msg_id=year_baseline,
            timeout_sec=20,
        )
    except TimeoutError:
        # If the year was already selected, Shiny may not emit a frame. That is fine;
        # the forced view transition below will create the table we actually use.
        print(f"No new table after setting year={season}; continuing to forced view refresh.")

    # The year change can reset the slider back to the site default, so apply it
    # after the year transition has settled.
    set_min_possessions(page, MIN_POSSESSIONS)

    # Step 2: force the app away from the requested view.
    away_baseline = capture.latest_msg_id
    set_view(page, opposite_view)
    try:
        _ = wait_for_new_table_matching_view(
            capture=capture,
            previous_msg_id=away_baseline,
            view=opposite_view,
            timeout_sec=45,
        )
    except TimeoutError:
        # If this does not emit cleanly, still try the final requested view.
        print(f"Could not confirm intermediate {opposite_view} table; continuing to requested view={view}.")

    # Step 3: final controlled event. Only accept frames after this baseline.
    final_baseline = capture.latest_msg_id
    set_view(page, view)
    raw_df = wait_for_new_table_matching_view(
        capture=capture,
        previous_msg_id=final_baseline,
        view=view,
        timeout_sec=90,
    )

    if not raw_table_matches_view(raw_df, view):
        raise RuntimeError(f"Internal error: captured table does not match requested view={view}")

    cleaned_df = clean_view_df(raw_df, season, view)

    print(f"{season} {view} cleaned shape: {cleaned_df.shape}")
    print(f"Columns: {list(cleaned_df.columns)}")

    return cleaned_df

def pull_one_view_with_retries(page, capture: ShinyTableCapture, season: str, view: str) -> pd.DataFrame:
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS_PER_TABLE + 1):
        try:
            print(f"\nAttempt {attempt}/{MAX_ATTEMPTS_PER_TABLE}: season={season}, view={view}")
            return pull_one_view(page, capture, season, view)

        except Exception as e:
            last_error = e
            print(f"Attempt failed for season={season}, view={view}: {repr(e)}")

            fail_html = OUT_DIR / f"failed_{season}_{view.lower()}_attempt_{attempt}.html"
            try:
                fail_html.write_text(page.content(), encoding="utf-8")
                print(f"Saved failure HTML: {fail_html}")
            except Exception as html_error:
                print(f"Could not save failure HTML: {repr(html_error)}")

            page.wait_for_timeout(5000)

            # On later failures, reload the app to get Shiny back to a clean state.
            if attempt < MAX_ATTEMPTS_PER_TABLE and attempt >= 2:
                print("Reloading page before retry...")
                page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(12_000)
                page.locator("#player_ratings_page-year").wait_for(state="attached", timeout=30_000)
                page.locator("#player_ratings_page-year-selectized").wait_for(state="visible", timeout=30_000)
                set_min_possessions(page, MIN_POSSESSIONS)

    raise RuntimeError(
        f"FAILED permanently: season={season}, view={view}. "
        f"Last error: {repr(last_error)}"
    )


# ---------------------------------------------------------------------
# Merge basic + advanced
# ---------------------------------------------------------------------

def check_duplicate_keys(df: pd.DataFrame, keys: list[str], label: str):
    dupes = df[df.duplicated(keys, keep=False)].sort_values(keys)

    if len(dupes) > 0:
        print(f"\nWARNING: {label} has duplicate join keys.")
        print(f"Duplicate rows: {len(dupes)}")
        preview_cols = [c for c in keys + ["name", "rank"] if c in dupes.columns]
        print(dupes[preview_cols].head(40))


def merge_basic_advanced(basic_df: pd.DataFrame, advanced_df: pd.DataFrame) -> pd.DataFrame:
    advanced_name_col = find_player_name_col(advanced_df)

    # Rank + name + team + year should make this a true one-to-one row pairing.
    # Name + year alone is not safe because multiple players can share names.
    join_cols = ["year", "rank", "player_name_join", "team"]

    for col in join_cols:
        if col not in basic_df.columns:
            raise RuntimeError(f"Missing join column in basic_df: {col}")
        if col not in advanced_df.columns:
            raise RuntimeError(f"Missing join column in advanced_df: {col}")

    check_duplicate_keys(basic_df, join_cols, "basic_df")
    check_duplicate_keys(advanced_df, join_cols, "advanced_df")

    advanced_clean = advanced_df.copy()

    drop_from_advanced = [
        "season",
        advanced_name_col,
    ]

    advanced_clean = advanced_clean.drop(
        columns=[c for c in drop_from_advanced if c in advanced_clean.columns],
        errors="ignore",
    )

    try:
        merged = basic_df.merge(
            advanced_clean,
            on=join_cols,
            how="left",
            validate="one_to_one",
            suffixes=("", "_advanced_dup"),
        )
    except Exception as e:
        basic_dupes = basic_df[basic_df.duplicated(join_cols, keep=False)].sort_values(join_cols)
        advanced_dupes = advanced_df[advanced_df.duplicated(join_cols, keep=False)].sort_values(join_cols)

        diag_dir = OUT_DIR / "merge_diagnostics"
        diag_dir.mkdir(exist_ok=True)
        basic_dupes.to_csv(diag_dir / "basic_duplicate_keys.csv", index=False)
        advanced_dupes.to_csv(diag_dir / "advanced_duplicate_keys.csv", index=False)

        raise RuntimeError(
            f"Merge failed with validate='one_to_one'. Diagnostics saved in {diag_dir}. "
            f"Original error: {repr(e)}"
        ) from e

    dup_cols = [c for c in merged.columns if c.endswith("_advanced_dup")]
    merged = merged.drop(columns=dup_cols)

    if len(merged) != len(basic_df):
        raise RuntimeError(
            f"Merge row count changed: basic_df={len(basic_df)}, merged={len(merged)}. "
            "This indicates duplicated or mismatched join keys."
        )

    advanced_cols = [c for c in merged.columns if c.startswith("advanced_")]
    missing_advanced_rows = merged[advanced_cols].isna().all(axis=1).sum() if advanced_cols else None

    print(f"Merged shape: {merged.shape}")
    if missing_advanced_rows is not None:
        print(f"Rows with no advanced match: {missing_advanced_rows}")

        if missing_advanced_rows > 0:
            diag_dir = OUT_DIR / "merge_diagnostics"
            diag_dir.mkdir(exist_ok=True)
            missing = merged[merged[advanced_cols].isna().all(axis=1)]
            missing.to_csv(diag_dir / "missing_advanced_rows.csv", index=False)
            raise RuntimeError(
                f"There are {missing_advanced_rows} basic rows with no advanced match. "
                f"Diagnostics saved in {diag_dir}."
            )

    return merged


# ---------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------

def save_outputs(final_df: pd.DataFrame):
    final_df = final_df.copy()

    # DuckDB can fail when numeric-looking columns contain literal string 'NA'.
    # Convert these placeholders to real nulls before writing CSV/DB.
    final_df = final_df.replace({"NA": None, "": None})
    final_df = final_df.where(pd.notna(final_df), None)

    final_df.to_csv(CSV_OUT, index=False)
    print(f"\nSaved CSV: {CSV_OUT}")

    con = duckdb.connect(str(DB_OUT))
    con.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
    con.register("final_df_view", final_df)
    con.execute(f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM final_df_view")
    con.close()

    print(f"Saved DuckDB: {DB_OUT}")
    print(f"DuckDB table name: {TABLE_NAME}")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    seasons = [season_label_from_later_year(y) for y in range(2010, 2027)]

    print("Seasons to pull:")
    print(seasons)

    all_years = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PLAYWRIGHT_USER_DATA_DIR),
            headless=True,
            viewport={"width": 1400, "height": 1200},
        )

        page = context.new_page()
        page.set_viewport_size({"width": 1400, "height": 1200})
        page.set_extra_http_headers(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                )
            }
        )

        capture = ShinyTableCapture()
        page.on("websocket", capture.handle_websocket)

        print("Opening site...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        print("Waiting for Shiny app to initialize...")
        page.wait_for_timeout(12_000)

        # Hidden select must be attached; visible selectize input must be visible.
        page.locator("#player_ratings_page-year").wait_for(state="attached", timeout=30_000)
        page.locator("#player_ratings_page-year-selectized").wait_for(state="visible", timeout=30_000)
        set_min_possessions(page, MIN_POSSESSIONS)

        try:
            for season in seasons:
                basic_df = pull_one_view_with_retries(page, capture, season, "Basic")
                advanced_df = pull_one_view_with_retries(page, capture, season, "Advanced")

                merged_df = merge_basic_advanced(basic_df, advanced_df)
                all_years.append(merged_df)

                checkpoint_path = OUT_DIR / f"checkpoint_{season}.csv"
                merged_df.to_csv(checkpoint_path, index=False)
                print(f"Saved checkpoint: {checkpoint_path}")

        finally:
            context.close()

    if len(all_years) != len(seasons):
        raise RuntimeError(
            f"Incomplete scrape: expected {len(seasons)} seasons, got {len(all_years)}. "
            "Final CSV/DB will not be written."
        )

    final_df = pd.concat(all_years, ignore_index=True)

    save_outputs(final_df)

    print("\nFinal shape:", final_df.shape)
    print(final_df.head())


if __name__ == "__main__":
    main()
