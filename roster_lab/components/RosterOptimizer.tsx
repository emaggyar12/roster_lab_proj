"use client";

import { useEffect, useMemo, useState, type DragEvent } from "react";
import Link from "next/link";
import basketballCourtPackage from "basketball-court";
import GLPK, { type GLPK as GLPKInstance, type LP } from "glpk.js";
import { Activity, AlertTriangle, ArrowRight, ChevronDown, Info, Loader2, RotateCcw, SlidersHorizontal, Trophy } from "lucide-react";
import clsx from "clsx";
import { players } from "@/data/players";
import { getHsPlayers, getPortalPlayers, getTeamPlayers, getTeams, isTransferOutgoingFromTeam } from "@/lib/data";
import {
  DEFAULT_TARGET_COUNTS,
  MAX_ROSTER_SIZE,
  SKILL_KEYS,
  SKILL_LABELS,
  TOP_N_CANDIDATES_PER_POSITION,
  buildHiddenFits,
  buildIndividualFits,
  calculateTeamRatings,
  candidateContribution,
  displayOptimizerTeam,
  getOpenSlots,
  getPositionCounts,
  normalizeCandidate,
  normalizeOptimizerPlayer,
  rankIndividualFits,
  rankRecommendationSets,
  ratingChanges,
  solutionToRecommendationSet,
  totalRating,
  weakestRating,
  type IndividualFitRecommendation,
  type OptimizerPlayer,
  type OptimizerResult,
  type PositionGroup,
  type RecommendationSet,
  type SkillKey,
  type SortMode,
  type TargetCounts,
  type TeamRatings,
} from "@/lib/optimizer";
import { readOptimizerRoster, saveOptimizerRoster, type OptimizerRosterPayload } from "@/lib/optimizerStorage";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { SourceBadge } from "@/components/StatusBadge";

type OptimizerView = "sets" | "single" | "manual";
type ResultTab = "sets" | "individual";

const POSITION_GROUPS: PositionGroup[] = ["G", "F", "C"];
const MANUAL_CANDIDATES_PER_PAGE = 20;
const MODE_OPTIONS: Array<{ value: OptimizerView; label: string }> = [
  { value: "sets", label: "Full Roster Optimization" },
  { value: "manual", label: "Manual Optimizer" },
  { value: "single", label: "Single Player Optimization" },
];
const SORT_OPTIONS: Array<{ value: SortMode; label: string }> = [
  { value: "overall", label: "Best Overall Fit" },
  { value: "total_gain", label: "Total Gain" },
  { value: "weakest_gain", label: "Weakest Category Gain" },
  { value: "added_bpr", label: "Added BPR" },
];
const CATEGORY_OPTIONS: Array<{ value: "all" | SkillKey; label: string }> = [
  { value: "all", label: "All Categories" },
  ...SKILL_KEYS.map((key) => ({ value: key, label: SKILL_LABELS[key] })),
];
const ROSTER_MANAGEMENT_STORAGE_KEY = "roster-lab-roster-management-state";
const makeBasketballCourt = basketballCourtPackage as unknown as (options: Record<string, unknown>) => { toString: () => string };
const COURT_THEME = {
  global: {
    fill: "none",
    stroke: "#F8FAFC",
    "stroke-width": "3",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  },
  court: { fill: "#0F172A" },
  centerCircle: { fill: "#1E293B", stroke: "#CBD5E1", "stroke-width": "2" },
  restrainCircle: false,
  lane: { fill: "#1E293B", stroke: "#F8FAFC", "stroke-width": "3" },
  innerLane: { fill: "#0F172A", stroke: "#CBD5E1", "stroke-width": "2" },
  tpline: { fill: "none", stroke: "#F8FAFC", "stroke-width": "3.5" },
  ftCircleHigh: { fill: "none", stroke: "#F8FAFC", "stroke-width": "3" },
  ftCircleLow: { fill: "none", stroke: "#94A3B8", "stroke-width": "2.5" },
  restricted: { fill: "none", stroke: "#CBD5E1", "stroke-width": "2.5" },
  backboard: { stroke: "#E2E8F0", "stroke-width": "5" },
  rim: { fill: "none", stroke: "#FB923C", "stroke-width": "4" },
};

let glpkPromise: Promise<GLPKInstance> | null = null;

function readCurrentOptimizerPayload(): OptimizerRosterPayload | null {
  if (typeof window === "undefined") return null;
  const rosterPayload = readRosterManagementPayload();
  if (rosterPayload) {
    saveOptimizerRoster(rosterPayload);
    return rosterPayload;
  }
  const existingPayload = readOptimizerRoster();
  if (existingPayload) return existingPayload;
  const defaultTeam = getTeams()[0]?.team_name;
  if (!defaultTeam) return null;
  const defaultPayload = {
    teamName: defaultTeam,
    playerIds: getTeamPlayers(defaultTeam).map((player) => player.player_id),
    loadedAt: new Date().toISOString(),
  };
  saveOptimizerRoster(defaultPayload);
  return defaultPayload;
}

