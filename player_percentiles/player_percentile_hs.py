from pathlib import Path
import re
import duckdb
import numpy as np
import pandas as pd


# ============================================================
# USER SETTINGS
# ============================================================

# Historical DB/table:
# This should contain historical HS recruits with:
#   - hs_year
#   - bvsrc_hs_rating
#   - bvsrc_hs_height_in
#   - actual college bvsrc_ stats used to calculate historical skill percentiles
HISTORICAL_DB_PATH = Path(
    "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/data_dir/hs_bv_evan_match.db"
)

HISTORICAL_TABLE_NAME = "hs_bv_evan_match"

# 2026 HS complete DB/table:
# This should contain current 2026 recruits from hs_complete.db.
HS_2026_DB_PATH = Path(
    "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/Basketball/College Basketball Project/uiuc_proj/data_dir/hs_complete.db"
)

HS_2026_TABLE_NAME = "hs_complete"

TARGET_HS_YEAR = 2026

OUTPUT_DIR = Path("hs_freshman_prior_percentile_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_2026_CSV = OUTPUT_DIR / "hs_2026_projected_skill_percentiles.csv"
OUTPUT_PRIORS_CSV = OUTPUT_DIR / "historical_freshman_prior_medians.csv"


# ============================================================
# COLUMN SETTINGS
# ============================================================

HISTORICAL_HS_YEAR_COL = "hs_year"
HISTORICAL_RATING_COL = "bvsrc_hs_rating"
HISTORICAL_HEIGHT_SOURCE_COL = "bvsrc_hs_height_in"

# This is derived in the script.
DERIVED_HEIGHT_COL = "player_height_in"

# The historical table may have one of these position columns.
# The first existing column will be used.
HISTORICAL_POSITION_CANDIDATES = [
    "bvsrc_hs_position"
]

# hs_complete columns
HS_YEAR_COL = "year"
HS_ID_COL = "player_key"
HS_NAME_COL = "full_name"
HS_POSITION_COL = "position"
HS_RATING_COL = "rating"
HS_NATIONAL_RANK_COL = "national_rank"
HS_HEIGHT_COL = "height_in"

# Optional columns to preserve from historical DB if they exist.
OPTIONAL_HISTORICAL_ID_COLS = [
    "allyears_pid",
    "name",
    "player_name",
    "team",
    "year",
    "hs_year",
    "bvsrc_hs_rating",
    "bvsrc_hs_height_in",
]

# Optional columns to preserve from hs_complete DB if they exist.
OPTIONAL_HS_2026_COLS = [
    "player_key",
    "first_name",
    "last_name",
    "full_name",
    "position",
    "height",
    "height_in",
    "weight",
    "stars",
    "rating",
    "national_rank",
    "position_rank",
    "state_rank",
    "hometown_city",
    "hometown_state",
    "committed_school",
    "committed_school_abbr",
    "committed_school_full",
    "signed_school",
    "signed_school_abbr",
    "signed_school_full",
    "current_school",
    "current_school_abbr",
    "current_school_full",
]


# ============================================================
# FEATURE GROUPS
# ============================================================
# These are the actual college features used to create historical
# outcome percentiles. The output columns are projected onto 2026 HS recruits
# by historical median bucket.

FEATURE_GROUPS = {
    "spacing_percentile": [
        "bvsrc_bv_FT_per",
        "bvsrc_bv_TP_per",
        "bvsrc_bv_midmade/(midmade+midmiss)",
        "bvsrc_bv_3p/100?",
    ],

    "facilitating_percentile": [
        "bvsrc_bv_usg",
        "bvsrc_bv_ast",
        "bvsrc_bv_TO_per",
        "bvsrc_bv_ast/tov",
    ],

    "rim_protection_percentile": [
        "bvsrc_bv_ORB_per",
        "bvsrc_bv_DRB_per",
        "bvsrc_bv_blk",
        "player_height_in",
    ],

    "defense_percentile": [
        "bvsrc_bv_blk",
        "bvsrc_bv_stl",
        "bvsrc_bv_drtg",
        "bvsrc_bv_stops",
    ],

    "finishing_percentile": [
        "bvsrc_bv_rimmade/(rimmade+rimmiss)",
        "bvsrc_bv_dunksmade/(dunksmade+dunksmiss)",
    ],
}

OUTPUT_PERCENTILE_COLS = list(FEATURE_GROUPS.keys())


# If a bucket has fewer than this many historical players, fallback is used.
MIN_BUCKET_N = 15


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
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.integer, np.floating)):
        value = float(value)

        if 50 <= value <= 100:
            return value

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


