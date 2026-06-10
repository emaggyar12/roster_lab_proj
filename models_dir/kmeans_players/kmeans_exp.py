from pathlib import Path
import pandas as pd

OUTPUT_DIR = Path("kmeans_cluster_outputs")

INPUT_LONG_CSV = OUTPUT_DIR / "kmeans_player_assignment_explanations_long.csv"

OUTPUT_CLUSTER_TOP5_CSV = OUTPUT_DIR / "kmeans_cluster_top5_assignment_features.csv"
OUTPUT_CLUSTER_TOP5_TXT = OUTPUT_DIR / "kmeans_cluster_top5_assignment_features.txt"

TOP_N = 5


def main():
    df = pd.read_csv(INPUT_LONG_CSV)

    required_cols = [
        "kmeans_cluster",
        "feature",
        "assignment_pull",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns from {INPUT_LONG_CSV}: {missing}")

    # Keep only positive pulls.
    # Positive = feature made assigned cluster closer than runner-up cluster.
    df = df[df["assignment_pull"] > 0].copy()

    if df.empty:
        raise ValueError("No positive assignment_pull rows found.")

    report = (
        df.groupby(["kmeans_cluster", "feature"], as_index=False)
          .agg(
              mean_assignment_pull=("assignment_pull", "mean"),
              median_assignment_pull=("assignment_pull", "median"),
              total_assignment_pull=("assignment_pull", "sum"),
              player_count=("assignment_pull", "size"),
          )
    )

    # Rank features within each cluster by average pull.
    report["rank"] = (
        report.groupby("kmeans_cluster")["mean_assignment_pull"]
              .rank(method="first", ascending=False)
              .astype(int)
    )

    top5 = (
        report[report["rank"] <= TOP_N]
        .sort_values(["kmeans_cluster", "rank"])
        [
            [
                "kmeans_cluster",
                "rank",
                "feature",
                "mean_assignment_pull",
                "median_assignment_pull",
                "total_assignment_pull",
                "player_count",
            ]
        ]
    )

    top5.to_csv(OUTPUT_CLUSTER_TOP5_CSV, index=False)

    lines = []
    for cluster, g in top5.groupby("kmeans_cluster"):
        lines.append(f"\nCluster {cluster}")
        lines.append("-" * 60)

        for _, row in g.iterrows():
            lines.append(
                f"{int(row['rank'])}. {row['feature']} "
                f"| mean pull={row['mean_assignment_pull']:.4f} "
                f"| median pull={row['median_assignment_pull']:.4f} "
                f"| players={int(row['player_count'])}"
            )

    OUTPUT_CLUSTER_TOP5_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote CSV: {OUTPUT_CLUSTER_TOP5_CSV}")
    print(f"Wrote TXT: {OUTPUT_CLUSTER_TOP5_TXT}")

    print("\nTop 5 assignment features per cluster:")
    print(top5.to_string(index=False))


if __name__ == "__main__":
    main()