function readRosterManagementPayload(): OptimizerRosterPayload | null {
  try {
    const raw = window.localStorage.getItem(ROSTER_MANAGEMENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<{
      teamName: string;
      removedIds: string[];
      addedIds: string[];
    }>;
    if (!parsed.teamName || !Array.isArray(parsed.removedIds) || !Array.isArray(parsed.addedIds)) return null;
    const removedIds = new Set(parsed.removedIds.filter((id): id is string => typeof id === "string"));
    const addedIds = new Set(parsed.addedIds.filter((id): id is string => typeof id === "string"));
    const currentRoster = getTeamPlayers(parsed.teamName);
    const currentIds = new Set(currentRoster.map((player) => player.player_id));
    const targetPlayers = [...getPortalPlayers(), ...getHsPlayers()].filter((player) => !currentIds.has(player.player_id));
    const projectedRoster = [
      ...currentRoster.filter((player) => !removedIds.has(player.player_id)),
      ...targetPlayers.filter((player) => addedIds.has(player.player_id)),
    ];
    return {
      teamName: parsed.teamName,
      playerIds: projectedRoster.map((player) => player.player_id),
      loadedAt: new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

export function RosterOptimizer() {
  const [payload, setPayload] = useState<OptimizerRosterPayload | null>(null);
  const [targetCounts, setTargetCounts] = useState<TargetCounts>(DEFAULT_TARGET_COUNTS);
  const [view, setView] = useState<OptimizerView>("sets");
  const [resultTab, setResultTab] = useState<ResultTab>("sets");
  const [sortMode, setSortMode] = useState<SortMode>("overall");
  const [categoryFilter, setCategoryFilter] = useState<"all" | SkillKey>("all");
  const [manualIds, setManualIds] = useState<string[]>([]);
  const [result, setResult] = useState<OptimizerResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    setPayload(readCurrentOptimizerPayload());
  }, []);

  const playerById = useMemo(() => new Map(players.map((player) => [player.player_id, player])), []);
  const loadedPlayers = useMemo(
    () =>
      payload?.playerIds
        .map((id) => playerById.get(id))
        .filter((player): player is NonNullable<typeof player> => Boolean(player))
        .filter((player) => !isTransferOutgoingFromTeam(player, payload.teamName)) ?? [],
    [payload, playerById],
  );
  const currentRoster = useMemo(
    () => loadedPlayers.map(normalizeOptimizerPlayer).filter((player): player is OptimizerPlayer => Boolean(player)),
    [loadedPlayers],
  );
  const invalidLoadedCount = Math.max(0, loadedPlayers.length - currentRoster.length);
  const currentCounts = useMemo(() => getPositionCounts(currentRoster), [currentRoster]);
  const openSlots = useMemo(() => getOpenSlots(currentCounts, targetCounts), [currentCounts, targetCounts]);
  const currentRatings = useMemo(() => calculateTeamRatings(currentRoster), [currentRoster]);
  const validation = useMemo(() => validateRosterState(loadedPlayers.length, currentCounts, targetCounts), [currentCounts, loadedPlayers.length, targetCounts]);
  const candidates = useMemo(() => {
    const selectedIds = new Set(currentRoster.map((player) => player.optimizer_player_id));
    const selectedAllyears = new Set(currentRoster.map((player) => player.allyears_pid).filter(Boolean));
    const selectedHsKeys = new Set(currentRoster.map((player) => player.player_key).filter(Boolean));
    const selectedNameSource = new Set(currentRoster.map((player) => `${player.source_type}:${normalizeName(player.player_name)}`));
    return [...getPortalPlayers(), ...getHsPlayers()]
      .map(normalizeCandidate)
      .filter((player): player is OptimizerPlayer => Boolean(player))
      .filter((candidate) => {
        if (selectedIds.has(candidate.optimizer_player_id)) return false;
        if (candidate.allyears_pid && selectedAllyears.has(candidate.allyears_pid)) return false;
        if (candidate.player_key && selectedHsKeys.has(candidate.player_key)) return false;
        if (selectedNameSource.has(`${candidate.source_type}:${normalizeName(candidate.player_name)}`)) return false;
        return true;
      });
  }, [currentRoster]);
  const fullRosterCandidates = useMemo(() => {
    if (!payload?.teamName) return candidates;
    return candidates.filter((candidate) => !isTransferOutgoingFromTeam(candidate.player, payload.teamName));
  }, [candidates, payload?.teamName]);

  const effectiveSortMode: SortMode =
    (sortMode === "total_gain" || sortMode === "weakest_gain") && categoryFilter !== "all"
      ? categoryFilter
      : sortMode;
  const fullSetSortMode: SortMode = view === "sets" ? "overall" : effectiveSortMode;
  const sortedSets = useMemo(() => (result ? rankRecommendationSets(result.recommended_sets, fullSetSortMode) : []), [fullSetSortMode, result]);

  async function runOptimizer() {
    setError(null);
    setResult(null);
    if (!payload) {
      setError("Load a roster from Roster Management before running the optimizer.");
      return;
    }
    if (validation) {
      setError(validation);
      return;
    }
    if (!currentRoster.length) {
      setError("The loaded roster does not contain enough players with optimizer fields.");
      return;
    }
    const totalNeeded = POSITION_GROUPS.reduce((sum, position) => sum + openSlots[position], 0);
    if (totalNeeded === 0) {
      setError("Roster already matches target position counts.");
      return;
    }

    setIsRunning(true);
    try {
      const nextResult = await solveOptimizer({
        currentRoster,
        candidates: fullRosterCandidates,
        openSlots,
        currentRatings,
      });
      setResult(nextResult);
      setResultTab("sets");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No valid recommendation found for the current roster constraints.");
    } finally {
      setIsRunning(false);
    }
  }

  function resetOptimizer() {
    setPayload(readCurrentOptimizerPayload());
    setTargetCounts(DEFAULT_TARGET_COUNTS);
    setManualIds([]);
    setResult(null);
    setError(null);
    setResultTab("sets");
  }

  function updateTarget(position: PositionGroup, delta: number) {
    setTargetCounts((counts) => {
      if (delta === 0) return counts;
      if (delta < 0 && counts[position] <= 0) return counts;
      return { ...counts, [position]: Math.max(0, counts[position] + delta) };
    });
    setResult(null);
  }

  function setTarget(position: PositionGroup, value: number) {
    if (!Number.isFinite(value)) return;
    setTargetCounts((counts) => ({ ...counts, [position]: Math.max(0, Math.floor(value)) }));
    setResult(null);
  }

  if (!payload) {
    return (
      <div className="rounded border border-line bg-white p-6 shadow-soft">
        <div className="text-lg font-semibold text-ink">No roster loaded</div>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
          Open Roster Management, make any additions or removals, then click Load to Optimizer.
        </p>
        <Link href="/rosters" className="mt-4 inline-flex h-10 items-center rounded bg-emerald-600 px-4 text-sm font-semibold text-white">
          Go to Roster Management
        </Link>
      </div>
    );
  }

  return (
    <section className="space-y-4">
      <div className="-mt-20 mb-10 flex justify-end gap-2">
        <Link href="/rosters" className="inline-flex h-9 items-center justify-center rounded border border-line bg-panel px-4 text-sm font-semibold text-slate-700">
          Back
        </Link>
        <button
          type="button"
          onClick={resetOptimizer}
          className="inline-flex h-9 items-center justify-center gap-2 rounded border border-line bg-panel px-4 text-sm font-semibold text-slate-700"
        >
          <RotateCcw className="h-4 w-4" />
          Reset
        </button>
      </div>
      <div className="overflow-hidden rounded border border-line bg-white shadow-soft">
        <div className={clsx("grid", view === "sets" && "xl:grid-cols-[minmax(0,1fr)_320px]")}>
          <div className="min-w-0 p-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Loaded Roster</div>
            <div className="mt-2 text-3xl font-semibold text-ink">{payload.teamName}</div>
            <div className="mt-2 text-sm text-slate-600">{loadedPlayers.length} players from Roster Management</div>
            {invalidLoadedCount ? (
              <div className="mt-3 inline-flex rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-600">
                {invalidLoadedCount} loaded player(s) are missing optimizer fields and are excluded from rating calculations.
              </div>
            ) : null}
            <div className="mt-5 grid max-w-3xl grid-cols-3 rounded border border-line bg-panel p-1">
              {MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setView(option.value)}
                  className={
                    view === option.value
                      ? "h-10 rounded bg-emerald-600 px-3 text-sm font-semibold text-white dark:bg-emerald-500 dark:text-slate-950"
                      : "h-10 rounded px-3 text-sm font-semibold text-slate-600 hover:bg-surface dark:text-slate-300"
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          {view === "sets" ? (
            <div className="border-t border-line bg-panel p-4 xl:border-l xl:border-t-0">
              <div className="space-y-3">
                <TargetControls targetCounts={targetCounts} currentCounts={currentCounts} onChange={updateTarget} onSet={setTarget} rosterSize={loadedPlayers.length} />
                <button
                  type="button"
                  onClick={runOptimizer}
                  disabled={Boolean(validation) || isRunning}
                  className="inline-flex h-12 w-full items-center justify-center gap-2 rounded bg-emerald-600 px-5 text-base font-semibold text-white shadow-soft disabled:cursor-not-allowed disabled:opacity-50 dark:bg-emerald-500 dark:text-slate-950"
                >
                  {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trophy className="h-4 w-4" />}
                  {isRunning ? "Optimizing..." : "Run Optimizer"}
                </button>
              </div>
              {validation ? <div className="mt-3"><WarningPanel message={validation} /></div> : null}
              {error ? <div className="mt-3"><WarningPanel message={error} /></div> : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="space-y-4">
        <div className="space-y-4">
          {view === "sets" ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(560px,.98fr)_minmax(520px,1.02fr)]">
              <div className="space-y-3">
                {sortedSets[0] ? <CourtLineup players={[...currentRoster, ...sortedSets[0].selected_players]} additions={sortedSets[0].selected_players} /> : <EmptyResults text="Run the optimizer to see the recommended court and bench." />}
              </div>
              <div className="space-y-4">
                <TeamComparisonCard baseline={currentRatings} result={sortedSets[0]} invalid={loadedPlayers.length > MAX_ROSTER_SIZE} />
                <ResultTabs active={resultTab} onChange={setResultTab} />
                {resultTab === "sets" ? <RecommendedSets sets={sortedSets.slice(0, 5)} sortMode={fullSetSortMode} /> : null}
                {resultTab === "individual" && result ? <IndividualFits fits={result.individual_fits} sortMode={effectiveSortMode} /> : null}
              </div>
            </div>
          ) : view === "single" ? (
            <>
              {loadedPlayers.length <= MAX_ROSTER_SIZE ? (
                <SinglePlayerPane
                  result={result}
                  sortModeValue={sortMode}
                  categoryFilter={categoryFilter}
                  onSortModeChange={(mode) => {
                    setSortMode(mode);
                    if (mode !== "total_gain" && mode !== "weakest_gain") setCategoryFilter("all");
                  }}
                  onCategoryFilterChange={setCategoryFilter}
                  sortMode={effectiveSortMode}
                  candidates={candidates}
                  currentRoster={currentRoster}
                  currentRatings={currentRatings}
                />
              ) : (
                <WarningPanel message="Single-player optimization is disabled until the roster is back to 15 or fewer players." />
              )}
            </>
          ) : (
            <ManualOptimizerPane
              candidates={candidates}
              currentRoster={currentRoster}
              currentRatings={currentRatings}
              manualIds={manualIds}
              onManualIdsChange={setManualIds}
              sortModeValue={sortMode}
              categoryFilter={categoryFilter}
              onSortModeChange={(mode) => {
                setSortMode(mode);
                if (mode !== "total_gain" && mode !== "weakest_gain") setCategoryFilter("all");
              }}
              onCategoryFilterChange={setCategoryFilter}
              sortMode={effectiveSortMode}
            />
          )}
        </div>
      </div>
    </section>
  );
}

const GLPK_SOLUTIONS_PER_OBJECTIVE = 12;
const DINKELBACH_ITERATIONS = 12;

async function solveOptimizer({
  currentRoster,
  candidates,
  openSlots,
  currentRatings,
}: {
  currentRoster: OptimizerPlayer[];
  candidates: OptimizerPlayer[];
  openSlots: TargetCounts;
  currentRatings: TeamRatings;
}): Promise<OptimizerResult> {
  const neededPositions = POSITION_GROUPS.filter((position) => openSlots[position] > 0);

  // Only keep candidates who can actually fill one of the currently open position slots.
  const eligibleCandidates = candidates.filter((candidate) => neededPositions.includes(candidate.position_group));

  // Build single-player fits from the full eligible pool. Do not use the GLPK-capped pool here.
  // Single Player Optimization should answer the clean marginal question for every eligible player.
  const individualFits = buildIndividualFits(currentRoster, eligibleCandidates, currentRatings);
  const individualFitById = new Map(
    POSITION_GROUPS.flatMap((group) => individualFits[group]).map((fit) => [fit.player.optimizer_player_id, fit]),
  );

  // Build a broader GLPK pool using multiple signals. The old version only capped by
  // candidateContribution(), which can miss players who are better by exact one-player gain.
  const cappedCandidates = buildExpandedGlpkCandidatePool({
    candidates: eligibleCandidates,
    individualFits,
    currentRatings,
  });

  const availableCounts = getPositionCounts(cappedCandidates);
  for (const position of neededPositions) {
    if (availableCounts[position] < openSlots[position]) {
      throw new Error(`Not enough eligible candidates available for ${position}. Needed: ${openSlots[position]}. Available: ${availableCounts[position]}.`);
    }
  }

  const glpk = await getGlpk();
  const currentTotal = totalRating(currentRatings);
  const currentWeakest = weakestRating(currentRatings);
  const seen = new Set<string>();
  const sets: RecommendationSet[] = [];

  function addSelectedSet(selected: OptimizerPlayer[], surfacedBy: string) {
    if (!selected.length) return;

    const signature = selected.map((candidate) => candidate.optimizer_player_id).sort().join("|");
    if (seen.has(signature)) return;

    seen.add(signature);
    sets.push(
      solutionToRecommendationSet({
        selectedPlayers: selected,
        currentRoster,
        currentRatings,
        currentTotal,
        currentWeakest,
        rank: sets.length + 1,
        surfacedBy,
      }),
    );
  }

  async function runObjectiveFamily({
    id,
    label,
    objective,
  }: {
    id: string;
    label: string;
    objective: number[];
  }) {
    const exclusions: string[][] = [];

    for (let iteration = 0; iteration < GLPK_SOLUTIONS_PER_OBJECTIVE; iteration += 1) {
      const selected = await solveSingleGlpkModel(
        glpk,
        cappedCandidates,
        openSlots,
        objective,
        exclusions,
        `${id}-${iteration}`,
      );

      if (!selected.length) break;

      exclusions.push(selected.map((candidate) => candidate.optimizer_player_id));
      addSelectedSet(selected, label);
    }
  }

  // 1. Original rough objective family.
  await runObjectiveFamily({
    id: "rough-total",
    label: "Total contribution",
    objective: cappedCandidates.map((candidate) => candidateContribution(candidate)),
  });

  for (const skill of SKILL_KEYS) {
    await runObjectiveFamily({
      id: `skill-${skill}`,
      label: `${SKILL_LABELS[skill]} specialist`,
      objective: cappedCandidates.map((candidate) => candidateContribution(candidate, skill)),
    });
  }

  // 2. Exact one-player gain objective family.
  // These make the full-set generator consider players who improve the current roster directly,
  // even if their rough BPR * skill_sum score is lower.
  await runObjectiveFamily({
    id: "one-player-total-gain",
    label: "One-player total gain",
    objective: cappedCandidates.map((candidate) => individualFitById.get(candidate.optimizer_player_id)?.individual_total_gain ?? -9999),
  });

  await runObjectiveFamily({
    id: "one-player-weakest-gain",
    label: "One-player weakest-category gain",
    objective: cappedCandidates.map((candidate) => individualFitById.get(candidate.optimizer_player_id)?.individual_weakest_gain ?? -9999),
  });

  for (const skill of SKILL_KEYS) {
    await runObjectiveFamily({
      id: `one-player-${skill}-gain`,
      label: `One-player ${SKILL_LABELS[skill]} gain`,
      objective: cappedCandidates.map((candidate) => individualFitById.get(candidate.optimizer_player_id)?.rating_changes_if_added[skill] ?? -9999),
    });
  }

  // 3. Weakness objectives using the current roster profile.
  const weakestCurrentSkill = SKILL_KEYS.map((key) => ({ key, value: currentRatings[key] })).sort((left, right) => left.value - right.value)[0]?.key;
  const bestCurrentSkill = Math.max(...SKILL_KEYS.map((key) => currentRatings[key]));

  if (weakestCurrentSkill) {
    await runObjectiveFamily({
      id: "current-weakness",
      label: "Current weakness",
      objective: cappedCandidates.map((candidate) => candidateContribution(candidate, weakestCurrentSkill)),
    });
  }

  await runObjectiveFamily({
    id: "weakness-balanced",
    label: "Weakness balanced",
    objective: cappedCandidates.map((candidate) =>
      SKILL_KEYS.reduce((sum, key) => {
        const gapWeight = Math.max(bestCurrentSkill - currentRatings[key], 0);
        return sum + candidate.projected_bpr * candidate[key] * gapWeight;
      }, 0),
    ),
  });

  // 4. Fractional objective approximation for the exact total-rating formula.
  // GLPK cannot directly maximize a ratio, so this uses a Dinkelbach-style linearization.
  await runDinkelbachObjectiveFamily({
    glpk,
    candidates: cappedCandidates,
    currentRoster,
    openSlots,
    addSelectedSet,
  });

  if (!sets.length) throw new Error("No valid recommendation found for the current roster constraints.");

  // Critical final step: exact-rank every generated set by the true recommendation order.
  const rankedSets = rankRecommendationSets(sets, "overall").map((set, index) => ({ ...set, rank: index + 1 }));
  const hiddenFits = buildHiddenFits(individualFits, eligibleCandidates, "overall");

  return {
    recommended_sets: rankedSets,
    individual_fits: individualFits,
    hidden_fits: hiddenFits,
    current_ratings: currentRatings,
    current_total_rating: currentTotal,
    current_weakest_rating: currentWeakest,
    open_slots: openSlots,
    current_counts: getPositionCounts(currentRoster),
  };
}

function buildExpandedGlpkCandidatePool({
  candidates,
  individualFits,
  currentRatings,
}: {
  candidates: OptimizerPlayer[];
  individualFits: OptimizerResult["individual_fits"];
  currentRatings: TeamRatings;
}) {
  const fitById = new Map(
    POSITION_GROUPS.flatMap((group) => individualFits[group]).map((fit) => [fit.player.optimizer_player_id, fit]),
  );
  const selected = new Map<string, OptimizerPlayer>();

  function addTopByScore(positionCandidates: OptimizerPlayer[], score: (candidate: OptimizerPlayer) => number) {
    positionCandidates
      .slice()
      .sort((left, right) => {
        const scoreDiff = score(right) - score(left);
        if (scoreDiff !== 0) return scoreDiff;
        return right.projected_bpr - left.projected_bpr;
      })
      .slice(0, TOP_N_CANDIDATES_PER_POSITION)
      .forEach((candidate) => selected.set(candidate.optimizer_player_id, candidate));
  }

  const bestCurrentSkill = Math.max(...SKILL_KEYS.map((key) => currentRatings[key]));

  for (const position of POSITION_GROUPS) {
    const positionCandidates = candidates.filter((candidate) => candidate.position_group === position);

    // Original contribution signal.
    addTopByScore(positionCandidates, (candidate) => candidateContribution(candidate));

    // Exact one-player marginal signals.
    addTopByScore(positionCandidates, (candidate) => fitById.get(candidate.optimizer_player_id)?.individual_total_gain ?? -9999);
    addTopByScore(positionCandidates, (candidate) => fitById.get(candidate.optimizer_player_id)?.individual_weakest_gain ?? -9999);

    for (const skill of SKILL_KEYS) {
      addTopByScore(positionCandidates, (candidate) => fitById.get(candidate.optimizer_player_id)?.rating_changes_if_added[skill] ?? -9999);
    }

    // Raw category contribution signals.
    for (const skill of SKILL_KEYS) {
      addTopByScore(positionCandidates, (candidate) => candidateContribution(candidate, skill));
    }

    // Current-roster weakness signal.
    addTopByScore(positionCandidates, (candidate) =>
      SKILL_KEYS.reduce((sum, key) => {
        const gapWeight = Math.max(bestCurrentSkill - currentRatings[key], 0);
        return sum + candidate.projected_bpr * candidate[key] * gapWeight;
      }, 0),
    );
  }

  return Array.from(selected.values());
}

async function runDinkelbachObjectiveFamily({
  glpk,
  candidates,
  currentRoster,
  openSlots,
  addSelectedSet,
}: {
  glpk: GLPKInstance;
  candidates: OptimizerPlayer[];
  currentRoster: OptimizerPlayer[];
  openSlots: TargetCounts;
  addSelectedSet: (selected: OptimizerPlayer[], surfacedBy: string) => void;
}) {
  const exclusions: string[][] = [];

  for (let solutionIndex = 0; solutionIndex < GLPK_SOLUTIONS_PER_OBJECTIVE; solutionIndex += 1) {
    let lambda = exactTotalFraction(currentRoster);
    let selected: OptimizerPlayer[] = [];

    for (let iteration = 0; iteration < DINKELBACH_ITERATIONS; iteration += 1) {
      const objective = candidates.map((candidate) => totalNumerator([candidate]) - lambda * totalDenominator([candidate]));
      const nextSelected = await solveSingleGlpkModel(
        glpk,
        candidates,
        openSlots,
        objective,
        exclusions,
        `dinkelbach-${solutionIndex}-${iteration}`,
      );

      if (!nextSelected.length) break;

      selected = nextSelected;
      const nextLambda = exactTotalFraction([...currentRoster, ...selected]);
      if (Math.abs(nextLambda - lambda) < 1e-6) break;
      lambda = nextLambda;
    }

    if (!selected.length) break;

    exclusions.push(selected.map((candidate) => candidate.optimizer_player_id));
    addSelectedSet(selected, "Exact total-rating approximation");
  }
}

function totalSkillSum(player: OptimizerPlayer) {
  return SKILL_KEYS.reduce((sum, key) => sum + player[key], 0);
}

function totalNumerator(playersToScore: OptimizerPlayer[]) {
  return playersToScore.reduce((sum, player) => sum + player.projected_bpr * totalSkillSum(player), 0);
}

function totalDenominator(playersToScore: OptimizerPlayer[]) {
  return playersToScore.reduce((sum, player) => sum + Math.abs(player.projected_bpr), 0);
}

function exactTotalFraction(playersToScore: OptimizerPlayer[]) {
  const denominator = totalDenominator(playersToScore);
  if (denominator <= 0) return 0;
  return totalNumerator(playersToScore) / denominator;
}

async function solveSingleGlpkModel(
  glpk: GLPKInstance,
  candidates: OptimizerPlayer[],
  openSlots: TargetCounts,
  objective: number[],
  exclusions: string[][],
  name: string,
) {
  const vars = candidates.map((_, index) => `x_${index}`);
  const subjectTo: LP["subjectTo"] = POSITION_GROUPS.map((position) => ({
    name: `need_${position}`,
    vars: candidates
      .map((candidate, index) => (candidate.position_group === position ? { name: vars[index], coef: 1 } : null))
      .filter((value): value is { name: string; coef: number } => Boolean(value)),
    bnds: { type: glpk.GLP_FX, lb: openSlots[position], ub: openSlots[position] },
  }));
  exclusions.forEach((selectedIds, index) => {
    const selected = new Set(selectedIds);
    subjectTo.push({
      name: `exclude_${index}`,
      vars: candidates
        .map((candidate, candidateIndex) => (selected.has(candidate.optimizer_player_id) ? { name: vars[candidateIndex], coef: 1 } : null))
        .filter((value): value is { name: string; coef: number } => Boolean(value)),
      bnds: { type: glpk.GLP_UP, lb: 0, ub: Math.max(0, selectedIds.length - 1) },
    });
  });
  const lp: LP = {
    name,
    objective: {
      direction: glpk.GLP_MAX,
      name: "obj",
      vars: vars.map((variable, index) => ({ name: variable, coef: objective[index] })),
    },
    subjectTo,
    binaries: vars,
  };
  const solved = await glpk.solve(lp, { msglev: glpk.GLP_MSG_ERR, presol: true, tmlim: 8 });
  if (solved.result.status !== glpk.GLP_OPT && solved.result.status !== glpk.GLP_FEAS) return [];
  return candidates.filter((_, index) => Math.round(solved.result.vars[vars[index]] ?? 0) === 1);
}

function TargetControls({
  targetCounts,
  currentCounts,
  rosterSize,
  onChange,
  onSet,
}: {
  targetCounts: TargetCounts;
  currentCounts: TargetCounts;
  rosterSize: number;
  onChange: (position: PositionGroup, delta: number) => void;
  onSet: (position: PositionGroup, value: number) => void;
}) {
  const targetTotalIsValid = targetCounts.G + targetCounts.F + targetCounts.C === MAX_ROSTER_SIZE;
  return (
    <div className="grid gap-2">
        <CountPill
          label="Roster Size"
          current={rosterSize}
          target={MAX_ROSTER_SIZE}
          tooltip="Optimizer only runs if total roster count equals 15. Adjust positional limits with +/- buttons or manually adjust in text fields until roster count is 15."
        />
        {POSITION_GROUPS.map((position) => (
          <div key={position} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded border border-line bg-white px-3 py-2 dark:bg-panel">
            <EditableCountPill
              label={positionLabel(position)}
              current={currentCounts[position]}
              target={targetCounts[position]}
              invalidTotal={!targetTotalIsValid}
              onTargetChange={(value) => onSet(position, value)}
            />
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => onChange(position, -1)} className="h-8 w-8 rounded border border-line bg-panel text-sm font-semibold">-</button>
              <button type="button" onClick={() => onChange(position, 1)} className="h-8 w-8 rounded border border-line bg-panel text-sm font-semibold">+</button>
            </div>
          </div>
        ))}
    </div>
  );
}

function EditableCountPill({
  label,
  current,
  target,
  invalidTotal,
  onTargetChange,
}: {
  label: string;
  current: number;
  target: number;
  invalidTotal: boolean;
  onTargetChange: (value: number) => void;
}) {
  const [draftTarget, setDraftTarget] = useState(String(target));

  useEffect(() => {
    setDraftTarget(String(target));
  }, [target]);

  const tone = current > target || invalidTotal ? "text-rose-600" : current === target ? "text-emerald-700" : "text-slate-600";
  const displayLabel = label.replace("Guards", "Guard").replace("Forwards", "Forward").replace("Centers", "Center");
  function handleTargetInput(value: string) {
    const digits = value.replace(/\D/g, "");
    if (!digits) {
      setDraftTarget("");
      return;
    }
    const nextValue = String(Number.parseInt(digits, 10));
    setDraftTarget(nextValue);
    onTargetChange(Number(nextValue));
  }

  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="font-semibold text-slate-600">{displayLabel}</span>
      <span className={clsx("flex items-center gap-1 font-bold tabular-nums", tone)}>
        {current} /
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={draftTarget}
          onChange={(event) => handleTargetInput(event.target.value)}
          onBlur={() => {
            if (!draftTarget) setDraftTarget(String(target));
          }}
          className={clsx(
            "h-7 w-11 rounded border bg-panel px-1 text-center font-bold tabular-nums outline-none focus:border-ink",
            current > target || invalidTotal ? "border-rose-500 text-rose-600" : "border-line text-inherit",
          )}
        />
      </span>
    </div>
  );
}

function CountPill({
  label,
  current,
  target,
  compact = false,
  tooltip,
}: {
  label: string;
  current: number;
  target: number;
  compact?: boolean;
  tooltip?: string;
}) {
  const tone = current > target ? "text-rose-600" : current === target ? "text-emerald-700" : "text-slate-600";
  const displayLabel = compact ? label.replace("Guards", "Guard").replace("Forwards", "Forward").replace("Centers", "Center") : label;
  return (
    <div className={clsx("flex items-center justify-between gap-3", compact ? "text-sm" : "rounded border border-line bg-white px-3 py-2 text-sm dark:bg-panel")}>
      <span className="flex items-center gap-1.5 font-semibold text-slate-600">
        {tooltip ? (
          <span className="group relative inline-flex">
            <Info className="h-3.5 w-3.5 text-slate-500" aria-label={tooltip} />
            <span className="pointer-events-none absolute left-0 top-5 z-30 hidden w-64 rounded border border-line bg-panel px-2 py-1.5 text-xs font-semibold leading-5 text-slate-700 shadow-soft group-hover:block">
              {tooltip}
            </span>
          </span>
        ) : null}
        {displayLabel}
      </span>
      <span className={clsx("font-bold tabular-nums", tone)}>{current} / {target}</span>
    </div>
  );
}

function OptimizerControls({
  sortMode,
  categoryFilter,
  disabled,
  onSortModeChange,
  onCategoryFilterChange,
}: {
  sortMode: SortMode;
  categoryFilter: "all" | SkillKey;
  disabled: boolean;
  onSortModeChange: (mode: SortMode) => void;
  onCategoryFilterChange: (category: "all" | SkillKey) => void;
}) {
  return (
    <div className="rounded border border-line bg-white p-4 shadow-soft">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
        <SlidersHorizontal className="h-4 w-4" />
        Recommendation View
      </div>
      <div className="grid gap-2">
        <Select value={sortMode} onChange={(value) => onSortModeChange(value as SortMode)} options={SORT_OPTIONS} disabled={disabled} />
        {sortMode === "total_gain" || sortMode === "weakest_gain" ? (
          <Select value={categoryFilter} onChange={(value) => onCategoryFilterChange(value as "all" | SkillKey)} options={CATEGORY_OPTIONS} disabled={disabled} />
        ) : null}
      </div>
    </div>
  );
}

function TeamComparisonCard({
  baseline,
  result,
  manualRatings,
  invalid,
}: {
  baseline: TeamRatings;
  result?: RecommendationSet;
  manualRatings?: TeamRatings;
  invalid: boolean;
}) {
  const finalRatings = manualRatings ?? result?.final_ratings;
  return (
    <div className="rounded border border-line bg-white p-4 shadow-soft">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
        <Activity className="h-4 w-4" />
        Roster Rating Overlay
      </div>
      {invalid ? (
        <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm font-semibold text-rose-700">
          Roster is over 15 players. Edited ratings are disabled until the roster is back to 15 or fewer.
        </div>
      ) : (
        <ComparisonRadar baseline={baseline} finalRatings={finalRatings} />
      )}
    </div>
  );
}

function ComparisonRadar({ baseline, finalRatings }: { baseline: TeamRatings; finalRatings?: TeamRatings }) {
  const center = 110;
  const maxRadius = 78;
  const angles = SKILL_KEYS.map((_, index) => -90 + index * 72);
  const basePointArray = polygonPointArray(SKILL_KEYS.map((key) => baseline[key]), center, maxRadius, angles);
  const finalPointArray = finalRatings ? polygonPointArray(SKILL_KEYS.map((key) => finalRatings[key]), center, maxRadius, angles) : [];
  const labelPoints = angles.map((angle) => polarPoint(center, center, maxRadius + 19, angle));
  const basePoints = pointsToString(basePointArray);
  const finalPoints = pointsToString(finalPointArray);
  return (
    <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)] lg:items-center">
      <svg viewBox="0 0 220 220" className="mx-auto h-56 w-56 overflow-visible">
        <polygon points={basePoints} className="fill-slate-400/25 stroke-slate-400" strokeWidth="2" />
        {finalRatings ? (
          <>
            <polygon points={finalPoints} className="fill-emerald-500/10 stroke-slate-300" strokeWidth="2" />
            {finalPointArray.map((point, index) => {
              const key = SKILL_KEYS[index];
              const improved = finalRatings[key] >= baseline[key];
              return (
                <circle
                  key={key}
                  cx={point.x}
                  cy={point.y}
                  r="5"
                  className={improved ? "fill-emerald-500 stroke-white" : "fill-rose-500 stroke-white"}
                  strokeWidth="2"
                />
              );
            })}
          </>
        ) : null}
        {labelPoints.map((point, index) => (
          <text
            key={SKILL_KEYS[index]}
            x={point.x}
            y={point.y}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-slate-500 text-[9px] font-bold"
          >
            {radarShortLabel(SKILL_KEYS[index])}
          </text>
        ))}
      </svg>
      <div className="grid gap-2">
        {SKILL_KEYS.map((key) => {
          const final = finalRatings?.[key];
          const delta = final == null ? 0 : final - baseline[key];
          return (
            <div key={key} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded border border-line bg-panel px-3 py-2 text-sm">
              <span className="font-semibold text-slate-600">{SKILL_LABELS[key]}</span>
              <span className="inline-flex items-center gap-1 font-semibold tabular-nums text-slate-700">
                {baseline[key].toFixed(2)}
                {final != null ? (
                  <>
                    <ArrowRight className="h-3.5 w-3.5 text-slate-500" />
                    {final.toFixed(2)}
                  </>
                ) : null}
              </span>
              {final != null ? <span className={clsx("font-bold tabular-nums", delta >= 0 ? "text-emerald-600" : "text-rose-600")}>{formatDelta(delta)}</span> : null}
            </div>
          );
        })}
        <div className="flex flex-wrap gap-3 text-xs font-semibold text-slate-500">
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-slate-400" />Original roster</span>
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-500" />Improvement</span>
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-rose-500" />Decline</span>
        </div>
      </div>
    </div>
  );
}