def normalize_position_group(pos) -> str | None:
    if pd.isna(pos):
        return None

    s = str(pos).upper().strip()

    if not s or s in {"N/A", "NA", "NONE", "NULL", "-"}:
        return None

    s = s.replace(" ", "")

    # Order matters for combo labels.
    if s in {"PG", "SG", "CG", "G", "COMBOGUARD"}:
        return "G"

    if s in {"SF", "PF", "F", "WF", "WING", "WINGF", "STRETCH4", "FORWARD"}:
        return "F"

    if s in {"C", "CENTER", "PF/C", "C/PF", "FC", "F/C"}:
        return "C"

    # Broader contains-based fallback.
    if "PG" in s or "SG" in s or s == "G":
        return "G"

    if "C" in s and "PG" not in s and "SG" not in s:
        return "C"

    if "F" in s or "WING" in s:
        return "F"

    return None


def higher_is_better(feature: str) -> bool:
    """
    Percentile direction.

    Lower turnover rate is better.
    Lower defensive rating is usually better.

    If your bvsrc_drtg column is already reverse-coded where higher is better,
    remove 'bvsrc_drtg' from this set.
    """
    lower_is_better = {
        "bvsrc_bv_TO_per",
        "bvsrc_bv_drtg",
    }

    return feature not in lower_is_better


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
    group_features = get_all_group_features()

    db_features = []

    for feature in group_features:
        if feature == DERIVED_HEIGHT_COL:
            continue

        if feature not in db_features:
            db_features.append(feature)

    if DERIVED_HEIGHT_COL in group_features and HISTORICAL_HEIGHT_SOURCE_COL not in db_features:
        db_features.append(HISTORICAL_HEIGHT_SOURCE_COL)

    return db_features


def choose_first_existing(candidates: list[str], existing_cols: list[str], label: str) -> str:
    col_map = resolve_columns(candidates, existing_cols)

    for c in candidates:
        if c in col_map:
            return col_map[c]

    raise ValueError(
        f"Could not find a usable {label} column. Tried:\n"
        + "\n".join(f"  - {x}" for x in candidates)
    )


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


# ============================================================
# HISTORICAL DATA LOAD
# ============================================================

def load_historical_data() -> pd.DataFrame:
    validate_config()

    db_features = get_db_features_needed()

    required_cols = [
        HISTORICAL_HS_YEAR_COL,
        HISTORICAL_RATING_COL,
        HISTORICAL_HEIGHT_SOURCE_COL,
    ] + db_features

    requested_cols = list(dict.fromkeys(OPTIONAL_HISTORICAL_ID_COLS + required_cols))

    con = duckdb.connect(str(HISTORICAL_DB_PATH), read_only=True)
    existing_cols = get_table_columns(con, HISTORICAL_TABLE_NAME)

    position_actual_col = choose_first_existing(
        HISTORICAL_POSITION_CANDIDATES,
        existing_cols,
        label="historical position",
    )

    col_map = resolve_columns(requested_cols, existing_cols)

    missing_required = [
        col for col in required_cols
        if col not in col_map
    ]

    if missing_required:
        print("\nAvailable historical columns:")
        for col in existing_cols:
            print(f"  - {col}")

        raise ValueError(
            "Missing required historical DB columns:\n"
            + "\n".join(f"  - {x}" for x in missing_required)
        )

    select_parts = []
    used_aliases = set()

    # Force the selected historical position column into one standard alias.
    select_parts.append(f"{quote_ident(position_actual_col)} AS source_position")
    used_aliases.add("source_position")

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
    FROM {quote_ident(HISTORICAL_TABLE_NAME)}
    WHERE {quote_ident(col_map[HISTORICAL_HS_YEAR_COL])} != ?
    """

    print("\nRunning historical query:")
    print(query)

    df = con.execute(query, [TARGET_HS_YEAR]).fetchdf()
    con.close()

    return df


# ============================================================
# 2026 HS DATA LOAD
# ============================================================

def load_hs_2026_data() -> pd.DataFrame:
    required_cols = [
        HS_YEAR_COL,
        HS_ID_COL,
        HS_NAME_COL,
        HS_POSITION_COL,
        HS_RATING_COL,
        HS_HEIGHT_COL,
    ]

    requested_cols = list(dict.fromkeys(OPTIONAL_HS_2026_COLS + required_cols))

    con = duckdb.connect(str(HS_2026_DB_PATH), read_only=True)
    existing_cols = get_table_columns(con, HS_2026_TABLE_NAME)

    col_map = resolve_columns(requested_cols, existing_cols)

    missing_required = [
        col for col in required_cols
        if col not in col_map
    ]

    if missing_required:
        print("\nAvailable hs_complete columns:")
        for col in existing_cols:
            print(f"  - {col}")

        raise ValueError(
            "Missing required hs_complete columns:\n"
            + "\n".join(f"  - {x}" for x in missing_required)
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
    FROM {quote_ident(HS_2026_TABLE_NAME)}
    WHERE {quote_ident(col_map[HS_YEAR_COL])} = ?
    """

    print("\nRunning 2026 HS query:")
    print(query)

    df = con.execute(query, [TARGET_HS_YEAR]).fetchdf()
    con.close()

    return df


