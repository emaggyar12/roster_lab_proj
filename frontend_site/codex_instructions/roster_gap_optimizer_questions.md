# Roster Gap Optimizer Clarification Questions

Please answer inline under each question. These are the decisions I need clarified before implementation so I do not guess at data sources or behavior.

## 1. Optimizer Scope

Should the first implementation optimize over:

```text
A. Transfers only
B. High-school recruits only
C. Transfers + high-school recruits
D. Transfers + high-school recruits + returning players
```

Answer: C, the optimizer is recommending new additions to the roster as the current players are set in stone.


## 2. Current Roster Source

What should count as the user's current selected roster?

For example:

```text
A. Returning players only
B. Manually selected players from all site players
C. Existing team roster from the team page plus user additions/removals
D. Something else
```

Answer: C. Existing team roster from the team page plus user additions/removals

The optimizer’s current roster is the roster state loaded from the Roster Management page after user edits.


## 3. Candidate Pool Source

Which generated frontend data files should feed optimizer candidates?

Current likely options:

```text
frontend_site/data/transferPlayers.ts
frontend_site/data/hsRecruits.ts
frontend_site/data/returningPlayers.ts
frontend_site/data/players.ts
```

Answer: 
frontend_site/data/transferPlayers.ts
frontend_site/data/hsRecruits.ts

should feed optimizer candidates


## 4. Unique ID for High-School Recruits

The spec requires `allyears_pid` everywhere, but many 2026 high-school recruits do not have a BartTorvik `allyears_pid` yet.

How should HS recruits be handled?

```text
A. Exclude HS recruits that do not have `allyears_pid`
B. Use `hs_player_key` only for HS recruits despite the spec
C. Create a separate optimizer-safe ID field that can represent both BV and HS IDs
D. Something else
```

Answer:
Use C. Create a separate optimizer-safe ID field that can represent both BV and HS IDs.

The optimizer should use a universal ID field called:

optimizer_player_id

For high-school recruits, generate it as:

optimizer_player_id = "hs:" + player_key

Keep allyears_pid as a separate optional field when available, but do not require allyears_pid for HS recruits. HS recruits should not be excluded just because they do not have a BartTorvik allyears_pid.

For high-school recruits, the generated frontend/player object should follow this structure:

{
  optimizer_player_id: "hs:<player_key>",
  allyears_pid: null, // or existing value if available
  source_type: "hs_recruit",

  player_key: "<player_key>",
  name: "<full_name>",
  position_group: "G" | "F" | "C",

  projected_bpr: <freshman_prior_or_model_value>,

  spacing_percentile: <historical_freshman_prior>,
  facilitating_percentile: <historical_freshman_prior>,
  rim_protection_percentile: <historical_freshman_prior>,
  defense_percentile: <historical_freshman_prior>,
  finishing_percentile: <historical_freshman_prior>,

  percentile_projection_source: "historical_freshman_prior",
  prior_source: "position_group_plus_rating_tier" // or fallback source
}

The HS percentile values should come from the freshman-prior method:

Historical rows:
- hs_year != 2026

Current HS rows:
- hs_year/year = 2026

Projection method:
1. Bucket historical players by position_group + rating tier within recruiting class.
2. Compute median college outcome percentiles for each bucket.
3. Assign those median percentiles to 2026 HS recruits.
4. If the exact bucket is too small or missing, fallback in this order:
   - position_group only
   - rating_tier only
   - overall historical median

Final implementation rule:

Use optimizer_player_id as the universal optimizer key.
Use allyears_pid where available, but never require it for HS recruits.
Use freshman-prior projected percentiles for HS recruits.
Do not exclude HS recruits only because they lack allyears_pid.


## 5. Transfer ID Field

For transfers, should `allyears_pid` map to:

```text
A. `transfer_barttorvik_trid`
B. `returning_bvt_pid` / BartTorvik pid where available
C. A new explicit `allyears_pid` field added to generated frontend player objects
D. Something else
```

Answer:
Use A/C combined:

allyears_pid = transfer_barttorvik_trid

This is a hard rule. For transfers, transfer_barttorvik_trid and allyears_pid should be treated as the same stable player identifier.

During frontend data generation, normalize the transfer ID field like this:

allyears_pid = transfer_barttorvik_trid
optimizer_player_id = "transfer:" + transfer_barttorvik_trid

The generated transfer object should expose both the normalized universal optimizer ID and the normalized allyears_pid:

{
  optimizer_player_id: "transfer:<transfer_barttorvik_trid>",
  allyears_pid: "<transfer_barttorvik_trid>",
  transfer_barttorvik_trid: "<transfer_barttorvik_trid>",

  source_type: "transfer",
  name: "<player_name>",
  position_group: "G" | "F" | "C",

  projected_bpr: <projected_bpr>,

  spacing_percentile: <spacing_percentile>,
  facilitating_percentile: <facilitating_percentile>,
  rim_protection_percentile: <rim_protection_percentile>,
  defense_percentile: <defense_percentile>,
  finishing_percentile: <finishing_percentile>
}

The optimizer should use:

optimizer_player_id

as the universal frontend key across all player types.

For transfers specifically:

optimizer_player_id = "transfer:" + allyears_pid
optimizer_player_id = "transfer:" + transfer_barttorvik_trid

These are equivalent because:

allyears_pid = transfer_barttorvik_trid

Final implementation rule:

For transfers, allyears_pid and transfer_barttorvik_trid are the same identifier.
Always set allyears_pid = transfer_barttorvik_trid.
Use optimizer_player_id = "transfer:" + allyears_pid as the optimizer key.


## 6. Position Group Mapping

How should site positions map to optimizer position groups?

Proposed default:

```text
PG, SG, CG -> G
SF, PF, Wing F, Stretch 4 -> F
C, PF/C -> C
N/A -> exclude from optimizer
```

Answer:
Use the proposed mapping, with a few explicit additions for consistency.

The optimizer should only use three position groups:

G
F
C

Map site positions to optimizer position groups as follows:

