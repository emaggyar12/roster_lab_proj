# Roster Gap Optimizer Codex Spec

## Non-negotiable objective

Implement the optimizer exactly with this lexicographic priority order:

1. **Primary objective:** maximize total final team rating across the 5 rating categories.
2. **Secondary tie-breaker:** maximize the weakest final team category.
3. **Final tie-breaker:** maximize total projected BPR.

Do **not** replace this with arbitrary weighted formulas. Do **not** invent scalar weights between skill ratings and BPR. BPR should affect player impact through roster-weighted rating calculations and then serve as the final tie-breaker.

---

## Unique identifier

The site/player database unique identifier is:

```text
allyears_pid
```

Every roster selection, candidate exclusion, recommendation output, and frontend/backend player reference should use `allyears_pid` as the unique player identifier.

Do not use `player_id`, `pid`, `247_player_key`, names, or URLs as the primary identifier for this optimizer.

---

## Intended website flow

The website will allow the user to construct a roster under positional constraints.

Default target roster structure:

```text
5 Guards
6 Forwards
4 Centers
Total = 15 players
```

The user can add/subtract target slots by position, but the site should not allow more than 15 total target roster spots.

Example target counts:

```text
G = 5
F = 6
C = 4
```

If the current selected roster has:

```text
G = 3
F = 4
C = 2
```

Then the optimizer should fill:

```text
G_needed = 2
F_needed = 2
C_needed = 2
```

The optimizer should select exactly that many candidates by position from the available transfer/recruit pool.

---

## Required database columns

The current roster and candidate pool tables should expose these columns, or the backend query should alias columns to these names:

```text
allyears_pid
player_name
position_group
projected_bpr
scoring_percentile
spacing_percentile
playmaking_percentile
rebounding_percentile
defense_percentile
year
```

`position_group` must be normalized before optimization to one of:

```text
G
F
C
```

The five optimization rating categories are:

```text
scoring_percentile
spacing_percentile
playmaking_percentile
rebounding_percentile
defense_percentile
```

If the actual database uses different names, alias them in the SQL query rather than changing the optimizer logic.

---

## BPR-adjusted roster rating concept

The team percentile ratings should not be a simple unweighted average if projected BPR is available.

The intended logic is:

```text
team_skill_rating = sum(player_skill_percentile * player_weight) / sum(player_weight)
```

Where `player_weight` is derived from projected BPR.

This means a high-BPR player affects the team rating more than a low-BPR player. For example:

```text
Player A spacing = 90, projected_bpr = 10
Player B spacing = 50, projected_bpr = 5
```

If using raw positive BPR as weights:

```text
team_spacing = (90 * 10 + 50 * 5) / (10 + 5)
             = 76.7
```

The lower-spacing player still drags spacing down, but only in proportion to his roster importance.

Because BPR can be negative, do not use raw BPR directly as a weight without safeguards. Use a safe transformation.

Recommended first-pass weight function:

```python
def bpr_to_weight(projected_bpr: float) -> float:
    return max(projected_bpr + 2.0, 0.5)
```

Alternative if projected minutes are later available:

```text
player_weight = projected_minutes
```

For the current version, use BPR-derived weights.

---

## Optimization interpretation with BPR-adjusted ratings

The optimizer should evaluate final team ratings after adding selected candidates.

For each skill category:

```text
final_skill_rating =
    (current_weighted_skill_sum + selected_candidate_weighted_skill_sum)
    /
    (current_total_weight + selected_candidate_total_weight)
```

Where:

```text
current_weighted_skill_sum = sum(current_roster_player_skill * current_roster_player_weight)
selected_candidate_weighted_skill_sum = sum(candidate_skill * candidate_weight * x_i)
current_total_weight = sum(current_roster_player_weight)
selected_candidate_total_weight = sum(candidate_weight * x_i)
```

`x_i` is 1 if candidate `i` is selected and 0 otherwise.

Important implementation note:

If candidate weights vary, the exact weighted-average objective contains a denominator that depends on the selected players. This is not a pure linear objective in the strict mathematical sense.

For implementation simplicity, use one of the following approaches:

### Recommended practical approach for Codex

Use candidate BPR weights to compute each candidate's weighted contribution:

```text
candidate_weighted_total_skill = candidate_weight * (
    scoring_percentile
  + spacing_percentile
  + playmaking_percentile
  + rebounding_percentile
  + defense_percentile
)
```

Then optimize selected weighted contribution subject to position constraints.

This directly implements the idea that higher-BPR players change the roster more.

After the optimizer chooses players, compute the actual final weighted team ratings using the full weighted average formula above.