type CourtSpot = {
  key: "guardTop" | "guardWing" | "forwardSlot" | "forwardBaseline" | "centerPaint";
  label: string;
  role: "Guard" | "Forward" | "Center";
  x: number;
  y: number;
};

/**
 * Baseline-bottom layout.
 *
 * Percentages are panel coordinates:
 * - x: 0 left to 100 right
 * - y: 0 top to 100 bottom
 *
 * The basket/baseline is at the bottom of the panel.
 * This keeps the court visually intuitive and makes player placement easier.
 */
const COURT_SPOTS: CourtSpot[] = [
  // 1 – Point Guard: top of the key, center of the panel
  { key: "guardTop", label: "1", role: "Guard", x: 50, y: 70 },

  // 2 – Shooting Guard: left wing
  { key: "guardWing", label: "2", role: "Guard", x: 16, y: 55 },

  // 3 – Small Forward: right wing
  { key: "forwardSlot", label: "3", role: "Forward", x: 84, y: 38 },

  // 4 – Power Forward: left elbow / high post
  { key: "forwardBaseline", label: "4", role: "Forward", x: 20, y: 20 },

  // 5 – Center: paint, near the basket
  { key: "centerPaint", label: "5", role: "Center", x: 52, y: 16 },
];

function createCourtSvg() {
  return makeBasketballCourt({
    width: 510,
    type: "nba",
    halfCourt: true,
    horizontal: false,
    theme: "plain",
    trapezoid: false,
    ftCircleDashCount: 18,
    data: COURT_THEME,
  })
    .toString()
    // Strip hardcoded width/height so the SVG scales via CSS instead
    .replace(/\s+width="[^"]*"/, "")
    .replace(/\s+height="[^"]*"/, "")
    .replace(
      "<svg ",
      '<svg class="court-svg" role="img" aria-label="Clean NBA half court" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block;" ',
    )
    .replace("<rect ", '<rect rx="18" ry="18" ');
}