PG, SG, CG, G, Combo Guard -> G

SF, PF, F, Wing, Wing F, Stretch 4, Forward -> F

C, Center, PF/C, C/PF, F/C, FC -> C

N/A, unknown, missing, null -> exclude from optimizer

For the first implementation, treat combo frontcourt labels like PF/C, C/PF, and F/C as C.

Reason: center is the scarcer roster slot, and this avoids ambiguous dual-position handling in the first version.

The generated player object should include a normalized field:

position_group: "G" | "F" | "C"

The optimizer should rely only on position_group, not raw position strings.

Final implementation rule:

Normalize every player into one position_group before optimization.
Use G/F/C only.
Treat PF/C, C/PF, and F/C as C in version one.
Exclude players with missing or unknown position_group from optimizer candidates.


## 7. Skill Percentile Columns

The spec requires:

```text
scoring_percentile
spacing_percentile
playmaking_percentile
rebounding_percentile
defense_percentile
```

The current frontend transfer/returning data visibly has:

```text
skill_spacing_percentile
skill_facilitating_percentile
skill_rim_protection_percentile
skill_defense_percentile
skill_finishing_percentile
```

How should these map?

Proposed possible mapping:

```text
spacing_percentile    <- skill_spacing_percentile
playmaking_percentile <- skill_facilitating_percentile
defense_percentile    <- skill_defense_percentile
rebounding_percentile <- needs a confirmed source
scoring_percentile    <- needs a confirmed source, maybe skill_finishing_percentile is not enough
```

Answer:
Do not use the old five names from the spec. For the first implementation, the optimizer should use the five skill columns we actually have and are actively generating:

spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile

These are the five optimizer ratings.

For frontend data that currently prefixes these with skill_, normalize them during data preparation:

spacing_percentile        = skill_spacing_percentile
facilitating_percentile   = skill_facilitating_percentile
rim_protection_percentile = skill_rim_protection_percentile
defense_percentile        = skill_defense_percentile
finishing_percentile      = skill_finishing_percentile

Do not create scoring_percentile, playmaking_percentile, or rebounding_percentile for version one unless those fields already exist cleanly. The current five-category system should remain consistent across transfers, returning players, and HS recruits.

The optimizer’s five-category objective should therefore be:

maximize final team:
- spacing_percentile
- facilitating_percentile
- rim_protection_percentile
- defense_percentile
- finishing_percentile

For display labels, the UI can use cleaner names:

{
  spacing_percentile: "Spacing",
  facilitating_percentile: "Facilitating",
  rim_protection_percentile: "Rim Protection",
  defense_percentile: "Defense",
  finishing_percentile: "Finishing"
}

For high-school recruits, the projected percentile script should output the same normalized five columns:

spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile

For transfers and returning players, generated frontend objects should also expose those same normalized names, even if the original source fields are prefixed with skill_.

Final implementation rule:

Use the five normalized optimizer skill columns:
spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile

Do not use scoring/playmaking/rebounding names in version one.
Normalize any skill_* frontend fields into these five names before running the optimizer.

## 8. Missing Skill Percentiles

What should happen when a player is missing one or more required skill percentile values?

```text
A. Exclude that player from optimizer candidates
B. Impute missing values as 50
C. Impute from position-group average
D. Display as unavailable but still allow selection somehow
```

Answer: A, exclude the player from recommended players.


## 9. Current Team Ratings

Should current team ratings be calculated from only the user-selected roster, or from the whole team roster currently shown on the site before user edits?

Answer:
Current team ratings should be calculated from the active roster management roster state, not from the untouched original team roster.

Current team ratings on the Optimizer page are calculated from the roster loaded into the Optimizer from the Roster Management page.

The active roster management roster is:

active_ros_manage_roster =
    default team roster currently shown on the site
  - players removed by the user
  + transfers added by the user
  + high-school recruits added by the user

The optimizer should treat this active roster manag roster as the source of truth for:

- current G/F/C position counts
- open roster slots
- current five-category team ratings
- before/after comparison
- BPR-weighted percentile calculations

However, current team ratings should not be calculated or displayed unless the active roster manage roster has 15 or fewer players.

Hard UI rule:

if active_ros_manage_roster.length > 15:
    do not calculate team ratings
    do not show active team rating overlay
    do not allow optimizer to run

Instead, show a clear red/error UI state telling the user they must reduce the roster size:

Roster size exceeds 15 players.
Remove at least X player(s) to view team ratings or run the optimizer.

Where:

X = active_ros_manage_roster.length - 15

Recommended UX behavior when roster size is over 15:

- Show roster count in red when over 15.
- Disable the active team rating calculation.
- Disable the optimizer button.
- Show a red warning banner near the roster controls.
- Show the current count clearly, e.g. "17 / 15 players".
- Keep the original baseline team shape visible in gray.
- Hide or disable the edited overlay until the roster is back to 15 or fewer players.

Example UI copy:

Too many players selected

Your roster currently has 17 players. Team ratings and optimizer recommendations are only available for rosters of 15 or fewer players.

Remove 2 player(s) to calculate team ratings and run the optimizer.
Radar / Pentagon Visualization Requirements

The radar chart should always preserve the original baseline team shape from before any user edits.

Baseline state

Before the user makes any edits:

- Show the original/default team roster pentagon in gray.
- This gray pentagon represents the baseline roster state.
After user edits

Once the user adds or removes players:

- Keep the original pentagon visible in faint gray.
- Overlay the new edited roster pentagon on top of it.
- The old gray pentagon should remain as the comparison baseline.
- The new pentagon should represent the active edited roster management roster.
Color behavior for changes

For each skill vertex:

- If the edited roster value is higher than the original baseline value, that outward change should be shown in green.
- If the edited roster value is lower than the original baseline value, that inward change should be shown in red.
- If unchanged, it can remain neutral or use the default edited overlay color.

Recommended interpretation:

Outward movement from baseline = green
Inward movement from baseline = red
Baseline/original shape = faint gray
Visual requirements
- The original pentagon should be faint gray and remain visible at all times after edits.
- The edited pentagon should be overlaid against the old one.
- The baseline should be visually de-emphasized but still easy to compare against.
- The chart should include a small legend.

Recommended legend:

Gray   = Original roster
Green  = Improvement vs original roster
Red    = Decline vs original roster

If needed, the edited polygon can use segmented edge/fill styling so that skill directions that improved appear green and those that declined appear red.

Skill columns used for team ratings

Use the five normalized optimizer skill columns:

spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile
Re-enable behavior

When the roster returns to 15 or fewer players:

- Recalculate current team ratings.
- Re-enable the edited radar/team rating overlay.
- Re-enable the optimizer if all other required fields are present.
- Keep the original baseline gray pentagon as the permanent comparison layer.

Final implementation rule:

Current team ratings = ratings from active roster management roster after all user additions/removals.

Do not calculate or display edited current team ratings if active_ros_manage_roster.length > 15.

Do not allow optimizer to run if active_ros_manage_roster.length > 15.

Always preserve the original pre-edit team pentagon in faint gray.

After edits, overlay the edited pentagon against the original:
- inward changes = red
- outward changes = green

Include a small legend explaining gray/original, green/improvement, and red/decline.


## 10. Exact vs Practical Objective

The spec allows the practical MILP proxy:

```text
maximize sum(candidate_bpr_weight * candidate_total_skill)
```

Then report exact final weighted averages afterward.

Should the first implementation use this practical proxy exactly as written, or should it attempt exact final weighted-average optimization?

Answer:
Use a BPR-weighted contribution objective, but do not force BPR weights to be positive.

The optimizer must preserve the agreed objective order:

Primary objective:
maximize total final team rating across the 5 categories

Secondary tie-breaker:
maximize the weakest category

Final tie-breaker:
maximize total projected BPR

The five optimizer skill columns are:

spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile

For each player and each skill, their contribution should be:

skill_contribution = projected_bpr * skill_percentile

This means positive-BPR players increase the team rating according to their skill percentiles, while negative-BPR players decrease the team rating. Do not shift BPR upward and do not clamp BPR to a positive weight.

The team skill rating should be calculated as:

team_skill_rating =
    sum(projected_bpr * skill_percentile)
    /
    sum(abs(projected_bpr))

Use sum(abs(projected_bpr)) in the denominator so the rating remains stable even when some players have negative BPR. Do not use sum(projected_bpr) as the denominator because that can become near-zero or negative and produce unstable ratings.

The primary optimization objective should use candidate BPR-weighted total skill contribution:

candidate_total_contribution =
    projected_bpr * (
        spacing_percentile
      + facilitating_percentile
      + rim_protection_percentile
      + defense_percentile
      + finishing_percentile
    )

Primary MILP objective:

maximize sum(candidate_total_contribution)

After the optimizer selects players, calculate and display the exact before/after team ratings using:

team_skill_rating =
    sum(projected_bpr * skill_percentile)
    /
    sum(abs(projected_bpr))
Secondary tie-breaker

The secondary objective should maximize the weakest final team category:

weakest_category =
    min(
        final_spacing_rating,
        final_facilitating_rating,
        final_rim_protection_rating,
        final_defense_rating,
        final_finishing_rating
    )

Where each final rating uses the same BPR-weighted formula:

final_skill_rating =
    sum(projected_bpr * skill_percentile)
    /
    sum(abs(projected_bpr))
Final tie-breaker

If multiple candidate groups are equivalent or nearly equivalent after the first two objectives, prefer the group with the highest total projected BPR:

maximize sum(projected_bpr)
UI note

Because negative-BPR players can reduce team ratings, a final team category may theoretically fall below 0. The numeric value should be preserved for calculations. For radar visualization, the chart may clamp visual values to the display range while still showing the true numeric rating elsewhere.

Final implementation rule
Do not use positive-only BPR weights.

Do not use:
candidate_bpr_weight = max(projected_bpr + 2.0, 0.5)

Use:
skill_contribution = projected_bpr * skill_percentile

Calculate team ratings as:
sum(projected_bpr * skill_percentile) / sum(abs(projected_bpr))

Primary:
maximize total BPR-weighted skill contribution across the five categories.

Secondary:
maximize weakest final team category.

Final:
maximize total projected BPR.


## 11. Candidate Limits

Should we cap candidates per position for speed, as the skeleton suggests?

Default in spec:

```text
top_n_candidates_per_position = 200
```

Answer:
Yes, use a candidate cap for version one.

Use:

top_n_candidates_per_position = 200

This cap should be applied after filtering candidates for optimizer eligibility and position need.

The optimizer candidate filtering order should be:

1. Combine transfers + HS recruits.
2. Remove already-selected players.
3. Remove players missing required optimizer fields.
4. Normalize position_group into G/F/C.
5. Keep only candidates whose position_group is needed based on open slots.
6. Within each needed position_group, keep the top 200 candidates.

The per-position cap should be ranked by the same general value signal used by the optimizer:

candidate_total_contribution =
    projected_bpr * (
        spacing_percentile
      + facilitating_percentile
      + rim_protection_percentile
      + defense_percentile
      + finishing_percentile
    )

Sort descending by candidate_total_contribution within each position group, then keep the top 200.

If candidate_total_contribution ties, use projected BPR as the tie-breaker:

sort by:
1. candidate_total_contribution descending
2. projected_bpr descending

Reasoning:

The optimizer does not need to search thousands of low-value candidates in version one.
A top-200-per-position cap keeps the optimization fast while preserving a large enough candidate pool for realistic recommendations.

If fewer than 200 candidates exist for a needed position, use all eligible candidates for that position.

If a needed position has fewer eligible candidates than open slots, the optimizer should fail gracefully and display a clear message:

Not enough eligible candidates available for [position_group].
Needed: X
Available: Y

The cap should be configurable, not hardcoded deep inside the optimizer:

const TOP_N_CANDIDATES_PER_POSITION = 200;

or in Python:

TOP_N_CANDIDATES_PER_POSITION = 200

Final implementation rule:

Use top_n_candidates_per_position = 200 for version one.

Apply the cap after eligibility filtering and position-need filtering.

Rank candidates within each position group by:
1. projected_bpr * sum(five skill percentiles)
2. projected_bpr

Keep all candidates if fewer than 200 are available for that position.

Show a clear error if there are not enough eligible candidates to fill required open slots.


## 12. User Interface Location

Where should this optimizer live in the frontend?

Current likely options:

```text
A. Existing Simulator page
B. Team detail page
C. New optimizer page
D. Existing Portal page
```

Answer: C, new optimizer page.


Answer: It seems as though we are going to have to make a new page called "Optimizer." Rename "Simulator" to "Roster Management" , change its logo to a clipboard or something like that (clean logo please) and then make the new "Optimizer" tab right under it with some sciency logo (also neat and clean). Basically, i want you to include a button on the roster management page that says "Load to Optimizer" When they click this button, their "current roster" including whatever transfer changes they made will be loaded into the optimizer. From there, you will take this updated roster as the set in stone current roster for the team (though it may include added transfers or hs recrutits from the roster management page). 

Another thing I want on the optimizer page is a small basketball court visual. Make this visual very clean (its kind of like those overhead visuals you see of a half court with players at each position)

Anyway, what im getting is at, when you make their final optimized roster I want you to place the optimized people (by their pfp) on the court in the 1-5 spots (make 1 and 2 the top 2 guards), make (3 and 4 the top Fs), and make 5 the top C. Put the rest of the 10 under the court visual with their PFPs. Try to fit the player name and headshot on the court in their labelled position.

I want a toggle included that says "full roster optimization" or "single player optimization" that the user can toggle. If the user toggles to single player the court disappears and then the single player optimization shows up, which is just another scroll down pane with various filters. The single page optimization results are discussed in question 20.


## 13. Backend vs Frontend Execution

Should the optimizer run:

```text
A. Fully in frontend TypeScript over generated static player data
B. In a Python backend/API using DuckDB/SciPy as in the spec
C. As a precomputed script output loaded by frontend
```

Answer:
Use A. Fully in frontend TypeScript over generated static player data, but use a real frontend optimization package rather than simple top-N combination search.

Specifically, use:

glpk.js

This allows the optimizer to run fully in the browser/frontend while still using an actual mixed-integer linear programming solver.

Do not use a Python backend, DuckDB server, SciPy API, or serverless Python function for the first implementation.

The site should remain deployable on Vercel with no backend setup beyond normal frontend dependencies.

Package Choice

Install:

npm install glpk.js

Use glpk.js in the frontend optimizer code.

Reason:

glpk.js is a JavaScript/WebAssembly optimization solver that can run in browser/frontend code.
It supports LP/MILP-style models.
It avoids requiring Python/SciPy/serverless backend infrastructure.
It is better suited to this project than a hand-written top-30 candidate search.
Runtime Architecture

Use:

Frontend TypeScript
+
glpk.js
+
generated static player data

The frontend should load generated static data files:

frontend_site/data/transferPlayers.ts
frontend_site/data/hsRecruits.ts
frontend_site/data/returningPlayers.ts

Candidate pool:

transferPlayers + hsRecruits

Current roster context:

active simulator roster =
    default team roster
  - user removals
  + user additions

The optimizer should run fully in the frontend.

Do not use:

Python backend/API using DuckDB/SciPy

for the first implementation.

Reason:

Using Python/SciPy requires backend deployment, API routes, serverless/runtime packaging, and likely extra deployment/debugging work.

The first version should work entirely inside the deployed frontend app.

Python/DuckDB scripts are still allowed upstream for data generation:

- calculate player percentiles
- project HS recruit percentiles
- normalize IDs
- generate frontend .ts data files

But live user optimization should happen in the frontend.

Why Not Simple Top-30 Filtering

Do not solve this by filtering to the top 30 candidates per position.

That would weaken the product.

The website is supposed to help the user find “diamonds in the rough,” meaning lower-BPR or less obvious players who may fit the current roster.

Therefore:

Do not blindly filter to only the top 30 candidates by projected BPR.
Do not blindly filter to only the top 30 candidates by projected_bpr * skill_sum.

The optimizer should be able to consider the full eligible candidate pool, or at least a much broader pool, using an actual frontend solver.

Optimizer Decision Variables

For each candidate player i, define a binary variable:

x_i = 1 if candidate i is selected
x_i = 0 if candidate i is not selected

The optimizer chooses which players to add.

Position Constraints

Given target counts:

target_G
target_F
target_C

And current active roster counts:

current_G
current_F
current_C

Calculate open slots:

G_needed = target_G - current_G
F_needed = target_F - current_F
C_needed = target_C - current_C

Then add constraints:

sum(x_i for candidates where position_group = "G") = G_needed
sum(x_i for candidates where position_group = "F") = F_needed
sum(x_i for candidates where position_group = "C") = C_needed

Also enforce:

active_roster.length <= 15
target_G + target_F + target_C <= 15

Do not allow optimizer to run if the active roster is already over 15 players.

Candidate Eligibility

Eligible candidates must have:

optimizer_player_id
source_type
position_group
projected_bpr
spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile

Candidate pool should include only:

transfers + high-school recruits

Exclude:

- players already selected on active roster
- players missing optimizer fields
- players with missing/invalid position_group
- returning players as recommendation candidates
Team Rating Formula

After selections are made, calculate exact team ratings using:

team_skill_rating =
    sum(projected_bpr * skill_percentile)
    /
    sum(abs(projected_bpr))

Use this for all five skills:

spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile

Do not force projected BPR to be positive.

Negative projected BPR should negatively affect the numerator.

Do not use:

max(projected_bpr + 2, 0.5)
Important Mathematical Note

glpk.js solves linear/integer optimization models.