# ============================================================
# HISTORICAL PERCENTILE LOGIC
# ============================================================

def add_player_height_in_from_historical(df: pd.DataFrame) -> pd.DataFrame:
    if HISTORICAL_HEIGHT_SOURCE_COL not in df.columns:
        raise ValueError(
            f"Cannot create {DERIVED_HEIGHT_COL}; "
            f"missing source column {HISTORICAL_HEIGHT_SOURCE_COL}."
        )

    df[DERIVED_HEIGHT_COL] = df[HISTORICAL_HEIGHT_SOURCE_COL].apply(parse_height_to_inches)

    print(
        f"\nCreated {DERIVED_HEIGHT_COL} from {HISTORICAL_HEIGHT_SOURCE_COL}: "
        f"{df[DERIVED_HEIGHT_COL].notna().sum():,} non-null rows"
    )

    return df


def percentile_over_historical_dataset(df: pd.DataFrame, feature: str) -> pd.Series:
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


def add_historical_group_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    group_features = get_all_group_features()

    if DERIVED_HEIGHT_COL in group_features:
        df = add_player_height_in_from_historical(df)

    for feature in group_features:
        if feature == DERIVED_HEIGHT_COL:
            df[feature] = df[feature].apply(parse_height_to_inches)
        else:
            df[feature] = clean_numeric_series(df[feature])

    feature_pct_cols = {}

    for feature in group_features:
        pct_col = f"{feature}_feature_percentile"
        df[pct_col] = percentile_over_historical_dataset(df, feature)
        feature_pct_cols[feature] = pct_col

    for output_col, features in FEATURE_GROUPS.items():
        pct_cols = [feature_pct_cols[feature] for feature in features]
        df[output_col] = df[pct_cols].mean(axis=1, skipna=True)

    return df


# ============================================================
# RATING TIER LOGIC
# ============================================================

def add_rating_percentile_and_tier(
    df: pd.DataFrame,
    year_col: str,
    rating_col: str,
) -> pd.DataFrame:
    df = df.copy()

    df[year_col] = clean_numeric_series(df[year_col])
    df[rating_col] = clean_numeric_series(df[rating_col])

    # This is the "top people in their class" adjustment.
    # A 0.995 rating in a weak class and a 0.995 rating in a strong class
    # are handled by class-relative percentile.
    df["rating_percentile_in_class"] = (
        df.groupby(year_col)[rating_col]
          .rank(method="average", pct=True, ascending=True)
        * 100
    )

    df["rating_tier"] = df["rating_percentile_in_class"].apply(rating_percentile_to_tier)

    return df