function getCourtAssignments(players: OptimizerPlayer[]) {
  const guards = players
    .filter((player) => player.position_group === "G")
    .sort((a, b) => b.projected_bpr - a.projected_bpr);
  const forwards = players
    .filter((player) => player.position_group === "F")
    .sort((a, b) => b.projected_bpr - a.projected_bpr);
  const centers = players
    .filter((player) => player.position_group === "C")
    .sort((a, b) => b.projected_bpr - a.projected_bpr);

  const assignments = [
    guards[0] ? { player: guards[0], spot: COURT_SPOTS[0] } : null,
    guards[1] ? { player: guards[1], spot: COURT_SPOTS[1] } : null,
    forwards[0] ? { player: forwards[0], spot: COURT_SPOTS[2] } : null,
    forwards[1] ? { player: forwards[1], spot: COURT_SPOTS[3] } : null,
    centers[0] ? { player: centers[0], spot: COURT_SPOTS[4] } : null,
  ].filter((assignment): assignment is { player: OptimizerPlayer; spot: CourtSpot } => Boolean(assignment));

  const starterIds = new Set(assignments.map(({ player }) => player.optimizer_player_id));
  return { assignments, starterIds };
}

function CourtLineup({
  players,
  additions,
  onDropCandidate,
}: {
  players: OptimizerPlayer[];
  additions: OptimizerPlayer[];
  onDropCandidate?: (playerId: string) => void;
}) {
  const { assignments, starterIds } = useMemo(() => getCourtAssignments(players), [players]);
  const bench = useMemo(
    () => players.filter((player) => !starterIds.has(player.optimizer_player_id)).sort((a, b) => b.projected_bpr - a.projected_bpr),
    [players, starterIds],
  );
  const additionIds = useMemo(() => new Set(additions.map((player) => player.optimizer_player_id)), [additions]);
  const courtSvg = useMemo(() => createCourtSvg(), []);

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    if (!onDropCandidate) return;
    event.preventDefault();
    const id = event.dataTransfer.getData("text/plain");
    if (id) onDropCandidate(id);
  }

  return (
    <div className="rounded border border-line bg-white p-4 shadow-soft">
      <div className="mb-3 text-sm font-semibold text-ink">Optimized Roster Court</div>
      <div
        // className="relative mx-auto aspect-[47/50] w-full overflow-hidden rounded border border-line bg-slate-950 shadow-inner"
        className="relative mx-auto h-[510px] w-full overflow-hidden rounded border border-line bg-slate-950 shadow-inner"
        style={{
          backgroundImage:
            "linear-gradient(90deg, rgba(148,163,184,.08) 1px, transparent 1px), linear-gradient(180deg, rgba(14,165,233,.16), rgba(16,185,129,.10) 54%, rgba(15,23,42,.18)), radial-gradient(circle at 50% 20%, rgba(255,255,255,.08), transparent 36%)",
          backgroundSize: "44px 44px, 100% 100%, 100% 100%",
        }}
        onDragOver={onDropCandidate ? (event) => event.preventDefault() : undefined}
        onDrop={onDropCandidate ? handleDrop : undefined}
      >
        <div
          className="pointer-events-none absolute inset-3 bottom-[-40px] z-0 opacity-95 drop-shadow-[0_0_8px_rgba(226,232,240,.16)]"
          aria-hidden="true"
          dangerouslySetInnerHTML={{ __html: courtSvg }}
        />

        <div className="absolute inset-0 z-10 bg-emerald-500/[.02]" />

        <div className="absolute inset-0 z-20">
          {assignments.map(({ player, spot }) => (
            <div
              key={player.optimizer_player_id}
              className="absolute w-32 -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${spot.x}%`, top: `${spot.y}%` }}
            >
              <CourtPlayer player={player} label={spot.label} role={spot.role} added={additionIds.has(player.optimizer_player_id)} />
            </div>
          ))}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-3 2xl:grid-cols-4">
        {bench.slice(0, 10).map((player) => (
          <div key={player.optimizer_player_id} className={clsx("flex items-center gap-2 rounded border border-line bg-panel px-2 py-1.5", additionIds.has(player.optimizer_player_id) && "border-emerald-300 bg-emerald-50 dark:bg-emerald-950")}>
            <PlayerAvatar player={player.player} size="sm" />
            <div className="min-w-0">
              <div className="truncate text-xs font-semibold text-ink">{player.player_name}</div>
              <div className="text-[11px] font-semibold text-slate-500">{player.position_group} | {player.projected_bpr.toFixed(2)}</div>
            </div>
          </div>
        ))}
      </div>
      {onDropCandidate ? (
        <div
          className="mt-3 rounded border border-dashed border-line bg-panel p-3 text-center text-sm font-semibold text-slate-500"
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
        >
          Drop players here to add them to the bench.
        </div>
      ) : null}
    </div>
  );
}