The exact displayed team rating formula has a denominator:

sum(abs(projected_bpr))

That denominator can change depending on which players are selected.

Because of that, the exact team rating formula is not a simple linear MILP objective.

Therefore, implement the optimizer in two stages:

Stage 1:
Use glpk.js to solve one or more linearized roster-selection objectives over the full eligible candidate pool.

Stage 2:
Take the solver-produced candidate solutions, compute exact final team ratings, and rank those solutions using the final agreed objective order.

This keeps the model frontend-only while still using a real optimizer and avoiding naive top-30 filtering.

Primary Linear Solver Objective

For each player, define:

candidate_total_contribution =
    projected_bpr * (
        spacing_percentile
      + facilitating_percentile
      + rim_protection_percentile
      + defense_percentile
      + finishing_percentile
    )

Use this as the main GLPK objective:

maximize sum(candidate_total_contribution * x_i)

This is linear because each candidate contribution is precomputed.

Negative BPR should remain negative.

Additional Solver Objectives to Preserve Diamonds in the Rough

To avoid only finding obvious high-BPR players, run multiple GLPK solves with different linear objectives, then exact-rank the resulting solution sets.

Run at least these objective variants:

1. Total contribution objective
maximize projected_bpr * sum(five skill percentiles)
2. Spacing specialist objective
maximize projected_bpr * spacing_percentile
3. Facilitating specialist objective
maximize projected_bpr * facilitating_percentile
4. Rim protection specialist objective
maximize projected_bpr * rim_protection_percentile
5. Defense specialist objective
maximize projected_bpr * defense_percentile
6. Finishing specialist objective
maximize projected_bpr * finishing_percentile
7. Current-weakness objective

Find the weakest current roster category, then optimize that skill.

Example:

if current weakest category is spacing:
    maximize projected_bpr * spacing_percentile
8. Weakness-balanced objective

Give more linear objective value to categories where the current roster is weak.

Example:

skill_gap_weight =
    max(current_best_skill_rating - current_skill_rating, 0)

Then:

maximize sum(
    projected_bpr
    * skill_percentile
    * skill_gap_weight
)

This is still linear because skill_gap_weight is known before optimization.

Iterative Top-K Solutions

For each objective variant, do not only take one solution.

After GLPK returns a solution, add an exclusion constraint and solve again to get alternative valid solutions.

If the selected player IDs in solution k are:

S_k = selected players in previous solution

Add exclusion constraint:

sum(x_i for i in S_k) <= |S_k| - 1

Then solve again.

This prevents returning the same exact roster group repeatedly.

Recommended:

Get up to 10 solutions per objective variant.

If there are 8 objective variants, this gives up to about 80 candidate roster solutions.

Then deduplicate solution sets.

Final Exact Ranking

After collecting candidate solution sets from GLPK, calculate exact final roster ratings for each set using:

team_skill_rating =
    sum(projected_bpr * skill_percentile)
    /
    sum(abs(projected_bpr))

Then rank solution sets by the non-negotiable final objective order:

1. final_total_rating descending
2. final_weakest_rating descending
3. added_projected_bpr descending

Where:

final_total_rating =
    final_spacing_rating
  + final_facilitating_rating
  + final_rim_protection_rating
  + final_defense_rating
  + final_finishing_rating
final_weakest_rating =
    min(
      final_spacing_rating,
      final_facilitating_rating,
      final_rim_protection_rating,
      final_defense_rating,
      final_finishing_rating
    )
added_projected_bpr =
    sum(projected_bpr of selected additions)

Return the highest-ranked exact solution as the main recommendation.

Hidden-Fit Output

In addition to the main recommendation, return a section called:

Hidden Fits

Hidden fits should include players who:

- were selected in one of the alternate objective solutions
- are not among the highest projected-BPR players
- improved a weak category or appeared in a specialist/weakness objective solution

For each hidden-fit player, return:

name
position_group
source_type
projected_bpr
strongest skill percentile
which objective surfaced the player
estimated category improvement

This supports the GM-style use case.

Web Worker Requirement

Run glpk.js inside a Web Worker if possible.

Reason:

Optimization should not freeze the page.

Main frontend thread:

- sends active roster and candidate pool to worker
- shows "Optimizing roster..." loading state
- receives final recommendations

Worker:

- builds GLPK model
- solves objective variants
- exact-ranks returned solution sets
- sends results back
UX Requirements

While optimizing, show:

Optimizing roster fits...

Disable optimizer button while running.

If optimization takes more than a short moment, show a spinner/progress state.

If GLPK fails or no valid roster combination exists, show a clear error:

No valid recommendation found for the current roster constraints.

If the active roster has more than 15 players, do not run the optimizer:

Your roster currently has X players. Remove Y player(s) to run the optimizer.
Final Implementation Rule

Use:

Frontend TypeScript
+
glpk.js
+
Web Worker if possible

Do not use Python/SciPy/serverless for version one.

Do not use simple top-30 filtering.

Use GLPK over the eligible candidate pool with position constraints.

Run multiple linear objective variants to preserve both obvious top players and diamond-in-the-rough fits.

Then compute exact final team ratings and rank all candidate solutions by:

1. maximize total final team rating across the five categories
2. maximize weakest final category
3. maximize total added projected BPR

This gives the best combination of:

- good frontend-only deployment on Vercel
- real optimization logic
- better candidate coverage
- ability to surface hidden-fit players


## 14. Deployment Constraint

If using Python/SciPy/DuckDB backend, where will it run?

For example:

```text
local only, Streamlit, FastAPI, Next API route calling Python, serverless, etc.
```

Answer: N/A, we are going to do fully typescript frontend optimization as in question 13


## 15. Recommendation Output Size

Should the optimizer return exactly the full set needed to fill open slots, or also show alternate ranked candidates by position?

Answer:
The optimizer should return both:

1. Full recommended player sets that fill the current open roster slots
2. Individual ranked fit candidates by position

These are different outputs and should not be treated as the same thing.

