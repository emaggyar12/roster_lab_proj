from pathlib import Path
import re
import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.cluster import KMeans


# ============================================================
# USER SETTINGS
# ============================================================

DB_PATH = Path(
    "/Users/anirudhhaharsha/Desktop/sports_analytics_projects/"
    "Basketball/College Basketball Project/uiuc_proj/data_dir/"
    "evan_miya_barttorvik_matched.db"
)

TABLE_NAME = "evan_miya_barttorvik_matched"

OUTPUT_DIR = Path("kmeans_cluster_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_CLUSTERED_CSV = OUTPUT_DIR / "players_with_kmeans_clusters.csv"
OUTPUT_ELBOW_PLOT = OUTPUT_DIR / "kmeans_elbow_plot.png"

OUTPUT_ASSIGNMENT_EXPLANATIONS_LONG = OUTPUT_DIR / "kmeans_player_assignment_explanations_long.csv"
OUTPUT_ASSIGNMENT_EXPLANATIONS_WIDE = OUTPUT_DIR / "kmeans_player_assignment_explanations_wide.csv"
OUTPUT_CLUSTER_CENTROID_PROFILES = OUTPUT_DIR / "kmeans_cluster_centroid_profiles.csv"

FINAL_K = 6

# You said to keep max tries at 10.
K_MIN = 1
K_MAX = 10

TOP_N_ASSIGNMENT_FEATURES = 10

OPTIONAL_ID_COLS = [
    "name",
    "bvt_pid",
]


# ============================================================
# FEATURES — NO old_ PREFIXES
# ============================================================

RAW_FEATURES = [
    "basic_obpr",
    "basic_dbpr",
    "basic_poss",
    "basic_box_obpr",
    "basic_box_dbpr",
    "basic_adj_team_off_eff",
    "basic_adj_team_def_eff",

    "bvt_ORtg",
    "bvt_usg",
    "bvt_eFG",
    "bvt_TS_per",
    "bvt_TO_per",
    "bvt_FTM",
    "bvt_FTA",
    "bvt_FT_per",
    "bvt_twoP_per",
    "bvt_TPM",
    "bvt_TPA",
    "bvt_TP_per",
    "bvt_blk_per",
    "bvt_ftr",
    "bvt_ht",
    "bvt_porpag",
    "bvt_adjoe",
    "bvt_pfr",

    "bvt_Rec Rank",
    "bvt_ast/tov",
    "bvt_rimmade/(rimmade+rimmiss)",
    "bvt_midmade/(midmade+midmiss)",
    "bvt_dunksmade/(dunksmade+dunksmiss)",
    "bvt_drtg",
    "bvt_adrtg",
    "bvt_dporpag",
    "bvt_stops",
    "bvt_bpm",
    "bvt_obpm",
    "bvt_dbpm",
    "bvt_gbpm",
    "bvt_mp",
    "bvt_ogbpm",
    "bvt_dgbpm",
    "bvt_oreb",
    "bvt_dreb",
    "bvt_treb",
    "bvt_ast",
    "bvt_stl",
    "bvt_blk",
    "bvt_pts",
    "bvt_3p/100?",

    "bvt_player_height",
]


# ============================================================
# SQL HELPERS
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
    normalized_to_actual = {}

    for col in existing_cols:
        lower_to_actual.setdefault(col.lower(), col)
        normalized_to_actual.setdefault(normalize_col_name(col), col)

    resolved = {}

    for requested in requested_cols:
        actual = None

        if requested in existing_exact:
            actual = requested
        elif requested.lower() in lower_to_actual:
            actual = lower_to_actual[requested.lower()]
        elif normalize_col_name(requested) in normalized_to_actual:
            actual = normalized_to_actual[normalize_col_name(requested)]

        if actual is not None:
            resolved[requested] = actual

    return resolved


# ============================================================
# HEIGHT HELPERS
# ============================================================

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

    m = re.match(r"^\s*(\d)\s*-\s*(\d{1,2})\s*$", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))

    m = re.match(r"^\s*(\d)\s*'\s*(\d{0,2})\s*\"?\s*$", s)
    if m:
        feet = int(m.group(1))
        inches = int(m.group(2)) if m.group(2) else 0
        return feet * 12 + inches

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


def is_height_col(col: str) -> bool:
    c = col.lower()

    return (
        "height" in c
        or c == "ht"
        or c.endswith("_ht")
        or re.search(r"(^|_)ht($|_)", c) is not None
    )


