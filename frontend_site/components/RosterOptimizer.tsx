"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import GLPK, { type GLPK as GLPKInstance, type LP } from "glpk.js";
import { Activity, AlertTriangle, ArrowRight, ChevronDown, Loader2, RotateCcw, SlidersHorizontal, Trophy } from "lucide-react";
import clsx from "clsx";
import { players } from "@/data/players";
import { getHsPlayers, getPortalPlayers, getTeamPlayers, getTeams } from "@/lib/data";
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
  isValidTargetTotal,
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
type ResultTab = "sets" | "individual" | "hidden";

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
const OBJECTIVE_VARIANTS: Array<{ id: string; label: string; skill?: SkillKey; weakness?: boolean; balanced?: boolean }> = [
  { id: "total", label: "Total contribution" },
  { id: "spacing", label: "Spacing specialist", skill: "spacing_percentile" },
  { id: "facilitating", label: "Facilitating specialist", skill: "facilitating_percentile" },
  { id: "rim", label: "Rim protection specialist", skill: "rim_protection_percentile" },
  { id: "defense", label: "Defense specialist", skill: "defense_percentile" },
  { id: "finishing", label: "Finishing specialist", skill: "finishing_percentile" },
  { id: "weakness", label: "Current weakness", weakness: true },
  { id: "balanced", label: "Weakness balanced", balanced: true },
];
const ROSTER_MANAGEMENT_STORAGE_KEY = "roster-lab-roster-management-state";

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
    () => payload?.playerIds.map((id) => playerById.get(id)).filter((player): player is NonNullable<typeof player> => Boolean(player)) ?? [],
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

  const effectiveSortMode: SortMode =
    (sortMode === "total_gain" || sortMode === "weakest_gain") && categoryFilter !== "all"
      ? categoryFilter
      : sortMode;
  const fullSetSortMode: SortMode = view === "sets" ? "overall" : effectiveSortMode;
  const sortedSets = useMemo(() => (result ? rankRecommendationSets(result.recommended_sets, fullSetSortMode) : []), [fullSetSortMode, result]);
  const sortedHiddenFits = useMemo(() => (result ? rankIndividualFits(result.hidden_fits, effectiveSortMode) : []), [effectiveSortMode, result]);

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
        candidates,
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
      const next = { ...counts, [position]: counts[position] + delta };
      const others = POSITION_GROUPS.filter((group) => group !== position);
      if (delta > 0) {
        const donor = [...others].sort((left, right) => next[right] - next[left])[0];
        if (!donor || next[donor] <= 0) return counts;
        next[donor] -= 1;
      } else {
        const recipient = [...others].sort((left, right) => next[right] - next[left])[0];
        if (!recipient) return counts;
        next[recipient] += 1;
      }
      if (!isValidTargetTotal(next)) return counts;
      return next;
    });
    setResult(null);
  }

  if (!payload) {
    return (
      <div className="rounded border border-line bg-white p-6 shadow-soft">
        <div className="text-lg font-semibold text-ink">No roster loaded</div>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
          Open Roster Management, make any additions or removals, then click Load to Optimizer.
        </p>
        <Link href="/simulator" className="mt-4 inline-flex h-10 items-center rounded bg-emerald-600 px-4 text-sm font-semibold text-white">
          Go to Roster Management
        </Link>
      </div>
    );
  }

  return (
    <section className="space-y-4">
      <div className="-mt-20 mb-10 flex justify-end gap-2">
        <Link href="/simulator" className="inline-flex h-9 items-center justify-center rounded border border-line bg-panel px-4 text-sm font-semibold text-slate-700">
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
                <TargetControls targetCounts={targetCounts} currentCounts={currentCounts} onChange={updateTarget} rosterSize={loadedPlayers.length} />
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
                {resultTab === "hidden" ? <HiddenFits fits={sortedHiddenFits} sortMode={effectiveSortMode} /> : null}
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
  const cappedCandidates = POSITION_GROUPS.flatMap((position) =>
    candidates
      .filter((candidate) => neededPositions.includes(candidate.position_group) && candidate.position_group === position)
      .sort((left, right) => candidateContribution(right) - candidateContribution(left) || right.projected_bpr - left.projected_bpr)
      .slice(0, TOP_N_CANDIDATES_PER_POSITION),
  );
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
  const weakestCurrentSkill = SKILL_KEYS.map((key) => ({ key, value: currentRatings[key] })).sort((left, right) => left.value - right.value)[0]?.key;
  const bestCurrentSkill = Math.max(...SKILL_KEYS.map((key) => currentRatings[key]));

  for (const variant of OBJECTIVE_VARIANTS) {
    const exclusions: string[][] = [];
    for (let iteration = 0; iteration < 10; iteration += 1) {
      const objectiveSkill = variant.weakness ? weakestCurrentSkill : variant.skill;
      const objective = cappedCandidates.map((candidate) => {
        if (variant.balanced) {
          return SKILL_KEYS.reduce((sum, key) => sum + candidate.projected_bpr * candidate[key] * Math.max(bestCurrentSkill - currentRatings[key], 0), 0);
        }
        return candidateContribution(candidate, objectiveSkill);
      });
      const selected = await solveSingleGlpkModel(glpk, cappedCandidates, openSlots, objective, exclusions, `${variant.id}-${iteration}`);
      if (!selected.length) break;
      const signature = selected.map((candidate) => candidate.optimizer_player_id).sort().join("|");
      exclusions.push(selected.map((candidate) => candidate.optimizer_player_id));
      if (seen.has(signature)) continue;
      seen.add(signature);
      sets.push(
        solutionToRecommendationSet({
          selectedPlayers: selected,
          currentRoster,
          currentRatings,
          currentTotal,
          currentWeakest,
          rank: sets.length + 1,
          surfacedBy: variant.label,
        }),
      );
    }
  }

  if (!sets.length) throw new Error("No valid recommendation found for the current roster constraints.");
  const rankedSets = rankRecommendationSets(sets, "overall").map((set, index) => ({ ...set, rank: index + 1 }));
  const individualFits = buildIndividualFits(currentRoster, cappedCandidates, currentRatings);
  const hiddenFits = buildHiddenFits(individualFits, cappedCandidates, "overall");

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
}: {
  targetCounts: TargetCounts;
  currentCounts: TargetCounts;
  rosterSize: number;
  onChange: (position: PositionGroup, delta: number) => void;
}) {
  return (
    <div className="grid gap-2">
        <CountPill label="Roster Size" current={rosterSize} target={MAX_ROSTER_SIZE} />
        {POSITION_GROUPS.map((position) => (
          <div key={position} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded border border-line bg-white px-3 py-2 dark:bg-panel">
            <CountPill label={positionLabel(position)} current={currentCounts[position]} target={targetCounts[position]} compact />
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => onChange(position, -1)} className="h-8 w-8 rounded border border-line bg-panel text-sm font-semibold">-</button>
              <button type="button" onClick={() => onChange(position, 1)} className="h-8 w-8 rounded border border-line bg-panel text-sm font-semibold">+</button>
            </div>
          </div>
        ))}
    </div>
  );
}