### Exact-but-more-complex approach

If exact weighted average optimization is desired later, brute force may be acceptable for small candidate lists, or use a fractional programming transformation. Do not do that now unless necessary.

---

## Optimization formulation

Let:

```text
x_i = 1 if candidate i is selected
x_i = 0 otherwise
```

Position constraints:

```text
sum(is_guard_i   * x_i) = G_needed
sum(is_forward_i * x_i) = F_needed
sum(is_center_i  * x_i) = C_needed
```

Roster size constraint:

```text
current_roster_size + sum(x_i) <= 15
```

Primary objective:

```text
maximize final_scoring
       + final_spacing
       + final_playmaking
       + final_rebounding
       + final_defense
```

Using the practical implementation, this becomes:

```text
maximize sum(x_i * candidate_weighted_total_skill_i)
```

Secondary tie-breaker:

Among all solutions that achieve the best primary objective value, maximize the weakest final team category:

```text
maximize min(
    final_scoring,
    final_spacing,
    final_playmaking,
    final_rebounding,
    final_defense
)
```

Final tie-breaker:

Among all solutions that achieve the best primary objective and best weakest-category objective, maximize:

```text
sum(x_i * projected_bpr_i)
```

---

## Code skeleton

This is a backend-oriented Python implementation using DuckDB, pandas, NumPy, and SciPy MILP.