def collapse_height_features(df: pd.DataFrame, feature_cols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    height_cols = [
        col for col in feature_cols
        if col in df.columns and is_height_col(col)
    ]

    if not height_cols:
        print("\nNo height columns found among selected features.")
        return df, feature_cols

    print("\nHeight columns collapsed into height_inches:")
    for col in height_cols:
        print(f"  - {col}")

    converted = pd.DataFrame(index=df.index)

    for col in height_cols:
        converted[col] = df[col].apply(parse_height_to_inches)

    df["height_inches"] = converted.bfill(axis=1).iloc[:, 0]

    non_null_height = df["height_inches"].notna().sum()
    print(f"Non-null height_inches rows: {non_null_height:,}")

    df = df.drop(columns=height_cols, errors="ignore")

    new_feature_cols = [
        col for col in feature_cols
        if col not in height_cols
    ]

    if non_null_height > 0:
        new_feature_cols.append("height_inches")
    else:
        print("WARNING: height columns existed, but none converted. Dropping height_inches.")
        df = df.drop(columns=["height_inches"], errors="ignore")

    return df, new_feature_cols


# ============================================================
# CLEANING HELPERS
# ============================================================

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


def coerce_numeric_like_columns(feature_df: pd.DataFrame) -> pd.DataFrame:
    feature_df = feature_df.copy()

    for col in feature_df.columns:
        if feature_df[col].dtype == "object":
            numeric_version = clean_numeric_series(feature_df[col])

            non_null_original = feature_df[col].notna().sum()
            non_null_numeric = numeric_version.notna().sum()

            if non_null_original == 0:
                continue

            conversion_rate = non_null_numeric / non_null_original

            if conversion_rate >= 0.80:
                feature_df[col] = numeric_version

    return feature_df


def drop_all_null_columns(feature_df: pd.DataFrame) -> pd.DataFrame:
    all_null_cols = [
        col for col in feature_df.columns
        if feature_df[col].isna().all()
    ]

    if all_null_cols:
        print("\nDropping all-null feature columns:")
        for col in all_null_cols:
            print(f"  - {col}")

        feature_df = feature_df.drop(columns=all_null_cols)

    return feature_df


# ============================================================
# LOAD DATA
# ============================================================

def load_data() -> tuple[pd.DataFrame, list[str], list[str]]:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    existing_cols = get_table_columns(con, TABLE_NAME)

    id_map = resolve_columns(OPTIONAL_ID_COLS, existing_cols)
    feature_map = resolve_columns(RAW_FEATURES, existing_cols)

    missing_features = [
        feature for feature in RAW_FEATURES
        if feature not in feature_map
    ]

    print("\nResolved ID columns:")
    if id_map:
        for requested, actual in id_map.items():
            print(f"  {requested} -> {actual}")
    else:
        print("  None")

    print("\nResolved feature columns:")
    if feature_map:
        for requested, actual in feature_map.items():
            print(f"  {requested} -> {actual}")
    else:
        print("  None")

    print(f"\nFeature columns found: {len(feature_map)} / {len(RAW_FEATURES)}")

    if missing_features:
        print(f"\nMissing requested features: {len(missing_features)}")
        for col in missing_features:
            print(f"  - {col}")

    if not feature_map:
        print("\nAvailable columns in table:")
        for col in existing_cols:
            print(f"  - {col}")

        raise ValueError(
            "\nNo clustering feature columns were found.\n"
            "ID columns like name and bvt_pid do not count as model features."
        )

    select_parts = []
    used_aliases = set()

    for requested, actual in id_map.items():
        alias = requested

        if alias in used_aliases:
            alias = f"id_{requested}"

        used_aliases.add(alias)
        select_parts.append(f"{quote_ident(actual)} AS {quote_ident(alias)}")

    for requested, actual in feature_map.items():
        alias = requested

        if alias in used_aliases:
            alias = f"feature_{requested}"

        used_aliases.add(alias)
        select_parts.append(f"{quote_ident(actual)} AS {quote_ident(alias)}")

    select_sql = ",\n        ".join(select_parts)

    query = f"""
    SELECT
        {select_sql}
    FROM {quote_ident(TABLE_NAME)}
    """

    print("\nRunning query:")
    print(query)

    df = con.execute(query).fetchdf()
    con.close()

    id_cols = list(id_map.keys())
    feature_cols = list(feature_map.keys())

    return df, id_cols, feature_cols


# ============================================================
# KMEANS EXPLANATION HELPERS
# ============================================================

def get_feature_names(preprocessor: ColumnTransformer) -> list[str]:
    feature_names = []

    for name, transformer, cols in preprocessor.transformers_:
        if name == "remainder":
            continue

        if name == "num":
            feature_names.extend(cols)

        elif name == "cat":
            onehot = transformer.named_steps["onehot"]
            cat_names = onehot.get_feature_names_out(cols)
            feature_names.extend(cat_names.tolist())

    return feature_names


def save_kmeans_assignment_explanations(
    X: np.ndarray,
    labels: np.ndarray,
    kmeans: KMeans,
    feature_names: list[str],
    output_df: pd.DataFrame,
    id_cols: list[str],
    output_long_csv: Path,
    output_wide_csv: Path,
    output_centroid_profiles_csv: Path,
    top_n: int = 10,
):
    """
    Per-player KMeans assignment explanation.

    KMeans assigns a row to the closest centroid.

    For each player and each feature:

        assignment_pull =
            squared distance to runner-up centroid on this feature
            -
            squared distance to assigned centroid on this feature

    Positive value:
        this feature made the assigned cluster closer than the runner-up cluster.

    Bigger positive value:
        stronger reason the player landed in the assigned bucket.
    """

    centroids = kmeans.cluster_centers_

    squared_diffs = (X[:, None, :] - centroids[None, :, :]) ** 2
    total_squared_distances = squared_diffs.sum(axis=2)

    sorted_cluster_indices = np.argsort(total_squared_distances, axis=1)

    assigned_clusters = labels
    runner_up_clusters = sorted_cluster_indices[:, 1]

    assigned_distances = np.sqrt(
        total_squared_distances[np.arange(len(X)), assigned_clusters]
    )

    runner_up_distances = np.sqrt(
        total_squared_distances[np.arange(len(X)), runner_up_clusters]
    )

    id_cols_present = [c for c in id_cols if c in output_df.columns]

    rows_long = []
    rows_wide = []

    for i in range(len(X)):
        assigned = int(assigned_clusters[i])
        runner_up = int(runner_up_clusters[i])

        assigned_feature_dists = squared_diffs[i, assigned, :]
        runner_up_feature_dists = squared_diffs[i, runner_up, :]

        assignment_pull = runner_up_feature_dists - assigned_feature_dists

        top_idx = np.argsort(assignment_pull)[::-1][:top_n]

        base_info = {
            "row_index": i,
            "kmeans_cluster": assigned,
            "runner_up_cluster": runner_up,
            "assigned_cluster_distance": float(assigned_distances[i]),
            "runner_up_cluster_distance": float(runner_up_distances[i]),
            "distance_margin_runner_up_minus_assigned": float(
                runner_up_distances[i] - assigned_distances[i]
            ),
        }

        for col in id_cols_present:
            base_info[col] = output_df.iloc[i][col]

        wide_row = dict(base_info)

        for rank, j in enumerate(top_idx, start=1):
            feature = feature_names[j]

            rows_long.append({
                **base_info,
                "rank": rank,
                "feature": feature,
                "assignment_pull": float(assignment_pull[j]),
                "player_value_scaled": float(X[i, j]),
                "assigned_centroid_value_scaled": float(centroids[assigned, j]),
                "runner_up_centroid_value_scaled": float(centroids[runner_up, j]),
                "squared_distance_to_assigned_centroid_feature": float(assigned_feature_dists[j]),
                "squared_distance_to_runner_up_centroid_feature": float(runner_up_feature_dists[j]),
            })

            wide_row[f"top_{rank}_feature"] = feature
            wide_row[f"top_{rank}_assignment_pull"] = float(assignment_pull[j])
            wide_row[f"top_{rank}_player_value_scaled"] = float(X[i, j])
            wide_row[f"top_{rank}_assigned_centroid_scaled"] = float(centroids[assigned, j])
            wide_row[f"top_{rank}_runner_up_centroid_scaled"] = float(centroids[runner_up, j])

        rows_wide.append(wide_row)

    long_df = pd.DataFrame(rows_long)
    wide_df = pd.DataFrame(rows_wide)

    long_df.to_csv(output_long_csv, index=False)
    wide_df.to_csv(output_wide_csv, index=False)

    centroid_profiles = pd.DataFrame(
        centroids,
        columns=feature_names,
    )

    centroid_profiles.insert(0, "kmeans_cluster", np.arange(len(centroids)))
    centroid_profiles.to_csv(output_centroid_profiles_csv, index=False)

    print(f"\nSaved assignment explanation long CSV to: {output_long_csv}")
    print(f"Saved assignment explanation wide CSV to: {output_wide_csv}")
    print(f"Saved centroid profiles CSV to: {output_centroid_profiles_csv}")


# ============================================================
# MAIN CLUSTERING PIPELINE
# ============================================================

def main():
    df, id_cols, feature_cols = load_data()

    print(f"\nLoaded rows: {len(df):,}")
    print(f"Loaded columns: {len(df.columns):,}")

    df, feature_cols = collapse_height_features(df, feature_cols)

    feature_cols = [
        col for col in feature_cols
        if col in df.columns
    ]

    if not feature_cols:
        raise ValueError("No feature columns remain after height processing.")

    feature_df = df[feature_cols].copy()

    feature_df = coerce_numeric_like_columns(feature_df)
    feature_df = drop_all_null_columns(feature_df)

    if feature_df.shape[1] == 0:
        raise ValueError(
            "\nNo usable features remain after cleaning.\n"
            "The selected feature columns are all null or invalid."
        )

    numeric_cols = feature_df.select_dtypes(
        include=["number", "bool"]
    ).columns.tolist()

    categorical_cols = feature_df.select_dtypes(
        exclude=["number", "bool"]
    ).columns.tolist()

    print("\nFinal numeric columns used:")
    for col in numeric_cols:
        print(f"  - {col}")

    if categorical_cols:
        print("\nFinal categorical columns one-hot encoded:")
        for col in categorical_cols:
            print(f"  - {col}")

    if not numeric_cols and not categorical_cols:
        raise ValueError("No usable features found after preprocessing.")

    transformers = []

    if numeric_cols:
        numeric_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )

        transformers.append(("num", numeric_pipeline, numeric_cols))

    if categorical_cols:
        categorical_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]
        )

        transformers.append(("cat", categorical_pipeline, categorical_cols))

    preprocessor = ColumnTransformer(
        transformers=transformers,
        remainder="drop",
    )

    X = preprocessor.fit_transform(feature_df)

    if X.shape[1] == 0:
        raise ValueError(
            "Preprocessing produced zero columns. "
            "Check selected features and missing values."
        )

    if np.isnan(X).any():
        raise ValueError("NaNs remain after preprocessing. Check the input data.")

    feature_names = get_feature_names(preprocessor)

    if len(feature_names) != X.shape[1]:
        raise ValueError(
            f"Feature name count mismatch: {len(feature_names)} names for {X.shape[1]} columns."
        )

    print(f"\nModel matrix shape: {X.shape}")

    # # ========================================================
    # # ELBOW PLOT — KEEPING 1 THROUGH 10
    # # ========================================================

    # if len(df) <= K_MAX:
    #     raise ValueError(
    #         f"Not enough rows to try k=1 through k={K_MAX}."
    #     )

    # ks = list(range(K_MIN, K_MAX + 1))
    # inertias = []

    # print("\nFitting elbow models...")

    # for k in ks:
    #     km = KMeans(
    #         n_clusters=k,
    #         random_state=42,
    #         n_init=50,
    #         max_iter=500,
    #     )

    #     km.fit(X)
    #     inertias.append(km.inertia_)

    #     print(f"k={k:>2} inertia={km.inertia_:,.2f}")

    # plt.figure(figsize=(9, 6))
    # plt.plot(ks, inertias, marker="o")
    # plt.xlabel("Number of clusters, k")
    # plt.ylabel("Inertia")
    # plt.title("KMeans Elbow Plot")
    # plt.grid(True, alpha=0.3)
    # plt.tight_layout()
    # plt.savefig(OUTPUT_ELBOW_PLOT, dpi=200)
    # plt.close()

    # print(f"\nSaved elbow plot to: {OUTPUT_ELBOW_PLOT}")

    # ========================================================
    # FINAL KMEANS
    # ========================================================

    if FINAL_K >= len(df):
        raise ValueError(
            f"FINAL_K={FINAL_K} is too large for {len(df):,} rows."
        )

    print(f"\nFitting final KMeans model with k={FINAL_K}...")

    final_kmeans = KMeans(
        n_clusters=FINAL_K,
        random_state=42,
        n_init=50,
        max_iter=500,
    )

    labels = final_kmeans.fit_predict(X)

    output_df = df.copy()
    output_df["kmeans_cluster"] = labels

    distances = final_kmeans.transform(X)
    output_df["kmeans_cluster_distance"] = distances[np.arange(len(labels)), labels]

    save_kmeans_assignment_explanations(
        X=X,
        labels=labels,
        kmeans=final_kmeans,
        feature_names=feature_names,
        output_df=output_df,
        id_cols=id_cols,
        output_long_csv=OUTPUT_ASSIGNMENT_EXPLANATIONS_LONG,
        output_wide_csv=OUTPUT_ASSIGNMENT_EXPLANATIONS_WIDE,
        output_centroid_profiles_csv=OUTPUT_CLUSTER_CENTROID_PROFILES,
        top_n=TOP_N_ASSIGNMENT_FEATURES,
    )

    output_df.to_csv(OUTPUT_CLUSTERED_CSV, index=False)

    print(f"\nSaved clustered CSV to: {OUTPUT_CLUSTERED_CSV}")

    print("\nCluster counts:")
    print(output_df["kmeans_cluster"].value_counts().sort_index())

    print("\nDone.")


if __name__ == "__main__":
    main()