function CourtPlayer({ player, label, role, added }: { player: OptimizerPlayer; label: string; role: string; added: boolean }) {
  return (
    <div className={clsx("rounded-full border bg-white/95 px-2 py-1 text-center shadow-soft", added ? "border-emerald-500 ring-2 ring-emerald-300" : "border-white")}>
      <div className="mx-auto flex h-8 w-8 items-center justify-center rounded-full bg-panel">
        <PlayerAvatar player={player.player} size="sm" />
      </div>
      <div className="mt-0.5 text-[9px] font-bold text-sky-700">#{label} {role}</div>
      <div className="truncate text-[11px] font-bold text-slate-950">{player.player_name}</div>
      <div className="text-[10px] font-bold text-slate-600">{player.position_group} | {player.projected_bpr.toFixed(2)}</div>
    </div>
  );
}


function RecommendedSets({ sets, sortMode, compact = false }: { sets: RecommendationSet[]; sortMode: SortMode; compact?: boolean }) {
  if (!sets.length) return <EmptyResults text="Run the optimizer to see recommended roster sets." />;
  return (
    <div className={clsx("grid gap-3", !compact && "max-h-[535px] overflow-y-auto pr-1")}>
      {sets.map((set) => <SetCard key={set.id} set={set} sortMode={sortMode} compact={compact} />)}
    </div>
  );
}