function CountPill({ label, current, target, compact = false }: { label: string; current: number; target: number; compact?: boolean }) {
  const tone = current > target ? "text-rose-600" : current === target ? "text-emerald-700" : "text-slate-600";
  const displayLabel = compact ? label.replace("Guards", "Guard").replace("Forwards", "Forward").replace("Centers", "Center") : label;
  return (
    <div className={clsx("flex items-center justify-between gap-3", compact ? "text-sm" : "rounded border border-line bg-white px-3 py-2 text-sm dark:bg-panel")}>
      <span className="font-semibold text-slate-600">{displayLabel}</span>
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
                {baseline[key].toFixed(1)}
                {final != null ? (
                  <>
                    <ArrowRight className="h-3.5 w-3.5 text-slate-500" />
                    {final.toFixed(1)}
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

function CourtLineup({
  players,
  additions,
  onDropCandidate,
}: {
  players: OptimizerPlayer[];
  additions: OptimizerPlayer[];
  onDropCandidate?: (playerId: string) => void;
}) {
  const guards = players.filter((player) => player.position_group === "G").sort((a, b) => b.projected_bpr - a.projected_bpr);
  const forwards = players.filter((player) => player.position_group === "F").sort((a, b) => b.projected_bpr - a.projected_bpr);
  const centers = players.filter((player) => player.position_group === "C").sort((a, b) => b.projected_bpr - a.projected_bpr);
  const starters = [guards[0], guards[1], forwards[0], forwards[1], centers[0]].filter(Boolean);
  const starterIds = new Set(starters.map((player) => player.optimizer_player_id));
  const bench = players.filter((player) => !starterIds.has(player.optimizer_player_id)).sort((a, b) => b.projected_bpr - a.projected_bpr);
  const additionIds = new Set(additions.map((player) => player.optimizer_player_id));
  const spots = [
    { label: "1", role: "Guard", className: "left-1/2 top-[7%] -translate-x-1/2" },
    { label: "2", role: "Guard", className: "left-[10%] top-[31%]" },
    { label: "3", role: "Forward", className: "right-[8%] top-[64%]" },
    { label: "4", role: "Forward", className: "left-[18%] top-[65%]" },
    { label: "5", role: "Center", className: "right-[34%] top-[44%]" },
  ];
  return (
    <div className="rounded border border-line bg-white p-4 shadow-soft">
      <div className="mb-3 text-sm font-semibold text-ink">Optimized Roster Court</div>
      <div
        className="relative mx-auto h-[400px] max-w-2xl overflow-hidden rounded border border-line bg-[#e5c17d]"
        onDragOver={onDropCandidate ? (event) => event.preventDefault() : undefined}
        onDrop={
          onDropCandidate
            ? (event) => {
                event.preventDefault();
                const id = event.dataTransfer.getData("text/plain");
                if (id) onDropCandidate(id);
              }
            : undefined
        }
      >
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(255,255,255,.12)_1px,transparent_1px)] bg-[length:42px_42px]" />
        <div className="absolute left-1/2 top-12 h-[390px] w-[560px] -translate-x-1/2 rounded-t-full border-[5px] border-white/90" />
        <div className="absolute left-1/2 top-28 h-48 w-48 -translate-x-1/2 rounded-t-full border-[5px] border-white/90" />
        <div className="absolute left-1/2 top-28 h-40 w-40 -translate-x-1/2 rounded-full border-[5px] border-white/90" />
        <div className="absolute left-1/2 bottom-0 h-40 w-52 -translate-x-1/2 border-x-[5px] border-t-[5px] border-white/90" />
        <div className="absolute bottom-24 left-1/2 h-20 w-20 -translate-x-1/2 rounded-full border-[5px] border-white/90" />
        {spots.map((spot, index) => {
          const player = starters[index];
          return player ? (
            <div key={spot.label} className={clsx("absolute w-32", spot.className)}>
              <CourtPlayer player={player} label={spot.label} role={spot.role} added={additionIds.has(player.optimizer_player_id)} />
            </div>
          ) : null;
        })}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-3 2xl:grid-cols-4">
        {bench.slice(0, 10).map((player) => (
          <div key={player.optimizer_player_id} className={clsx("flex items-center gap-2 rounded border border-line bg-panel px-2 py-1.5", additionIds.has(player.optimizer_player_id) && "border-emerald-300 bg-emerald-50 dark:bg-emerald-950")}>
            <PlayerAvatar player={player.player} size="sm" />
            <div className="min-w-0">
              <div className="truncate text-xs font-semibold text-ink">{player.player_name}</div>
              <div className="text-[11px] font-semibold text-slate-500">{player.position_group} | {player.projected_bpr.toFixed(1)}</div>
            </div>
          </div>
        ))}
      </div>
      {onDropCandidate ? (
        <div
          className="mt-3 rounded border border-dashed border-line bg-panel p-3 text-center text-sm font-semibold text-slate-500"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const id = event.dataTransfer.getData("text/plain");
            if (id) onDropCandidate(id);
          }}
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
      <div className="text-[10px] font-bold text-slate-600">{player.position_group} | {player.projected_bpr.toFixed(1)}</div>
    </div>
  );
}

function RecommendedSets({ sets, sortMode, compact = false }: { sets: RecommendationSet[]; sortMode: SortMode; compact?: boolean }) {
  if (!sets.length) return <EmptyResults text="Run the optimizer to see recommended roster sets." />;
  return <div className="grid gap-3">{sets.map((set) => <SetCard key={set.id} set={set} sortMode={sortMode} compact={compact} />)}</div>;
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
                <MetricCallout {...individualMetric(fit, sortMode)} compact />
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
      </div>

      <div className="space-y-4">
        <CourtLineup players={manualRoster} additions={selected} onDropCandidate={addPlayer} />
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
        <div className="rounded border border-line bg-white p-4 shadow-soft">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold text-ink">Manual Additions ({selected.length})</div>
            {selected.length ? (
              <button type="button" onClick={() => onManualIdsChange([])} className="text-xs font-semibold text-rose-600">
                Clear
              </button>
            ) : null}
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {selected.map((player) => (
              <div key={player.optimizer_player_id} className="grid grid-cols-[1fr_auto] items-center gap-2 rounded border border-line bg-panel px-3 py-2">
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
  );
}

function IndividualFitRow({ fit, sortMode }: { fit: IndividualFitRecommendation; sortMode: SortMode }) {
  const metric = individualMetric(fit, sortMode);
  return (
    <div className="grid gap-3 rounded border border-line bg-white px-3 py-2 shadow-soft md:grid-cols-[1fr_auto] md:items-center">
      <OptimizerPlayerRow player={fit.player} />
      <div className="flex flex-wrap items-center gap-3 md:justify-end">
        <MetricCallout value={metric.value} label={metric.label} affects={metric.affects} compact />
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
          {player.position_group} | {displayOptimizerTeam(player.player)} | BPR {player.projected_bpr.toFixed(1)}
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
      <MiniMetric label="Added BPR" value={set.added_projected_bpr.toFixed(1)} />
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
            <span className="font-bold tabular-nums text-ink">{ratings[key].toFixed(1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResultTabs({ active, onChange }: { active: ResultTab; onChange: (tab: ResultTab) => void }) {
  return (
    <div className="grid grid-cols-3 rounded border border-line bg-panel p-1">
      {[
        ["sets", "Recommended Sets"],
        ["individual", "Individual Fits"],
        ["hidden", "Hidden Fits"],
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

function MetricCallout({ value, label, affects, compact = false }: { value: number; label: string; affects: string; compact?: boolean }) {
  return (
    <div className={clsx("rounded border border-emerald-300 bg-emerald-50 text-right dark:border-emerald-700 dark:bg-emerald-950", compact ? "min-w-[82px] px-1.5 py-1" : "px-3 py-2")}>
      <div className={clsx("font-bold tabular-nums text-emerald-700 dark:text-emerald-200", compact ? "text-xs" : "text-lg")}>{formatDelta(value)}</div>
      <div className={clsx("font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300", compact ? "text-[8px]" : "text-[10px]")}>{label}</div>
      {!compact ? <div className="text-[10px] text-emerald-700 dark:text-emerald-300">Affects: {affects}</div> : <div className="truncate text-[8px] text-emerald-700 dark:text-emerald-300">{affects}</div>}
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
  if (!isValidTargetTotal(targetCounts)) return "Target roster counts cannot exceed 15.";
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
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}

function normalizeName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}