Main Output: Recommended Player Sets

The primary optimizer output should be full roster-addition sets.

If the active roster needs:

G_needed = 2
F_needed = 1
C_needed = 1

then the main optimizer should return groups containing exactly:

2 guards
1 forward
1 center

Each recommended set should be scored by the agreed final objective order:

1. maximize total final team rating across the five categories
2. maximize weakest final category
3. maximize total added projected BPR

The main recommendation answers:

What group of players best completes this roster?

Recommended output:

type RecommendedSet = {
  selected_players: OptimizerPlayer[];
  final_ratings: TeamRatings;
  rating_changes: TeamRatings;
  final_total_rating: number;
  final_weakest_rating: number;
  added_projected_bpr: number;
  rank: number;
};

Return at least:

Top 1 main recommended set
Top 3 to 5 alternate recommended sets

The UI should show the best set first, then allow the user to inspect alternate valid sets.

Secondary Output: Individual Fit Recommendations

The optimizer should also return individual player fit rankings.

These should answer a different question:

If I added only this one player to the current roster, how much would he help?

For every eligible candidate player p, calculate:

one_player_roster = active_simulator_roster + [p]

Then calculate exact before/after ratings using:

team_skill_rating =
    sum(projected_bpr * skill_percentile)
    /
    sum(abs(projected_bpr))

Compute:

individual_total_gain =
    one_player_final_total_rating - current_total_rating

individual_weakest_gain =
    one_player_final_weakest_rating - current_weakest_rating

individual_added_bpr =
    projected_bpr

Rank individual candidates by:

1. individual_total_gain descending
2. individual_weakest_gain descending
3. projected_bpr descending

Return individual recommendations by position group:

Top individual guard fits
Top individual forward fits
Top individual center fits

Recommended output:

type IndividualFitRecommendation = {
  player: OptimizerPlayer;
  position_group: "G" | "F" | "C";

  final_ratings_if_added: TeamRatings;
  rating_changes_if_added: TeamRatings;

  individual_total_gain: number;
  individual_weakest_gain: number;
  projected_bpr: number;

  best_improved_category: string;
  best_improved_category_gain: number;
};

Return something like:

Top 10 individual fits per needed position group
Important Distinction

The full-set optimizer and the individual-fit rankings can disagree.

That is expected.

A player might be the best individual fit at guard, but not appear in the best full set because another guard pairs better with a forward/center combination.

The UI should make this distinction clear:

Recommended Set:
Best group of players to complete the roster.

Individual Fits:
Best single-player additions if evaluating one player at a time.
Hidden-Fit / Diamond-in-the-Rough Output

Also include a small section for hidden-fit players.

A hidden-fit player is someone who:

- is not one of the highest projected-BPR candidates
- but produces strong individual_total_gain or individual_weakest_gain

Recommended definition:

projected_bpr <= median projected_bpr for his position group
AND
individual_total_gain ranks in the top 20 for his position group

or:

projected_bpr <= median projected_bpr for his position group
AND
individual_weakest_gain ranks in the top 20 for his position group

Return:

Top 5 hidden fits overall
Top 5 hidden fits by position if available

This supports the GM-style use case.

Final Implementation Rule

The optimizer should return:

1. Best full roster-addition set
2. Top 3 to 5 alternate full roster-addition sets
3. Top 10 individual fit candidates per needed position group
4. Hidden-fit / diamond-in-the-rough candidates

The full-set recommendation is the primary optimizer answer.

The individual rankings are supporting analysis for users who want to evaluate one player at a time.


## 16. Excluding Already Selected Players

Should candidates be excluded only if their `allyears_pid` is already selected, or also if they match by name/team/source due to missing/inconsistent IDs?

Answer:
Candidates should be excluded primarily by the universal optimizer key:

optimizer_player_id

Do not rely only on allyears_pid, because high-school recruits may not have allyears_pid.

The exclusion logic should be:

1. Exclude candidate if candidate.optimizer_player_id is already in the active roster management roster.
2. For transfers, also exclude if candidate.allyears_pid matches an already-selected player's allyears_pid.
3. For HS recruits, exclude if candidate.player_key matches an already-selected HS recruit's player_key.
4. As a safety fallback, optionally exclude exact duplicate name + source_type matches.

The primary rule is:

optimizer_player_id is the unique key used by the optimizer.

For transfers:

allyears_pid = transfer_barttorvik_trid
optimizer_player_id = "transfer:" + allyears_pid

For HS recruits:

optimizer_player_id = "hs:" + player_key
allyears_pid = null or existing value if available
Recommended TypeScript exclusion logic
const selectedOptimizerIds = new Set(
  activeRoster.map((p) => p.optimizer_player_id).filter(Boolean)
);

const selectedAllyearsPids = new Set(
  activeRoster.map((p) => p.allyears_pid).filter(Boolean)
);

const selectedHsPlayerKeys = new Set(
  activeRoster
    .filter((p) => p.source_type === "hs_recruit")
    .map((p) => p.player_key)
    .filter(Boolean)
);

const eligibleCandidates = candidatePool.filter((candidate) => {
  if (selectedOptimizerIds.has(candidate.optimizer_player_id)) {
    return false;
  }

  if (
    candidate.allyears_pid != null &&
    selectedAllyearsPids.has(candidate.allyears_pid)
  ) {
    return false;
  }

  if (
    candidate.source_type === "hs_recruit" &&
    candidate.player_key != null &&
    selectedHsPlayerKeys.has(candidate.player_key)
  ) {
    return false;
  }

  return true;
});
Name-match fallback

Name matching should only be a fallback, not the main exclusion rule.

Reason:

Name matching can incorrectly remove different players with the same/similar name.

If used, keep it conservative:

Exclude by name only when:
- normalized full name matches exactly
- source_type matches exactly
- and no reliable ID is available

Do not exclude based on team/school alone.

Final implementation rule
Use optimizer_player_id as the main duplicate/exclusion key.

Also exclude transfers by matching allyears_pid, because allyears_pid = transfer_barttorvik_trid.