def rating_percentile_to_tier(pct) -> str:
    if pd.isna(pct):
        return "unknown_rating"

    pct = float(pct)

    if pct >= 99:
        return "top_1pct"
    if pct >= 95:
        return "top_5pct"
    if pct >= 90:
        return "top_10pct"
    if pct >= 75:
        return "top_25pct"
    if pct >= 50:
        return "top_50pct"

    return "lower_50pct"


# ============================================================
# HISTORICAL PRIORS
# ============================================================

def prepare_historical_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["position_group"] = df["source_position"].apply(normalize_position_group)

    df[HISTORICAL_RATING_COL] = clean_numeric_series(df[HISTORICAL_RATING_COL])
    df[HISTORICAL_HS_YEAR_COL] = clean_numeric_series(df[HISTORICAL_HS_YEAR_COL])

    df = df.dropna(subset=[
        "position_group",
        HISTORICAL_RATING_COL,
        HISTORICAL_HS_YEAR_COL,
    ]).copy()

    df = add_rating_percentile_and_tier(
        df,
        year_col=HISTORICAL_HS_YEAR_COL,
        rating_col=HISTORICAL_RATING_COL,
    )

    df = add_historical_group_percentiles(df)

    # Keep only rows that have at least one computed output percentile.
    df = df[df[OUTPUT_PERCENTILE_COLS].notna().any(axis=1)].copy()

    return df


def build_historical_priors(historical: pd.DataFrame) -> dict:
    """
    Builds median lookup tables.

    Fallback order for 2026 projection:
      1. position_group + rating_tier, if bucket count >= MIN_BUCKET_N
      2. position_group
      3. rating_tier
      4. overall
    """

    exact = (
        historical
        .groupby(["position_group", "rating_tier"], dropna=False)
        .agg(
            historical_n=("rating_tier", "size"),
            **{
                col: (col, "median")
                for col in OUTPUT_PERCENTILE_COLS
            }
        )
        .reset_index()
    )

    position_only = (
        historical
        .groupby(["position_group"], dropna=False)
        .agg(
            historical_n=("position_group", "size"),
            **{
                col: (col, "median")
                for col in OUTPUT_PERCENTILE_COLS
            }
        )
        .reset_index()
    )

    rating_only = (
        historical
        .groupby(["rating_tier"], dropna=False)
        .agg(
            historical_n=("rating_tier", "size"),
            **{
                col: (col, "median")
                for col in OUTPUT_PERCENTILE_COLS
            }
        )
        .reset_index()
    )

    overall_values = {
        "historical_n": int(len(historical)),
        **{
            col: float(historical[col].median(skipna=True))
            for col in OUTPUT_PERCENTILE_COLS
        }
    }

    exact.to_csv(OUTPUT_PRIORS_CSV, index=False)

    return {
        "exact": exact,
        "position_only": position_only,
        "rating_only": rating_only,
        "overall": overall_values,
    }


def lookup_prior_for_player(row: pd.Series, priors: dict) -> dict:
    position_group = row["position_group"]
    rating_tier = row["rating_tier"]

    exact = priors["exact"]
    match = exact[
        (exact["position_group"] == position_group)
        & (exact["rating_tier"] == rating_tier)
        & (exact["historical_n"] >= MIN_BUCKET_N)
    ]

    if len(match) > 0:
        r = match.iloc[0]
        return {
            **{col: float(r[col]) for col in OUTPUT_PERCENTILE_COLS},
            "prior_source": "position_group_plus_rating_tier",
            "prior_historical_n": int(r["historical_n"]),
        }

    position_only = priors["position_only"]
    match = position_only[position_only["position_group"] == position_group]

    if len(match) > 0:
        r = match.iloc[0]
        return {
            **{col: float(r[col]) for col in OUTPUT_PERCENTILE_COLS},
            "prior_source": "position_group_only",
            "prior_historical_n": int(r["historical_n"]),
        }

    rating_only = priors["rating_only"]
    match = rating_only[rating_only["rating_tier"] == rating_tier]

    if len(match) > 0:
        r = match.iloc[0]
        return {
            **{col: float(r[col]) for col in OUTPUT_PERCENTILE_COLS},
            "prior_source": "rating_tier_only",
            "prior_historical_n": int(r["historical_n"]),
        }

    overall = priors["overall"]

    return {
        **{col: float(overall[col]) for col in OUTPUT_PERCENTILE_COLS},
        "prior_source": "overall",
        "prior_historical_n": int(overall["historical_n"]),
    }