```python
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds


# ============================================================
# SETTINGS
# ============================================================

DB_PATH = Path("YOUR_DATABASE.db")

CURRENT_ROSTER_TABLE = "current_roster_table"
CANDIDATE_TABLE = "available_recruits_and_transfers"

ID_COL = "allyears_pid"
NAME_COL = "player_name"
POSITION_COL = "position_group"  # must be G, F, or C
BPR_COL = "projected_bpr"
YEAR_COL = "year"

SKILL_COLS = [
    "scoring_percentile",
    "spacing_percentile",
    "playmaking_percentile",
    "rebounding_percentile",
    "defense_percentile",
]

DEFAULT_TARGET_COUNTS = {
    "G": 5,
    "F": 6,
    "C": 4,
}


# ============================================================
# WEIGHTING
# ============================================================

def bpr_to_weight(projected_bpr: float) -> float:
    """
    Converts projected BPR into a positive roster-impact weight.

    This makes high-BPR players affect team percentile changes more than low-BPR players.
    The offset/floor prevents negative or zero weights.
    """
    if pd.isna(projected_bpr):
        return 0.5
    return max(float(projected_bpr) + 2.0, 0.5)


# ============================================================
# DATA CLEANING
# ============================================================

def clean_player_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    keep_cols = [ID_COL, NAME_COL, POSITION_COL, BPR_COL] + SKILL_COLS
    df = df[keep_cols].copy()

    df[ID_COL] = df[ID_COL].astype(str).str.strip()
    df[NAME_COL] = df[NAME_COL].astype(str).str.strip()
    df[POSITION_COL] = df[POSITION_COL].astype(str).str.upper().str.strip()

    valid_positions = {"G", "F", "C"}
    df = df[df[POSITION_COL].isin(valid_positions)].copy()

    numeric_cols = [BPR_COL] + SKILL_COLS
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=[ID_COL, POSITION_COL, BPR_COL] + SKILL_COLS).copy()

    for col in SKILL_COLS:
        df[col] = df[col].clip(0, 100)

    df["bpr_weight"] = df[BPR_COL].apply(bpr_to_weight)

    return df.reset_index(drop=True)


# ============================================================
# DATA LOADING
# ============================================================

def load_selected_roster(
    db_path: Path,
    table_name: str,
    selected_allyears_pids: list[str],
) -> pd.DataFrame:
    if not selected_allyears_pids:
        return pd.DataFrame(columns=[ID_COL, NAME_COL, POSITION_COL, BPR_COL] + SKILL_COLS)

    con = duckdb.connect(str(db_path))
    placeholders = ", ".join(["?"] * len(selected_allyears_pids))

    query = f"""
        SELECT
            {ID_COL},
            {NAME_COL},
            {POSITION_COL},
            {BPR_COL},
            {", ".join(SKILL_COLS)}
        FROM {table_name}
        WHERE CAST({ID_COL} AS VARCHAR) IN ({placeholders})
    """

    roster = con.execute(query, [str(x) for x in selected_allyears_pids]).fetchdf()
    con.close()

    return clean_player_df(roster)


def load_candidate_pool(
    db_path: Path,
    table_name: str,
    selected_allyears_pids: list[str],
    year: int | None = None,
) -> pd.DataFrame:
    con = duckdb.connect(str(db_path))

    where_clauses = []
    params = []

    if selected_allyears_pids:
        placeholders = ", ".join(["?"] * len(selected_allyears_pids))
        where_clauses.append(f"CAST({ID_COL} AS VARCHAR) NOT IN ({placeholders})")
        params.extend([str(x) for x in selected_allyears_pids])

    if year is not None:
        where_clauses.append(f"{YEAR_COL} = ?")
        params.append(year)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    query = f"""
        SELECT
            {ID_COL},
            {NAME_COL},
            {POSITION_COL},
            {BPR_COL},
            {", ".join(SKILL_COLS)},
            {YEAR_COL}
        FROM {table_name}
        {where_sql}
    """

    candidates = con.execute(query, params).fetchdf()
    con.close()

    return clean_player_df(candidates)


# ============================================================
# ROSTER STATE
# ============================================================

def get_position_counts(roster: pd.DataFrame) -> dict[str, int]:
    counts = roster[POSITION_COL].value_counts().to_dict() if not roster.empty else {}
    return {
        "G": int(counts.get("G", 0)),
        "F": int(counts.get("F", 0)),
        "C": int(counts.get("C", 0)),
    }


def get_open_slots(roster: pd.DataFrame, target_counts: dict[str, int]) -> dict[str, int]:
    current_counts = get_position_counts(roster)

    open_slots = {
        pos: int(target_counts[pos] - current_counts[pos])
        for pos in ["G", "F", "C"]
    }

    if any(v < 0 for v in open_slots.values()):
        raise ValueError(
            f"Current roster exceeds target positional counts. "
            f"Current={current_counts}, Target={target_counts}"
        )

    if len(roster) > 15:
        raise ValueError("Current roster has more than 15 players.")

    if sum(target_counts.values()) > 15:
        raise ValueError("Target roster counts exceed 15 players.")

    return open_slots


def calculate_weighted_team_ratings(roster: pd.DataFrame) -> dict[str, float]:
    if roster.empty:
        return {skill: np.nan for skill in SKILL_COLS}

    weights = roster["bpr_weight"].to_numpy(dtype=float)
    total_weight = weights.sum()

    if total_weight <= 0:
        return {skill: float(roster[skill].mean()) for skill in SKILL_COLS}

    ratings = {}
    for skill in SKILL_COLS:
        values = roster[skill].to_numpy(dtype=float)
        ratings[skill] = float(np.sum(values * weights) / total_weight)

    return ratings


def calculate_total_team_rating(roster: pd.DataFrame) -> float:
    ratings = calculate_weighted_team_ratings(roster)
    return float(np.nansum(list(ratings.values())))


def calculate_weakest_team_rating(roster: pd.DataFrame) -> float:
    ratings = calculate_weighted_team_ratings(roster)
    return float(np.nanmin(list(ratings.values())))


# ============================================================
# OPTIMIZER
# ============================================================

def optimize_roster_additions(
    current_roster: pd.DataFrame,
    candidates: pd.DataFrame,
    target_counts: dict[str, int],
    top_n_candidates_per_position: int | None = 200,
    tolerance: float = 1e-6,
) -> tuple[pd.DataFrame, dict]:
    """
    Select candidates to fill open G/F/C slots.

    Objective order must remain:
      1. maximize total final team rating across 5 categories
      2. maximize weakest final team category
      3. maximize total projected BPR
    """

    open_slots = get_open_slots(current_roster, target_counts)
    total_to_add = sum(open_slots.values())

    if total_to_add == 0:
        return pd.DataFrame(), {
            "message": "Roster already matches target counts.",
            "open_slots": open_slots,
        }

    if len(current_roster) + total_to_add > 15:
        raise ValueError("Adding required players would exceed 15-player roster limit.")

    candidates = candidates.copy()

    needed_positions = [pos for pos, n_needed in open_slots.items() if n_needed > 0]
    candidates = candidates[candidates[POSITION_COL].isin(needed_positions)].copy()

    if candidates.empty:
        raise ValueError("No candidates available for needed positions.")

    # Candidate weighted total skill implements BPR-adjusted percentile impact.
    candidates["candidate_raw_skill_sum"] = candidates[SKILL_COLS].sum(axis=1)
    candidates["candidate_weighted_total_skill"] = (
        candidates["bpr_weight"] * candidates["candidate_raw_skill_sum"]
    )

    # Optional speed filter to keep MILP size manageable.
    if top_n_candidates_per_position is not None:
        candidates = (
            candidates.sort_values(
                ["candidate_weighted_total_skill", BPR_COL],
                ascending=[False, False],
            )
            .groupby(POSITION_COL, group_keys=False)
            .head(top_n_candidates_per_position)
            .reset_index(drop=True)
        )

    available_counts = candidates[POSITION_COL].value_counts().to_dict()
    for pos, needed in open_slots.items():
        available = int(available_counts.get(pos, 0))
        if available < needed:
            raise ValueError(
                f"Not enough available {pos} candidates. Needed={needed}, Available={available}"
            )

    n = len(candidates)

    candidate_skill_matrix = candidates[SKILL_COLS].to_numpy(dtype=float)
    candidate_weights = candidates["bpr_weight"].to_numpy(dtype=float)
    candidate_weighted_skill_matrix = candidate_skill_matrix * candidate_weights.reshape(-1, 1)
    candidate_weighted_total_skill = candidates["candidate_weighted_total_skill"].to_numpy(dtype=float)
    candidate_bpr = candidates[BPR_COL].to_numpy(dtype=float)

    # Shared binary variable constraints: x_i in {0,1}
    bounds = Bounds(0, 1)
    integrality = np.ones(n)

    constraints = []

    # Exact positional fill constraints.
    for pos in ["G", "F", "C"]:
        row = (candidates[POSITION_COL].to_numpy() == pos).astype(float).reshape(1, -1)
        constraints.append(LinearConstraint(row, lb=open_slots[pos], ub=open_slots[pos]))

    # ============================================================
    # STAGE 1: Maximize total final team rating across 5 categories
    # Practical linear objective: maximize BPR-weighted candidate skill contribution.
    # ============================================================

    result_1 = milp(
        c=-candidate_weighted_total_skill,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
    )

    if not result_1.success:
        raise RuntimeError(f"Primary optimization failed: {result_1.message}")

    best_primary_value = -float(result_1.fun)

    constraints_stage_2 = constraints + [
        LinearConstraint(
            candidate_weighted_total_skill.reshape(1, -1),
            lb=best_primary_value - tolerance,
            ub=np.inf,
        )
    ]

    # ============================================================
    # STAGE 2: Maximize weakest final team category
    # Uses weighted selected category contribution as the category value proxy.
    # Exact final ratings are calculated after selection for reporting.
    # ============================================================

    # Variables are x_0...x_n-1 and z, where z is the weakest category contribution.
    c_stage_2 = np.zeros(n + 1)
    c_stage_2[-1] = -1  # maximize z

    bounds_stage_2 = Bounds(
        lb=np.concatenate([np.zeros(n), [0]]),
        ub=np.concatenate([np.ones(n), [np.inf]]),
    )

    integrality_stage_2 = np.concatenate([np.ones(n), [0]])

    constraints_2 = []

    # Extend existing x-only constraints with zero coefficient for z.
    for con in constraints_stage_2:
        A_old = con.A
        A_new = np.hstack([A_old, np.zeros((A_old.shape[0], 1))])
        constraints_2.append(LinearConstraint(A_new, lb=con.lb, ub=con.ub))

    # z <= sum(weighted_skill_i_s * x_i) for each skill s
    for skill_idx, skill in enumerate(SKILL_COLS):
        A = np.zeros((1, n + 1))
        A[0, :n] = -candidate_weighted_skill_matrix[:, skill_idx]
        A[0, -1] = 1
        constraints_2.append(LinearConstraint(A, lb=-np.inf, ub=0))

    result_2 = milp(
        c=c_stage_2,
        integrality=integrality_stage_2,
        bounds=bounds_stage_2,
        constraints=constraints_2,
    )

    if not result_2.success:
        raise RuntimeError(f"Weakest-category optimization failed: {result_2.message}")

    best_weakest_value = float(result_2.x[-1])

    # Add constraints so stage 3 must preserve best weakest-category proxy.
    constraints_stage_3 = constraints_stage_2.copy()
    for skill_idx, skill in enumerate(SKILL_COLS):
        row = candidate_weighted_skill_matrix[:, skill_idx].reshape(1, -1)
        constraints_stage_3.append(
            LinearConstraint(row, lb=best_weakest_value - tolerance, ub=np.inf)
        )

    # ============================================================
    # STAGE 3: Maximize total projected BPR
    # ============================================================

    result_3 = milp(
        c=-candidate_bpr,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints_stage_3,
    )

    if not result_3.success:
        raise RuntimeError(f"BPR tie-break optimization failed: {result_3.message}")

    selected_mask = np.round(result_3.x).astype(bool)
    selected = candidates.loc[selected_mask].copy()

    final_roster = pd.concat([current_roster, selected], ignore_index=True)

    summary = {
        "open_slots": open_slots,
        "current_size": int(len(current_roster)),
        "added_size": int(len(selected)),
        "final_size": int(len(final_roster)),
        "current_position_counts": get_position_counts(current_roster),
        "final_position_counts": get_position_counts(final_roster),
        "current_ratings": calculate_weighted_team_ratings(current_roster),
        "final_ratings": calculate_weighted_team_ratings(final_roster),
        "current_total_rating": calculate_total_team_rating(current_roster),
        "final_total_rating": calculate_total_team_rating(final_roster),
        "current_weakest_rating": calculate_weakest_team_rating(current_roster),
        "final_weakest_rating": calculate_weakest_team_rating(final_roster),
        "added_projected_bpr": float(selected[BPR_COL].sum()),
        "primary_objective_value": float(best_primary_value),
        "weakest_category_proxy_value": float(best_weakest_value),
    }

    return selected, summary


# ============================================================
# BACKEND ENTRY POINT
# ============================================================

def recommend_players_for_user_roster(
    selected_allyears_pids: list[str],
    target_guard_count: int = 5,
    target_forward_count: int = 6,
    target_center_count: int = 4,
    year: int | None = 2026,
) -> dict:
    target_counts = {
        "G": int(target_guard_count),
        "F": int(target_forward_count),
        "C": int(target_center_count),
    }

    if sum(target_counts.values()) > 15:
        raise ValueError("Target roster cannot exceed 15 players.")

    current_roster = load_selected_roster(
        db_path=DB_PATH,
        table_name=CURRENT_ROSTER_TABLE,
        selected_allyears_pids=selected_allyears_pids,
    )

    candidates = load_candidate_pool(
        db_path=DB_PATH,
        table_name=CANDIDATE_TABLE,
        selected_allyears_pids=selected_allyears_pids,
        year=year,
    )

    selected_additions, summary = optimize_roster_additions(
        current_roster=current_roster,
        candidates=candidates,
        target_counts=target_counts,
    )

    output_cols = [ID_COL, NAME_COL, POSITION_COL, BPR_COL, "bpr_weight"] + SKILL_COLS

    return {
        "recommended_players": selected_additions[output_cols].to_dict(orient="records"),
        "summary": summary,
    }
```