Also exclude HS recruits by matching player_key.

Use exact normalized name + source_type matching only as a fallback when no reliable ID exists.

Do not rely only on allyears_pid, because many HS recruits will not have it.


## 17. Year Filter

Should optimizer candidates be restricted to `year = 2026` only for the first implementation?

Answer:
Yes. For the first implementation, restrict optimizer candidates to the 2026 roster/recruiting cycle only.

The optimizer should only recommend players from:

year = 2026

or the equivalent generated frontend data representing the 2026 cycle.

This applies to both candidate sources:

transferPlayers.ts
hsRecruits.ts

The candidate pool should be:

2026 transfers + 2026 high-school recruits

Do not include players from prior years in the live optimizer candidate pool.

Transfer candidates

For transfers, only include players whose transfer/recruiting cycle corresponds to 2026.

Recommended normalized field:

year: 2026

or:

class_year: 2026

The optimizer should filter to:

player.year === 2026

or the equivalent field used in the generated data.

High-school recruits

For HS recruits, use the 2026 recruiting class.

In the hs_complete source data, this corresponds to:

year = 2026

In the historical freshman-prior projection script, 2026 HS recruits are the target projection rows.

The generated HS recruit objects should expose a normalized year field:

year: 2026

or:

hs_year: 2026

The frontend optimizer should only include HS recruits from that 2026 class.

Returning players

Returning players are not optimizer candidates in version one. They are used only as current roster context.

The active roster can include returning players for the selected team, but the optimizer recommendation pool should remain:

2026 transfers + 2026 HS recruits
Final implementation rule
For version one, restrict optimizer candidates to the 2026 cycle only.

Candidate pool:
- 2026 transfers
- 2026 high-school recruits

Do not recommend players from previous years.

Returning players should only be used as current roster context, not optimizer candidates.


## 18. Roster Slot Limits UI

Should the UI enforce:

```text
G + F + C <= 15
```

and prevent selecting a current roster that already exceeds any target position count?

Answer:
Yes. The UI should enforce roster slot limits clearly and prevent invalid optimizer runs.

The optimizer should use the target position counts:

target_G
target_F
target_C

with the hard rule:

target_G + target_F + target_C <= 15

The default target structure should be:

G = 5
F = 6
C = 4
Total = 15

The user can adjust the target counts, but the UI must not allow the total to exceed 15.

Active Roster Count Rule

The active roster management roster is:

active_roster_manage_roster =
    default team roster
  - user removals
  + user additions

The active roster must also satisfy:

active_ros_manage_roster.length <= 15

If the active roster has more than 15 players:

- do not calculate edited team ratings
- do not run optimizer
- disable optimizer button
- show red warning UI

Recommended warning text:

Too many players selected

Your roster currently has X players. Team ratings and optimizer recommendations are only available for rosters of 15 or fewer players.

Remove Y player(s) to continue.

Where:

Y = active_ros_manage_roster.length - 15
Position Count Rule

The optimizer should not run if the active roster already exceeds the target count for any position group.

Example:

target_G = 5
current_G = 6

This is invalid because the optimizer cannot fill negative guard slots.

In that case:

G_needed = target_G - current_G = -1

The UI should show a clear red warning:

Too many guards selected

Your target allows 5 guards, but your current roster has 6 guards.
Remove 1 guard or increase the guard target count.

Apply the same logic for forwards and centers.

Open Slot Calculation

When the roster is valid, calculate:

G_needed = target_G - current_G
F_needed = target_F - current_F
C_needed = target_C - current_C

The optimizer should select exactly:

G_needed guards
F_needed forwards
C_needed centers

If all open slots are zero:

G_needed = 0
F_needed = 0
C_needed = 0

then the optimizer should show:

Roster already matches target position counts.

and it does not need to recommend additions.

UX Requirements

The UI should make the current roster state obvious.

Recommended display:

Roster Size: 14 / 15
Guards: 4 / 5
Forwards: 6 / 6
Centers: 4 / 4

Use color states:

gray/neutral = valid but incomplete
green = exactly at target
red = over target or over 15 total

Examples:

14 / 15 players = neutral
15 / 15 players = green
16 / 15 players = red

4 / 5 guards = neutral
5 / 5 guards = green
6 / 5 guards = red

When any count is red:

- disable optimizer
- hide or disable edited rating overlay if total roster > 15
- show a clear warning explaining exactly what must change
Final Implementation Rule
The UI must enforce G + F + C <= 15.

The optimizer must not run if:
- active_ros_manage_roster.length > 15
- current_G > target_G
- current_F > target_F
- current_C > target_C

When valid:
G_needed = target_G - current_G
F_needed = target_F - current_F
C_needed = target_C - current_C

The optimizer must fill exactly those open slots.

Use clear red UI warnings for invalid roster size or invalid position counts.


## 19. Team Context

Should candidate recommendations be team-specific in any way beyond the selected roster's current skill profile?

For example, should committed players to other schools be excluded, or should all portal/recruit candidates be available as a theoretical pool?

Answer: For transfers, only players of status "committed" and "entered" should be considered. For hs recruits, only uncommitted players should be considered. Also, this is more of a UI note, but currently "Uncommitted" is listed as the team name for HS recruits. Rather than that, I want you to make all hs recruits with this "Uncommitted" flag be N/A and rather have a checkbox to pull these guys up if their status is "Uncommitted" This is more of a UI note and belongs in the Players tab under HS recruit toggle. 


## 20. Any Non-Negotiable Display Requirements

Besides recommended player name, position group, projected BPR, five percentiles, and before/after ratings, is there anything else the first version must display?

Answer:
Yes. The optimizer display must support multiple user-selectable recommendation views/metrics, and each view should clearly show the marginal roster impact of each player or recommended set.

The user should be able to select which metric they want to optimize/view.

Required metric filters:

1. Total Gain
2. Weakest Category Gain
3. Added Projected BPR
4. Category-Specific Gain

