from pathlib import Path
import re
import duckdb
import numpy as np
import pandas as pd


# ============================================================
# USER SETTINGS
# ============================================================

DB_PATH = Path(
    "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/"
    "Basketball/College Basketball Project/uiuc_proj/data_dir/"
    "evan_miya_barttorvik_matched.db"
)

TABLE_NAME = "evan_miya_barttorvik_matched"

OUTPUT_DIR = Path("cluster_percentile_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_CSV = OUTPUT_DIR / "players_group_percentiles_from_db.csv"

OPTIONAL_ID_COLS = [
    "name",
    "bvt_pid",
    "player_id",
    "pid",
    "team",
    "year",
]

HEIGHT_SOURCE_COL = "bvt_player_height"
DERIVED_HEIGHT_COL = "player_height_in"


# ============================================================
# FEATURE GROUPS
# ============================================================
# The output will always be exactly these five added percentile columns.
# You can add/remove features inside each group.
# Use player_height_in here. It will be created from bvt_player_height.

FEATURE_GROUPS = {
    "spacing_percentile": [
        "bvt_FT_per",
        "bvt_TP_per",
        "bvt_midmade/(midmade+midmiss)",
        "bvt_3p/100?",
    ],

    "facilitating_percentile": [
        "bvt_usg",
        "bvt_ast",
        "bvt_TO_per",
        "bvt_ast/tov",
    ],

    "rim_protection_percentile": [
        "bvt_ORB_per",
        "bvt_DRB_per",
        "bvt_blk",
        "player_height_in",
    ],

    "defense_percentile": [
        "bvt_blk",
        "bvt_stl",
        "bvt_drtg",
        "bvt_stops",
    ],

    "finishing_percentile": [
        "bvt_rimmade/(rimmade+rimmiss)",
        "bvt_dunksmade/(dunksmade+dunksmiss)",
    ],
}


# ============================================================
# HELPERS
# ============================================================

def quote_ident(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def normalize_col_name(col: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", col.lower())


def get_table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    cols_df = con.execute(f"DESCRIBE {quote_ident(table_name)}").fetchdf()
    return cols_df["column_name"].tolist()


def resolve_columns(requested_cols: list[str], existing_cols: list[str]) -> dict[str, str]:
    existing_exact = set(existing_cols)

    lower_to_actual = {}
    norm_to_actual = {}

    for col in existing_cols:
        lower_to_actual.setdefault(col.lower(), col)
        norm_to_actual.setdefault(normalize_col_name(col), col)

    resolved = {}

    for requested in requested_cols:
        actual = None

        if requested in existing_exact:
            actual = requested
        elif requested.lower() in lower_to_actual:
            actual = lower_to_actual[requested.lower()]
        elif normalize_col_name(requested) in norm_to_actual:
            actual = norm_to_actual[normalize_col_name(requested)]

        if actual is not None:
            resolved[requested] = actual

    return resolved


def clean_numeric_series(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
         .str.strip()
         .str.replace(",", "", regex=False)
         .str.replace("%", "", regex=False)
         .replace({
             "": np.nan,
             "nan": np.nan,
             "NaN": np.nan,
             "None": np.nan,
             "none": np.nan,
             "NULL": np.nan,
             "null": np.nan,
             "-": np.nan,
         })
         .pipe(pd.to_numeric, errors="coerce")
    )


def parse_height_to_inches(value):
    """
    Converts height values to inches.

    Handles:
      6-8
      6'8
      6' 8"
      6 8
      80
      80.0
      6.75
    """
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.integer, np.floating)):
        value = float(value)

        # Already inches.
        if 50 <= value <= 100:
            return value

        # Feet as decimal, example 6.75.
        if 5 <= value <= 8:
            feet = int(value)
            inches = round((value - feet) * 12)
            return feet * 12 + inches

        return np.nan

    s = str(value).strip()

    if not s or s.lower() in {"nan", "none", "null", "-"}:
        return np.nan

    s = (
        s.replace("’", "'")
         .replace("′", "'")
         .replace("“", '"')
         .replace("”", '"')
         .replace("″", '"')
    )

    # 6-8
    m = re.match(r"^\s*(\d)\s*-\s*(\d{1,2})\s*$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    # 6'8", 6' 8
    m = re.match(r"^\s*(\d)\s*'\s*(\d{0,2})\s*\"?\s*$", s)
    if m:
        feet = int(m.group(1))
        inches = int(m.group(2)) if m.group(2) else 0
        return feet * 12 + inches

    # 6 8
    m = re.match(r"^\s*(\d)\s+(\d{1,2})\s*$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    try:
        num = float(s)

        if 50 <= num <= 100:
            return num

        if 5 <= num <= 8:
            feet = int(num)
            inches = round((num - feet) * 12)
            return feet * 12 + inches

    except ValueError:
        pass

    return np.nan


def higher_is_better(feature: str) -> bool:
    # User rule:
    # only bvt_TO_per is lower-is-better.
    # everything else is higher-is-better.
    return feature != "bvt_TO_per"


def get_all_group_features() -> list[str]:
    features = []

    for output_col, group_features in FEATURE_GROUPS.items():
        if not group_features:
            raise ValueError(f"{output_col} has no selected features.")

        for feature in group_features:
            if feature not in features:
                features.append(feature)

    return features


def get_db_features_needed() -> list[str]:
    """
    Features needed from DB.

    player_height_in is derived, so it should not be queried directly.
    bvt_player_height is queried instead.
    """
    group_features = get_all_group_features()

    db_features = []

    for feature in group_features:
        if feature == DERIVED_HEIGHT_COL:
            continue

        if feature not in db_features:
            db_features.append(feature)

    if DERIVED_HEIGHT_COL in group_features and HEIGHT_SOURCE_COL not in db_features:
        db_features.append(HEIGHT_SOURCE_COL)

    return db_features


def validate_config() -> None:
    expected_output_cols = {
        "spacing_percentile",
        "facilitating_percentile",
        "rim_protection_percentile",
        "defense_percentile",
        "finishing_percentile",
    }

    actual_output_cols = set(FEATURE_GROUPS.keys())

    missing = expected_output_cols - actual_output_cols
    extra = actual_output_cols - expected_output_cols

    if missing:
        raise ValueError(
            "Missing required FEATURE_GROUPS output keys:\n"
            + "\n".join(f"  - {x}" for x in sorted(missing))
        )

    if extra:
        raise ValueError(
            "Unexpected FEATURE_GROUPS output keys:\n"
            + "\n".join(f"  - {x}" for x in sorted(extra))
        )

    for output_col, features in FEATURE_GROUPS.items():
        if not features:
            raise ValueError(f"{output_col} has no features.")

        placeholders = [
            f for f in features
            if str(f).startswith("FILL_IN_FEATURE")
        ]

        if placeholders:
            raise ValueError(
                f"{output_col} still has placeholder features:\n"
                + "\n".join(f"  - {x}" for x in placeholders)
            )


# ============================================================
# LOAD DATA
# ============================================================

def load_data() -> pd.DataFrame:
    validate_config()

    db_features = get_db_features_needed()
    requested_cols = OPTIONAL_ID_COLS + db_features

    con = duckdb.connect(str(DB_PATH), read_only=True)

    existing_cols = get_table_columns(con, TABLE_NAME)
    col_map = resolve_columns(requested_cols, existing_cols)

    missing_features = [
        feature for feature in db_features
        if feature not in col_map
    ]

    if missing_features:
        print("\nAvailable columns:")
        for col in existing_cols:
            print(f"  - {col}")

        raise ValueError(
            "Missing selected DB columns:\n"
            + "\n".join(f"  - {feature}" for feature in missing_features)
        )

    select_parts = []
    used_aliases = set()

    for requested, actual in col_map.items():
        alias = requested

        if alias in used_aliases:
            alias = f"col_{requested}"

        used_aliases.add(alias)
        select_parts.append(f"{quote_ident(actual)} AS {quote_ident(alias)}")

    select_sql = ",\n        ".join(select_parts)

    query = f"""
    SELECT
        {select_sql}
    FROM {quote_ident(TABLE_NAME)}
    WHERE year = 2026
    """

    print("\nRunning query:")
    print(query)

    df = con.execute(query).fetchdf()
    con.close()

    return df


# ============================================================
# PERCENTILE LOGIC
# ============================================================

def add_player_height_in(df: pd.DataFrame) -> pd.DataFrame:
    if HEIGHT_SOURCE_COL not in df.columns:
        raise ValueError(
            f"Cannot create {DERIVED_HEIGHT_COL}; missing source column {HEIGHT_SOURCE_COL}."
        )

    df[DERIVED_HEIGHT_COL] = df[HEIGHT_SOURCE_COL].apply(parse_height_to_inches)

    print(
        f"\nCreated {DERIVED_HEIGHT_COL} from {HEIGHT_SOURCE_COL}: "
        f"{df[DERIVED_HEIGHT_COL].notna().sum():,} non-null rows"
    )

    return df


def percentile_over_dataset(df: pd.DataFrame, feature: str) -> pd.Series:
    """
    Computes 0-100 percentile over the entire queried DB result.

    Higher values get higher percentile for every feature except bvt_TO_per.
    For bvt_TO_per, lower values get higher percentile.
    """
    s = df[feature]

    if s.notna().sum() == 0:
        return pd.Series(np.nan, index=df.index, dtype=float)

    return (
        s.rank(
            method="average",
            pct=True,
            ascending=higher_is_better(feature),
        )
        * 100
    )


def add_group_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    group_features = get_all_group_features()

    if DERIVED_HEIGHT_COL in group_features:
        df = add_player_height_in(df)

    for feature in group_features:
        if feature == DERIVED_HEIGHT_COL:
            df[feature] = df[feature].apply(parse_height_to_inches)
        else:
            df[feature] = clean_numeric_series(df[feature])

    feature_pct_cols = {}

    for feature in group_features:
        pct_col = f"{feature}_percentile"
        df[pct_col] = percentile_over_dataset(df, feature)
        feature_pct_cols[feature] = pct_col

    for output_col, features in FEATURE_GROUPS.items():
        pct_cols = [feature_pct_cols[feature] for feature in features]
        df[output_col] = df[pct_cols].mean(axis=1, skipna=True)

    return df


# ============================================================
# MAIN
# ============================================================

def main():
    df = load_data()

    print(f"\nLoaded rows: {len(df):,}")
    print(f"Loaded columns: {len(df.columns):,}")

    df = add_group_percentiles(df)

    output_cols = [
        "spacing_percentile",
        "facilitating_percentile",
        "rim_protection_percentile",
        "defense_percentile",
        "finishing_percentile",
    ]

    # Drop intermediate feature-level percentile columns.
    feature_level_pct_cols = [
        col for col in df.columns
        if col.endswith("_percentile") and col not in output_cols
    ]

    # Keep queried DB columns plus player_height_in, then final 5 group percentiles.
    base_cols = [
        col for col in df.columns
        if col not in output_cols and col not in feature_level_pct_cols
    ]

    df = df[base_cols + output_cols]

    df.to_csv(OUTPUT_CSV, index=False)

    print(f"\nWrote output file: {OUTPUT_CSV}")

    print("\nNon-null counts:")
    for col in output_cols:
        print(f"  {col}: {df[col].notna().sum():,}")

    if DERIVED_HEIGHT_COL in df.columns:
        print(f"  {DERIVED_HEIGHT_COL}: {df[DERIVED_HEIGHT_COL].notna().sum():,}")


if __name__ == "__main__":
    main()