# ============================================================
# 2026 PROJECTION
# ============================================================

def prepare_hs_2026_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["position_group"] = df[HS_POSITION_COL].apply(normalize_position_group)

    df[HS_YEAR_COL] = clean_numeric_series(df[HS_YEAR_COL])
    df[HS_RATING_COL] = clean_numeric_series(df[HS_RATING_COL])
    df[HS_HEIGHT_COL] = clean_numeric_series(df[HS_HEIGHT_COL])

    df = df.dropna(subset=[
        HS_ID_COL,
        HS_NAME_COL,
        "position_group",
        HS_YEAR_COL,
        HS_RATING_COL,
    ]).copy()

    df = add_rating_percentile_and_tier(
        df,
        year_col=HS_YEAR_COL,
        rating_col=HS_RATING_COL,
    )

    # Useful for site integration until you settle the HS ID policy.
    # Do not treat this as a BartTorvik allyears_pid.
    df["optimizer_player_id"] = "hs:" + df[HS_ID_COL].astype(str)

    df["source_type"] = "hs_recruit"

    return df


def project_2026_percentiles(hs_2026: pd.DataFrame, priors: dict) -> pd.DataFrame:
    hs_2026 = hs_2026.copy()

    prior_rows = hs_2026.apply(
        lambda row: pd.Series(lookup_prior_for_player(row, priors)),
        axis=1,
    )

    out = pd.concat([hs_2026.reset_index(drop=True), prior_rows.reset_index(drop=True)], axis=1)

    return out


# ============================================================
# MAIN
# ============================================================

def main():
    historical_raw = load_historical_data()

    print(f"\nLoaded historical rows: {len(historical_raw):,}")
    print(f"Loaded historical columns: {len(historical_raw.columns):,}")

    historical = prepare_historical_rows(historical_raw)

    print(f"\nUsable historical rows after cleaning: {len(historical):,}")

    print("\nHistorical rows by position group:")
    print(historical["position_group"].value_counts(dropna=False).to_string())

    print("\nHistorical rows by rating tier:")
    print(historical["rating_tier"].value_counts(dropna=False).to_string())

    priors = build_historical_priors(historical)

    hs_2026_raw = load_hs_2026_data()

    print(f"\nLoaded 2026 HS rows: {len(hs_2026_raw):,}")
    print(f"Loaded 2026 HS columns: {len(hs_2026_raw.columns):,}")

    hs_2026 = prepare_hs_2026_rows(hs_2026_raw)

    print(f"\nUsable 2026 HS rows after cleaning: {len(hs_2026):,}")

    projected = project_2026_percentiles(hs_2026, priors)

    # Final output columns.
    preferred_front_cols = [
        "optimizer_player_id",
        HS_ID_COL,
        HS_NAME_COL,
        HS_POSITION_COL,
        "position_group",
        HS_RATING_COL,
        "rating_percentile_in_class",
        "rating_tier",
        HS_NATIONAL_RANK_COL,
        HS_HEIGHT_COL,
        "source_type",
        "prior_source",
        "prior_historical_n",
    ]

    existing_front_cols = [col for col in preferred_front_cols if col in projected.columns]

    remaining_cols = [
        col for col in projected.columns
        if col not in existing_front_cols and col not in OUTPUT_PERCENTILE_COLS
    ]

    projected = projected[
        existing_front_cols
        + OUTPUT_PERCENTILE_COLS
        + remaining_cols
    ].copy()

    projected.to_csv(OUTPUT_2026_CSV, index=False)

    print(f"\nWrote 2026 projected percentiles: {OUTPUT_2026_CSV}")
    print(f"Wrote historical prior medians: {OUTPUT_PRIORS_CSV}")

    print("\nProjected percentile non-null counts:")
    for col in OUTPUT_PERCENTILE_COLS:
        print(f"  {col}: {projected[col].notna().sum():,}")

    print("\nPrior source counts:")
    print(projected["prior_source"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()