function SetCard({ set, sortMode, compact = false }: { set: RecommendationSet; sortMode: SortMode; compact?: boolean }) {
  const metric = recommendationMetric(set, sortMode);
  return (
    <article className={clsx("rounded border border-line bg-white shadow-soft", compact ? "p-3" : "p-4")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recommended Set #{set.rank}</div>
          <div className="mt-1 text-sm font-semibold text-slate-600">Surfaced by {set.surfaced_by}</div>
        </div>
        <MetricCallout value={metric.value} label={metric.label} affects={metric.affects} compact={compact} />
      </div>
      <div className={clsx("mt-3 grid gap-2", compact ? "md:grid-cols-1 2xl:grid-cols-2" : "md:grid-cols-2")}>
        {set.selected_players.map((player) => <OptimizerPlayerRow key={player.optimizer_player_id} player={player} />)}
      </div>
      {!compact ? (
        <>
          <SetMetrics set={set} />
          <RatingDeltaGrid changes={set.rating_changes} />
        </>
      ) : null}
    </article>
  );
}

function IndividualFits({ fits, sortMode }: { fits: Record<PositionGroup, IndividualFitRecommendation[]>; sortMode: SortMode }) {
  const [position, setPosition] = useState<PositionGroup>("G");
  const rankedFits = rankIndividualFits(fits[position], sortMode).slice(0, 10);
  return (
    <div className="grid gap-3">
      <div className="rounded border border-line bg-white p-3 shadow-soft">
        <div className="grid grid-cols-3 rounded border border-line bg-panel p-1">
          {POSITION_GROUPS.map((group) => (
            <button
              key={group}
              type="button"
              onClick={() => setPosition(group)}
              className={
                position === group
                  ? "h-9 rounded bg-emerald-600 px-3 text-sm font-semibold text-white dark:bg-emerald-500 dark:text-slate-950"
                  : "h-9 rounded px-3 text-sm font-semibold text-slate-600 hover:bg-surface dark:text-slate-300"
              }
            >
              {positionLabel(group)}
            </button>
          ))}
        </div>
      </div>
      <div className="rounded border border-line bg-white p-4 shadow-soft">
        <div className="mb-3 text-sm font-semibold text-ink">Top {positionLabel(position)} Fits</div>
        <div className="grid gap-2">
          {rankedFits.map((fit) => <IndividualFitRow key={fit.player.optimizer_player_id} fit={fit} sortMode={sortMode} />)}
          {!rankedFits.length ? <div className="text-sm font-semibold text-slate-500">No fits found for this position.</div> : null}
        </div>
      </div>
    </div>
  );
}

function HiddenFits({ fits, sortMode }: { fits: IndividualFitRecommendation[]; sortMode: SortMode }) {
  if (!fits.length) return <EmptyResults text="No hidden fits found for this roster state." />;
  return <div className="grid gap-2">{fits.map((fit) => <IndividualFitRow key={fit.player.optimizer_player_id} fit={fit} sortMode={sortMode} />)}</div>;
}

function SinglePlayerPane({
  result,
  sortModeValue,
  categoryFilter,
  onSortModeChange,
  onCategoryFilterChange,
  sortMode,
  candidates,
  currentRoster,
  currentRatings,
}: {
  result: OptimizerResult | null;
  sortModeValue: SortMode;
  categoryFilter: "all" | SkillKey;
  onSortModeChange: (mode: SortMode) => void;
  onCategoryFilterChange: (category: "all" | SkillKey) => void;
  sortMode: SortMode;
  candidates: OptimizerPlayer[];
  currentRoster: OptimizerPlayer[];
  currentRatings: TeamRatings;
}) {
  const [position, setPosition] = useState<"all" | PositionGroup>("all");
  const fits = useMemo(() => {
    const source = result?.individual_fits ?? buildIndividualFits(currentRoster, candidates, currentRatings);
    const all = POSITION_GROUPS.flatMap((group) => source[group]);
    return rankIndividualFits(position === "all" ? all : all.filter((fit) => fit.position_group === position), sortMode);
  }, [candidates, currentRatings, currentRoster, position, result?.individual_fits, sortMode]);
  return (
    <div className="space-y-3">
      <OptimizerControls
        sortMode={sortModeValue}
        categoryFilter={categoryFilter}
        onSortModeChange={onSortModeChange}
        onCategoryFilterChange={onCategoryFilterChange}
        disabled={false}
      />
      <div className="rounded border border-line bg-white shadow-soft">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-panel px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-ink">Single Player Optimization</div>
            <div className="mt-1 text-xs text-slate-500">Ranks one-player additions by marginal team impact.</div>
          </div>
          <Select
            value={position}
            onChange={(value) => setPosition(value as "all" | PositionGroup)}
            options={[{ value: "all", label: "All Positions" }, ...POSITION_GROUPS.map((group) => ({ value: group, label: positionLabel(group) }))]}
          />
        </div>
        <div className="max-h-[720px] overflow-y-auto p-4">
          <div className="grid gap-2">
            {fits.slice(0, 40).map((fit) => <IndividualFitRow key={fit.player.optimizer_player_id} fit={fit} sortMode={sortMode} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

function ManualOptimizerPane({
  candidates,
  currentRoster,
  currentRatings,
  manualIds,
  onManualIdsChange,
  sortModeValue,
  categoryFilter,
  onSortModeChange,
  onCategoryFilterChange,
  sortMode,
}: {
  candidates: OptimizerPlayer[];
  currentRoster: OptimizerPlayer[];
  currentRatings: TeamRatings;
  manualIds: string[];
  onManualIdsChange: (ids: string[]) => void;
  sortModeValue: SortMode;
  categoryFilter: "all" | SkillKey;
  onSortModeChange: (mode: SortMode) => void;
  onCategoryFilterChange: (category: "all" | SkillKey) => void;
  sortMode: SortMode;
}) {
  const [position, setPosition] = useState<"all" | PositionGroup>("all");
  const [sourceFilter, setSourceFilter] = useState<"all" | "transfer" | "hs_recruit">("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const selected = candidates.filter((candidate) => manualIds.includes(candidate.optimizer_player_id));
  const selectedIds = new Set(manualIds);
  const manualRoster = [...currentRoster, ...selected];
  const finalRatings = calculateTeamRatings(manualRoster);
  const changes = ratingChanges(currentRatings, finalRatings);
  const candidateFits = useMemo(() => {
    const fits = buildIndividualFits(currentRoster, candidates, currentRatings);
    return new Map(POSITION_GROUPS.flatMap((group) => fits[group]).map((fit) => [fit.player.optimizer_player_id, fit]));
  }, [candidates, currentRatings, currentRoster]);
  const manualSet = solutionToRecommendationSet({
    selectedPlayers: selected,
    currentRoster,
    currentRatings,
    currentTotal: totalRating(currentRatings),
    currentWeakest: weakestRating(currentRatings),
    rank: 1,
    surfacedBy: "Manual selection",
  });
  const normalizedQuery = query.trim().toLowerCase();
  const visibleFits = rankIndividualFits(Array.from(candidateFits.values()), sortMode)
    .filter((fit) => !selectedIds.has(fit.player.optimizer_player_id))
    .filter((fit) => position === "all" || fit.player.position_group === position)
    .filter((fit) => sourceFilter === "all" || fit.player.source_type === sourceFilter)
    .filter((fit) => !normalizedQuery || fit.player.player_name.toLowerCase().includes(normalizedQuery) || displayOptimizerTeam(fit.player.player).toLowerCase().includes(normalizedQuery));
  const totalPages = Math.max(1, Math.ceil(visibleFits.length / MANUAL_CANDIDATES_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * MANUAL_CANDIDATES_PER_PAGE;
  const pageFits = visibleFits.slice(pageStart, pageStart + MANUAL_CANDIDATES_PER_PAGE);

  useEffect(() => {
    setPage(1);
  }, [normalizedQuery, position, sourceFilter, sortMode]);

  function addPlayer(playerId: string) {
    if (selectedIds.has(playerId)) return;
    onManualIdsChange([...manualIds, playerId]);
  }

  function removePlayer(playerId: string) {
    onManualIdsChange(manualIds.filter((id) => id !== playerId));
  }

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(420px,.85fr)_minmax(720px,1.15fr)]">
      <div className="self-start space-y-3">
        <OptimizerControls
          sortMode={sortModeValue}
          categoryFilter={categoryFilter}
          onSortModeChange={onSortModeChange}
          onCategoryFilterChange={onCategoryFilterChange}
          disabled={false}
        />
        <div className="self-start rounded border border-line bg-white shadow-soft">
          <div className="border-b border-line bg-panel px-4 py-3">
            <div className="text-sm font-semibold text-ink">Manual Candidate Pool</div>
            <div className="mt-1 text-xs text-slate-500">Drag ranked fits onto the court or bench, or click Add.</div>
          </div>
          <div className="grid gap-2 border-b border-line bg-panel px-3 py-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search ranked fits..."
              className="h-9 rounded border border-line bg-white px-3 text-sm font-semibold text-ink outline-none focus:border-ink dark:bg-panel"
            />
            <div className="grid gap-2 sm:grid-cols-2">
              <Select
                value={sourceFilter}
                onChange={(value) => setSourceFilter(value as "all" | "transfer" | "hs_recruit")}
                options={[
                  { value: "all", label: "Transfers + HS" },
                  { value: "transfer", label: "Transfers" },
                  { value: "hs_recruit", label: "High School" },
                ]}
              />
              <Select
                value={position}
                onChange={(value) => setPosition(value as "all" | PositionGroup)}
                options={[{ value: "all", label: "All Positions" }, ...POSITION_GROUPS.map((group) => ({ value: group, label: positionLabel(group) }))]}
              />
            </div>
          </div>
          <div className="max-h-[560px] overflow-y-auto divide-y divide-line">
            {pageFits.map((fit) => {
              const candidate = fit.player;
              return (
              <div
                key={candidate.optimizer_player_id}
                draggable
                onDragStart={(event) => event.dataTransfer.setData("text/plain", candidate.optimizer_player_id)}
                className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 px-3 py-2 hover:bg-panel"
              >
                <OptimizerPlayerRow player={candidate} />
                <MetricCallout {...individualMetric(fit, sortMode)} compact hideAffects />
                <button
                  type="button"
                  onClick={() => addPlayer(candidate.optimizer_player_id)}
                  className="rounded border border-line bg-panel px-2 py-1 text-xs font-bold text-slate-700"
                >
                  Add
                </button>
              </div>
              );
            })}
            {!visibleFits.length ? <div className="px-3 py-6 text-sm font-semibold text-slate-500">No ranked fits match these filters.</div> : null}
          </div>
          {visibleFits.length ? (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-panel px-3 py-2 text-xs font-semibold text-slate-500">
              <span>
                Showing {pageStart + 1}-{Math.min(pageStart + MANUAL_CANDIDATES_PER_PAGE, visibleFits.length)} of {visibleFits.length}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                  disabled={currentPage === 1}
                  className="rounded border border-line bg-white px-2 py-1 font-bold text-slate-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-panel"
                >
                  Prev
                </button>
                <span className="tabular-nums">Page {currentPage} / {totalPages}</span>
                <button
                  type="button"
                  onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                  disabled={currentPage === totalPages}
                  className="rounded border border-line bg-white px-2 py-1 font-bold text-slate-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-panel"
                >
                  Next
                </button>
              </div>
            </div>
          ) : null}
        </div>
        <div className="rounded border border-line bg-white p-4 shadow-soft">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold text-ink">Manual Additions ({selected.length})</div>
            {selected.length ? (
              <button type="button" onClick={() => onManualIdsChange([])} className="text-xs font-semibold text-rose-600">
                Clear
              </button>
            ) : null}
          </div>
          <div className="max-h-[340px] overflow-y-auto">
            <div className="grid gap-2">
              {selected.map((player) => (
                <div key={player.optimizer_player_id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded border border-line bg-panel px-3 py-2">
                  <OptimizerPlayerRow player={player} />
                  <button type="button" onClick={() => removePlayer(player.optimizer_player_id)} className="rounded border border-line bg-white px-2 py-1 text-xs font-bold text-rose-600">
                    Remove
                  </button>
                </div>
              ))}
              {!selected.length ? <div className="text-sm text-slate-500">No manual additions selected.</div> : null}
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div className="mx-auto w-full max-w-[580px]">
          <CourtLineup players={manualRoster} additions={selected} onDropCandidate={addPlayer} />
        </div>

        <TeamComparisonCard baseline={currentRatings} manualRatings={finalRatings} invalid={false} />

        <article className="rounded border border-line bg-white p-4 shadow-soft">
          <div>
            <div>
              <div className="text-sm font-semibold text-ink">Manual Roster Impact</div>
              <div className="mt-1 text-xs text-slate-500">No roster or positional limits are applied in manual mode.</div>
            </div>
          </div>
          <SetMetrics set={manualSet} />
          <RatingDeltaGrid changes={changes} />
        </article>
      </div>

    </div>
  );
}

function IndividualFitRow({ fit, sortMode }: { fit: IndividualFitRecommendation; sortMode: SortMode }) {
  const metric = individualMetric(fit, sortMode);
  return (
    <div className="grid gap-3 rounded border border-line bg-white px-3 py-2 shadow-soft md:grid-cols-[1fr_auto] md:items-center">
      <OptimizerPlayerRow player={fit.player} />
      <div className="flex flex-wrap items-center gap-3 md:justify-end">
        <MetricCallout value={metric.value} label={metric.label} affects={metric.affects} compact hideAffects />
        <div className="text-xs font-semibold text-slate-500">
          Total {formatDelta(fit.individual_total_gain)} | Weak {formatDelta(fit.individual_weakest_gain)}
        </div>
      </div>
    </div>
  );
}

function OptimizerPlayerRow({ player }: { player: OptimizerPlayer }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <PlayerAvatar player={player.player} size="sm" />
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-ink">{player.player_name}</div>
        <div className="mt-1 truncate text-xs text-slate-500">
          {player.position_group} | {displayOptimizerTeam(player.player)} | BPR {player.projected_bpr.toFixed(2)}
        </div>
        <div className="mt-1">
          <SourceBadge source={player.player.player_source} />
        </div>
      </div>
    </div>
  );
}

function SetMetrics({ set }: { set: RecommendationSet }) {
  return (
    <div className="mt-3 grid grid-cols-3 gap-2">
      <MiniMetric label="Total Gain" value={formatDelta(set.total_gain)} />
      <MiniMetric label="Weakest Gain" value={formatDelta(set.weakest_gain)} />
      <MiniMetric label="Added BPR" value={set.added_projected_bpr.toFixed(2)} />
    </div>
  );
}

function RatingDeltaGrid({ changes }: { changes: TeamRatings }) {
  return (
    <div className="mt-3 grid gap-2 md:grid-cols-5">
      {SKILL_KEYS.map((key) => (
        <div key={key} className="rounded border border-line bg-panel px-2 py-2 text-center">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{SKILL_LABELS[key]}</div>
          <div className={clsx("mt-1 text-sm font-bold tabular-nums", changes[key] >= 0 ? "text-emerald-600" : "text-rose-600")}>{formatDelta(changes[key])}</div>
        </div>
      ))}
    </div>
  );
}

function RatingSummary({ title, ratings }: { title: string; ratings: TeamRatings }) {
  return (
    <div className="rounded border border-line bg-white p-4 shadow-soft">
      <div className="mb-2 text-sm font-semibold text-ink">{title}</div>
      <div className="grid gap-2">
        {SKILL_KEYS.map((key) => (
          <div key={key} className="flex items-center justify-between rounded border border-line bg-panel px-2.5 py-1.5 text-xs">
            <span className="font-semibold text-slate-600">{SKILL_LABELS[key]}</span>
            <span className="font-bold tabular-nums text-ink">{ratings[key].toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResultTabs({ active, onChange }: { active: ResultTab; onChange: (tab: ResultTab) => void }) {
  return (
    <div className="grid grid-cols-2 rounded border border-line bg-panel p-1">
      {[
        ["sets", "Recommended Sets"],
        ["individual", "Individual Fits"],
      ].map(([value, label]) => (
        <button
          key={value}
          type="button"
          onClick={() => onChange(value as ResultTab)}
          className={active === value ? "h-9 rounded bg-emerald-600 px-3 text-sm font-semibold text-white dark:bg-emerald-500 dark:text-slate-950" : "h-9 rounded px-3 text-sm font-semibold text-slate-600 hover:bg-surface dark:text-slate-300"}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function WarningPanel({ message }: { message: string }) {
  return (
    <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm font-semibold text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-200">
      <div className="flex gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{message}</span>
      </div>
    </div>
  );
}

function Select({ value, options, disabled = false, onChange }: { value: string; options: Array<{ value: string; label: string }>; disabled?: boolean; onChange: (value: string) => void }) {
  return (
    <label className="relative block">
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full appearance-none rounded border border-line bg-panel px-3 pr-8 text-sm font-semibold text-slate-700 outline-none focus:border-ink disabled:opacity-50 dark:text-slate-200"
      >
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
    </label>
  );
}

function MetricCallout({ value, label, affects, compact = false, hideAffects = false }: { value: number; label: string; affects: string; compact?: boolean; hideAffects?: boolean }) {
  return (
    <div className={clsx("rounded border border-emerald-300 bg-emerald-50 text-right dark:border-emerald-700 dark:bg-emerald-950", compact ? "min-w-[82px] px-1.5 py-1" : "px-3 py-2")}>
      <div className={clsx("font-bold tabular-nums text-emerald-700 dark:text-emerald-200", compact ? "text-xs" : "text-lg")}>{formatDelta(value)}</div>
      <div className={clsx("font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300", compact ? "text-[8px]" : "text-[10px]")}>{label}</div>
      {hideAffects ? null : !compact ? <div className="text-[10px] text-emerald-700 dark:text-emerald-300">Affects: {affects}</div> : <div className="truncate text-[8px] text-emerald-700 dark:text-emerald-300">{affects}</div>}
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-panel px-2 py-2 text-center">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-bold tabular-nums text-ink">{value}</div>
    </div>
  );
}

function EmptyResults({ text }: { text: string }) {
  return <div className="rounded border border-line bg-white p-6 text-center text-sm font-semibold text-slate-500 shadow-soft">{text}</div>;
}

function recommendationMetric(set: RecommendationSet, sortMode: SortMode) {
  if (sortMode === "total_gain") return { value: set.total_gain, label: "Total Rating", affects: "Overall roster profile" };
  if (sortMode === "weakest_gain") return { value: set.weakest_gain, label: "Weakest Category", affects: SKILL_LABELS[set.best_affected_category] };
  if (sortMode === "added_bpr") return { value: set.added_projected_bpr, label: "Added BPR", affects: "Projected talent level" };
  if (SKILL_KEYS.includes(sortMode as SkillKey)) return { value: set.rating_changes[sortMode as SkillKey], label: SKILL_LABELS[sortMode as SkillKey], affects: `${SKILL_LABELS[sortMode as SkillKey]} percentile` };
  return { value: set.total_gain, label: "Total Rating", affects: SKILL_LABELS[set.best_affected_category] };
}

function individualMetric(fit: IndividualFitRecommendation, sortMode: SortMode) {
  if (sortMode === "total_gain") return { value: fit.individual_total_gain, label: "Total Rating", affects: "Overall roster profile" };
  if (sortMode === "weakest_gain") return { value: fit.individual_weakest_gain, label: "Weakest Category", affects: SKILL_LABELS[fit.best_improved_category] };
  if (sortMode === "added_bpr") return { value: fit.projected_bpr, label: "Projected BPR", affects: "Projected talent level" };
  if (SKILL_KEYS.includes(sortMode as SkillKey)) return { value: fit.rating_changes_if_added[sortMode as SkillKey], label: SKILL_LABELS[sortMode as SkillKey], affects: `${SKILL_LABELS[sortMode as SkillKey]} percentile` };
  return { value: fit.individual_total_gain, label: "Total Rating", affects: SKILL_LABELS[fit.best_improved_category] };
}

function validateRosterState(rosterSize: number, currentCounts: TargetCounts, targetCounts: TargetCounts) {
  const targetTotal = targetCounts.G + targetCounts.F + targetCounts.C;
  if (targetTotal !== MAX_ROSTER_SIZE) return `Target roster counts must equal 15. Current target total is ${targetTotal}.`;
  if (rosterSize > MAX_ROSTER_SIZE) {
    return `Your roster currently has ${rosterSize} players. Remove ${rosterSize - MAX_ROSTER_SIZE} player(s) to calculate ratings and run the optimizer.`;
  }
  for (const position of POSITION_GROUPS) {
    if (currentCounts[position] > targetCounts[position]) {
      return `Too many ${positionLabel(position).toLowerCase()} selected. Your target allows ${targetCounts[position]}, but your current roster has ${currentCounts[position]}.`;
    }
  }
  return null;
}

function getGlpk() {
  glpkPromise ??= GLPK();
  return glpkPromise;
}

function polygonPointArray(values: number[], center: number, maxRadius: number, angles: number[]) {
  return values.map((value, index) => polarPoint(center, center, maxRadius * (Math.max(0, Math.min(100, value)) / 100), angles[index]));
}

function pointsToString(points: Array<{ x: number; y: number }>) {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

function polarPoint(centerX: number, centerY: number, radius: number, angleDegrees: number) {
  const angle = (Math.PI / 180) * angleDegrees;
  return {
    x: Number((centerX + radius * Math.cos(angle)).toFixed(3)),
    y: Number((centerY + radius * Math.sin(angle)).toFixed(3)),
  };
}

function positionLabel(position: PositionGroup) {
  return position === "G" ? "Guards" : position === "F" ? "Forwards" : "Centers";
}

function radarShortLabel(key: SkillKey) {
  if (key === "rim_protection_percentile") return "Rim Prot.";
  return SKILL_LABELS[key];
}

function formatDelta(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function normalizeName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}