---

## Frontend request shape

The frontend should send something like:

```json
{
  "selected_allyears_pids": ["12345", "67890", "24680"],
  "target_guard_count": 5,
  "target_forward_count": 6,
  "target_center_count": 4,
  "year": 2026
}
```

The backend returns:

```json
{
  "recommended_players": [
    {
      "allyears_pid": "13579",
      "player_name": "Example Player",
      "position_group": "G",
      "projected_bpr": 5.2,
      "bpr_weight": 7.2,
      "scoring_percentile": 81,
      "spacing_percentile": 88,
      "playmaking_percentile": 77,
      "rebounding_percentile": 42,
      "defense_percentile": 66
    }
  ],
  "summary": {
    "open_slots": {"G": 2, "F": 1, "C": 1},
    "current_ratings": {},
    "final_ratings": {},
    "current_total_rating": 0,
    "final_total_rating": 0,
    "current_weakest_rating": 0,
    "final_weakest_rating": 0,
    "added_projected_bpr": 0
  }
}
```

---

## Display recommendations on the website

For each recommended player, show:

```text
Player name
Position group
Projected BPR
Five category percentiles
```

Also show before/after team ratings:

```text
Scoring:      current -> final
Spacing:      current -> final
Playmaking:   current -> final
Rebounding:   current -> final
Defense:      current -> final
```

And summary values:

```text
Total team rating: current -> final
Weakest category: current -> final
Total projected BPR added
```

A radar chart can be used as a visual layer, but the actual optimizer should remain the three-step objective above.

---

## Critical implementation notes

1. Use `allyears_pid` everywhere as the unique player identifier.
2. Keep the objective order exactly:
   - maximize total final team rating across the 5 categories
   - maximize the weakest category
   - maximize total projected BPR
3. Include BPR-adjusted percentile impact so high-BPR players affect team ratings more.
4. Do not use random skill/BPR scalar weights.
5. Do not use 247 IDs, names, or URLs as player identifiers.
6. Keep position constraints exact based on target G/F/C counts.
7. Enforce max roster size of 15.
8. Start with five categories only: scoring, spacing, playmaking, rebounding, defense.
9. Compute final reported team ratings using weighted averages, not just raw candidate objective values.
10. Later improvements may add archetype constraints, NIL budget, or projected minutes, but do not change the current objective for the first implementation.