The display should not only show the player or set Codex/the optimizer selects. It should also show the actual marginal change caused by that recommendation.

Required Display Metrics

For every recommended player or recommended set, calculate and display:

current_total_rating
final_total_rating
total_gain = final_total_rating - current_total_rating
current_weakest_rating
final_weakest_rating
weakest_gain = final_weakest_rating - current_weakest_rating
added_projected_bpr = sum(projected_bpr of selected additions)

For each of the five skill categories, also calculate:

category_gain =
    final_category_rating - current_category_rating

The five categories are:

spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile
User-Selectable Ranking Modes

The user should be able to switch between recommendation modes.

Recommended UI dropdown/tabs:

Sort by:
- Best Overall Fit
- Total Gain
- Weakest Category Gain
- Added BPR
- Spacing Gain
- Facilitating Gain
- Rim Protection Gain
- Defense Gain
- Finishing Gain
Best Overall Fit

This is the default ranking mode and should follow the non-negotiable optimizer objective order:

1. final_total_rating descending
2. final_weakest_rating descending
3. added_projected_bpr descending
Total Gain

Rank by:

total_gain descending

Tie-breakers:

1. weakest_gain descending
2. added_projected_bpr descending
Weakest Category Gain

Rank by:

weakest_gain descending

Tie-breakers:

1. total_gain descending
2. added_projected_bpr descending
Added BPR

Rank by:

added_projected_bpr descending

Tie-breakers:

1. total_gain descending
2. weakest_gain descending
Category-Specific Gain

If the user selects one of the five percentile categories, rank by the marginal gain in that category.

Example for spacing:

spacing_gain =
    final_spacing_rating - current_spacing_rating

Rank by:

spacing_gain descending

Tie-breakers:

1. total_gain descending
2. weakest_gain descending
3. added_projected_bpr descending

Repeat the same structure for:

facilitating_gain
rim_protection_gain
defense_gain
finishing_gain
Metric Display Requirements

For each recommendation card, display the selected metric prominently.

Example for Total Gain mode:

+14.2 Total Rating
Affects: Overall roster profile

Example for Weakest Category Gain mode:

+7.8 Weakest Category
Affects: Rim Protection

Example for Spacing Gain mode:

+5.4 Spacing
Affects: Spacing percentile

The small text under the gain value should explain what category the gain is affecting.

Required card fields:

Player or Set Name
Position Group(s)
Source Type
Projected BPR / Added Projected BPR
Selected Metric Gain
Affected Category
Five percentile values
Before/after team ratings

For a full recommended set, display:

Selected players in set
Combined added BPR
Total gain
Weakest-category gain
Largest category gain
Category affected by largest gain

For an individual player recommendation, display:

Player name
Position group
Source type
Projected BPR
Individual total gain
Individual weakest gain
Best category gain
Best affected category
Affected Category Logic

For any recommendation, calculate all five category gains:

spacing_gain
facilitating_gain
rim_protection_gain
defense_gain
finishing_gain

Then determine:

best_affected_category =
    category with largest positive gain

Example:

spacing_gain = +2.1
facilitating_gain = +1.4
rim_protection_gain = +8.6
defense_gain = +3.0
finishing_gain = -0.5

Then:

best_affected_category = "Rim Protection"
best_category_gain = +8.6

If the selected filter is category-specific, the affected category should be that selected category.

If the selected filter is weakest-category gain, the affected category should be the roster’s weakest category after/before comparison, depending on implementation. Prefer showing the category that produced the weakest-gain improvement.

Percentile Category Filters

The user should be able to filter recommendations by percentile category.

Required category filters:

All Categories
Spacing
Facilitating
Rim Protection
Defense
Finishing

When a percentile category is selected, the displayed recommendations should prioritize players or sets that increase that specific team rating.

Example:

Filter: Spacing

Show players/sets ranked by:
spacing_gain descending

Each card should show:

+X.X Spacing
Affects: Spacing percentile

When All Categories is selected, use the default overall objective order.

Individual and Set-Level Display

The optimizer should support both:

1. Full recommended player sets
2. Individual fit recommendations

For full player sets:

Show how the entire selected group changes the roster.

For individual players:

Show how adding only that one player changes the roster.

The same metric filters should work for both views.

Recommended UI tabs:

Recommended Sets
Individual Fits
Hidden Fits

Each tab should respect the selected sort/filter mode.

Hidden Fits Display

A hidden-fit section is required.

Hidden fits are players who may not have the highest projected BPR but create meaningful roster improvement.

Recommended hidden-fit definition:

projected_bpr <= median projected_bpr for that position group
AND
player ranks highly in total_gain, weakest_gain, or selected category_gain

The user should be able to view hidden fits by category.

Example:

Hidden Fits - Spacing

Player A
Projected BPR: +1.2
Spacing Gain: +4.8
Affects: Spacing percentile
Team Rating Formula

All marginal changes must be calculated using the agreed BPR-weighted team rating formula:

team_skill_rating =
    sum(projected_bpr * skill_percentile)
    /
    sum(abs(projected_bpr))

Use this for:

spacing_percentile
facilitating_percentile
rim_protection_percentile
defense_percentile
finishing_percentile

Do not clamp negative projected BPR to positive values.

Final Implementation Rule

The first version must display more than just selected player names.

It must include:

1. User-selectable sort metric:
   - Best Overall Fit
   - Total Gain
   - Weakest Category Gain
   - Added BPR
   - Spacing Gain
   - Facilitating Gain
   - Rim Protection Gain
   - Defense Gain
   - Finishing Gain

2. User-selectable percentile category filter:
   - All Categories
   - Spacing
   - Facilitating
   - Rim Protection
   - Defense
   - Finishing

3. Marginal gain value for each recommendation.

4. Small explanatory text under the gain value showing which category is affected.

5. Support for full recommended sets, individual fits, and hidden-fit candidates.

6. Before/after ratings and rating deltas for all five categories.

The display should make it clear not only who the optimizer recommends, but why the recommendation matters to the roster.

