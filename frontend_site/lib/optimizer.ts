import type { Player } from "@/data/players";
import { getTopPlaytypes } from "@/lib/data";

export type PositionGroup = "G" | "F" | "C";
export type SkillKey =
  | "spacing_percentile"
  | "facilitating_percentile"
  | "rim_protection_percentile"
  | "defense_percentile"
  | "finishing_percentile";

export type TeamRatings = Record<SkillKey, number>;

export type OptimizerPlayer = {
  optimizer_player_id: string;
  allyears_pid: string | null;
  player_key: string | null;
  source_type: "transfer" | "hs_recruit" | "returning";
  player: Player;
  player_name: string;
  position_group: PositionGroup;
  projected_bpr: number;
  spacing_percentile: number;
  facilitating_percentile: number;
  rim_protection_percentile: number;
  defense_percentile: number;
  finishing_percentile: number;
};

export type TargetCounts = Record<PositionGroup, number>;

export type RecommendationSet = {
  id: string;
  selected_players: OptimizerPlayer[];
  final_ratings: TeamRatings;
  rating_changes: TeamRatings;
  final_total_rating: number;
  final_weakest_rating: number;
  added_projected_bpr: number;
  total_gain: number;
  weakest_gain: number;
  best_affected_category: SkillKey;
  best_category_gain: number;
  rank: number;
  surfaced_by: string;
};

export type IndividualFitRecommendation = {
  player: OptimizerPlayer;
  position_group: PositionGroup;
  final_ratings_if_added: TeamRatings;
  rating_changes_if_added: TeamRatings;
  individual_total_gain: number;
  individual_weakest_gain: number;
  projected_bpr: number;
  best_improved_category: SkillKey;
  best_improved_category_gain: number;
};

export type OptimizerResult = {
  recommended_sets: RecommendationSet[];
  individual_fits: Record<PositionGroup, IndividualFitRecommendation[]>;
  hidden_fits: IndividualFitRecommendation[];
  current_ratings: TeamRatings;
  current_total_rating: number;
  current_weakest_rating: number;
  open_slots: TargetCounts;
  current_counts: TargetCounts;
};

export type SortMode =
  | "overall"
  | "total_gain"
  | "weakest_gain"
  | "added_bpr"
  | SkillKey;

export const SKILL_KEYS: SkillKey[] = [
  "spacing_percentile",
  "facilitating_percentile",
  "rim_protection_percentile",
  "defense_percentile",
  "finishing_percentile",
];

export const SKILL_LABELS: Record<SkillKey, string> = {
  spacing_percentile: "Spacing",
  facilitating_percentile: "Facilitating",
  rim_protection_percentile: "Rim Protection",
  defense_percentile: "Defense",
  finishing_percentile: "Finishing",
};

export const DEFAULT_TARGET_COUNTS: TargetCounts = { G: 5, F: 6, C: 4 };
export const TOP_N_CANDIDATES_PER_POSITION = 200;
export const MAX_ROSTER_SIZE = 15;

export function normalizeOptimizerPlayer(player: Player): OptimizerPlayer | null {
  const position_group = normalizePositionGroup(player.position) ?? normalizePositionGroup(getTopPlaytypes(player, 1)[0]?.label);
  if (!position_group) return null;

  const skills = {
    spacing_percentile: cleanNumber(player.skill_spacing_percentile),
    facilitating_percentile: cleanNumber(player.skill_facilitating_percentile),
    rim_protection_percentile: cleanNumber(player.skill_rim_protection_percentile),
    defense_percentile: cleanNumber(player.skill_defense_percentile),
    finishing_percentile: cleanNumber(player.skill_finishing_percentile),
  };
  if (SKILL_KEYS.some((key) => skills[key] == null)) return null;

  const projected_bpr =
    player.player_source === "transfer"
      ? cleanNumber(player.transfer_bpr) ?? cleanNumber(player.projected_bpr)
      : player.player_source === "hs"
        ? cleanNumber(player.hs_bpr) ?? cleanNumber(player.projected_bpr)
        : cleanNumber(player.projected_bpr);
  if (projected_bpr == null) return null;

  const transferId = cleanId(player.transfer_barttorvik_trid);
  const hsKey = cleanId(player.hs_player_key);
  const returningId = cleanId(player.returning_bvt_pid ?? player.returning_barttorvik_trid);

  if (player.player_source === "transfer" && transferId) {
    return {
      optimizer_player_id: `transfer:${transferId}`,
      allyears_pid: transferId,
      player_key: null,
      source_type: "transfer",
      player,
      player_name: player.player_name,
      position_group,
      projected_bpr,
      ...skillsAsNumbers(skills),
    };
  }

  if (player.player_source === "hs" && hsKey) {
    return {
      optimizer_player_id: `hs:${hsKey}`,
      allyears_pid: null,
      player_key: hsKey,
      source_type: "hs_recruit",
      player,
      player_name: player.player_name,
      position_group,
      projected_bpr,
      ...skillsAsNumbers(skills),
    };
  }

  if (player.player_source === "roster") {
    return {
      optimizer_player_id: returningId ? `returning:${returningId}` : `roster:${player.player_id}`,
      allyears_pid: returningId,
      player_key: null,
      source_type: "returning",
      player,
      player_name: player.player_name,
      position_group,
      projected_bpr,
      ...skillsAsNumbers(skills),
    };
  }

  return null;
}

export function normalizeCandidate(player: Player): OptimizerPlayer | null {
  if (player.player_source !== "transfer" && player.player_source !== "hs") return null;
  if (player.player_source === "transfer") {
    const status = (player.transfer_247_status ?? player.portal_status ?? "").toLowerCase();
    if (status !== "entered" && status !== "committed") return null;
  }
  if (player.player_source === "hs" && !isUncommittedHsRecruit(player)) return null;
  return normalizeOptimizerPlayer(player);
}

export function isUncommittedHsRecruit(player: Player) {
  if (player.player_source !== "hs") return false;
  const team = player.current_team.trim().toLowerCase();
  return team === "uncommitted" || team === "n/a" || team === "na" || !team;
}

export function displayOptimizerTeam(player: Player) {
  return isUncommittedHsRecruit(player) ? "N/A" : player.current_team;
}

export function getPositionCounts(players: OptimizerPlayer[]): TargetCounts {
  return {
    G: players.filter((player) => player.position_group === "G").length,
    F: players.filter((player) => player.position_group === "F").length,
    C: players.filter((player) => player.position_group === "C").length,
  };
}

export function getOpenSlots(currentCounts: TargetCounts, targetCounts: TargetCounts): TargetCounts {
  return {
    G: targetCounts.G - currentCounts.G,
    F: targetCounts.F - currentCounts.F,
    C: targetCounts.C - currentCounts.C,
  };
}

export function calculateTeamRatings(players: OptimizerPlayer[]): TeamRatings {
  const denominator = players.reduce((sum, player) => sum + Math.abs(player.projected_bpr), 0);
  const fallback = 50;
  return SKILL_KEYS.reduce((ratings, key) => {
    if (denominator <= 0) {
      ratings[key] = players.length ? average(players.map((player) => player[key])) : fallback;
      return ratings;
    }
    ratings[key] = players.reduce((sum, player) => sum + player.projected_bpr * player[key], 0) / denominator;
    return ratings;
  }, {} as TeamRatings);
}

export function totalRating(ratings: TeamRatings) {
  return SKILL_KEYS.reduce((sum, key) => sum + ratings[key], 0);
}

export function weakestRating(ratings: TeamRatings) {
  return Math.min(...SKILL_KEYS.map((key) => ratings[key]));
}

export function ratingChanges(current: TeamRatings, next: TeamRatings): TeamRatings {
  return SKILL_KEYS.reduce((changes, key) => {
    changes[key] = next[key] - current[key];
    return changes;
  }, {} as TeamRatings);
}

export function rankRecommendationSets(sets: RecommendationSet[], sortMode: SortMode) {
  return sets.slice().sort((left, right) => compareRecommendationSet(left, right, sortMode));
}

export function rankIndividualFits(fits: IndividualFitRecommendation[], sortMode: SortMode) {
  return fits.slice().sort((left, right) => compareIndividualFit(left, right, sortMode));
}

export function buildIndividualFits(
  currentRoster: OptimizerPlayer[],
  candidates: OptimizerPlayer[],
  currentRatings: TeamRatings,
): Record<PositionGroup, IndividualFitRecommendation[]> {
  const currentTotal = totalRating(currentRatings);
  const currentWeakest = weakestRating(currentRatings);
  const recommendations = candidates.map((candidate) => {
    const finalRatings = calculateTeamRatings([...currentRoster, candidate]);
    const changes = ratingChanges(currentRatings, finalRatings);
    const best = bestCategory(changes);
    return {
      player: candidate,
      position_group: candidate.position_group,
      final_ratings_if_added: finalRatings,
      rating_changes_if_added: changes,
      individual_total_gain: totalRating(finalRatings) - currentTotal,
      individual_weakest_gain: weakestRating(finalRatings) - currentWeakest,
      projected_bpr: candidate.projected_bpr,
      best_improved_category: best.key,
      best_improved_category_gain: best.value,
    };
  });

  return {
    G: rankIndividualFits(recommendations.filter((fit) => fit.position_group === "G"), "overall"),
    F: rankIndividualFits(recommendations.filter((fit) => fit.position_group === "F"), "overall"),
    C: rankIndividualFits(recommendations.filter((fit) => fit.position_group === "C"), "overall"),
  };
}

export function buildHiddenFits(
  individualFits: Record<PositionGroup, IndividualFitRecommendation[]>,
  allCandidates: OptimizerPlayer[],
  sortMode: SortMode,
) {
  const medians: Record<PositionGroup, number> = {
    G: median(allCandidates.filter((player) => player.position_group === "G").map((player) => player.projected_bpr)),
    F: median(allCandidates.filter((player) => player.position_group === "F").map((player) => player.projected_bpr)),
    C: median(allCandidates.filter((player) => player.position_group === "C").map((player) => player.projected_bpr)),
  };
  const fits = (["G", "F", "C"] as PositionGroup[]).flatMap((position) =>
    rankIndividualFits(individualFits[position], sortMode).filter((fit) => fit.projected_bpr <= medians[position]),
  );
  return rankIndividualFits(fits, sortMode).slice(0, 5);
}

export function candidateContribution(player: OptimizerPlayer, key?: SkillKey) {
  if (key) return player.projected_bpr * player[key];
  return player.projected_bpr * SKILL_KEYS.reduce((sum, skill) => sum + player[skill], 0);
}

export function solutionToRecommendationSet({
  selectedPlayers,
  currentRoster,
  currentRatings,
  currentTotal,
  currentWeakest,
  rank,
  surfacedBy,
}: {
  selectedPlayers: OptimizerPlayer[];
  currentRoster: OptimizerPlayer[];
  currentRatings: TeamRatings;
  currentTotal: number;
  currentWeakest: number;
  rank: number;
  surfacedBy: string;
}): RecommendationSet {
  const finalRatings = calculateTeamRatings([...currentRoster, ...selectedPlayers]);
  const changes = ratingChanges(currentRatings, finalRatings);
  const best = bestCategory(changes);
  const finalTotal = totalRating(finalRatings);
  const finalWeakest = weakestRating(finalRatings);
  const ids = selectedPlayers.map((player) => player.optimizer_player_id).sort().join("|");
  return {
    id: ids || `empty-${rank}`,
    selected_players: selectedPlayers,
    final_ratings: finalRatings,
    rating_changes: changes,
    final_total_rating: finalTotal,
    final_weakest_rating: finalWeakest,
    added_projected_bpr: selectedPlayers.reduce((sum, player) => sum + player.projected_bpr, 0),
    total_gain: finalTotal - currentTotal,
    weakest_gain: finalWeakest - currentWeakest,
    best_affected_category: best.key,
    best_category_gain: best.value,
    rank,
    surfaced_by: surfacedBy,
  };
}

export function isValidTargetTotal(targetCounts: TargetCounts) {
  return targetCounts.G + targetCounts.F + targetCounts.C <= MAX_ROSTER_SIZE;
}

export function normalizePositionGroup(value: string | null | undefined): PositionGroup | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (["pg", "sg", "cg", "g", "combo guard", "combo g", "pure pg", "scoring pg"].includes(normalized)) return "G";
  if (["sf", "pf", "f", "wing", "wing f", "wing g", "stretch 4", "forward"].includes(normalized)) return "F";
  if (["c", "center", "pf/c", "c/pf", "f/c", "fc"].includes(normalized)) return "C";
  return null;
}

function compareRecommendationSet(left: RecommendationSet, right: RecommendationSet, sortMode: SortMode) {
  if (sortMode === "total_gain") return by(right.total_gain, left.total_gain) || by(right.weakest_gain, left.weakest_gain) || by(right.added_projected_bpr, left.added_projected_bpr);
  if (sortMode === "weakest_gain") return by(right.weakest_gain, left.weakest_gain) || by(right.total_gain, left.total_gain) || by(right.added_projected_bpr, left.added_projected_bpr);
  if (sortMode === "added_bpr") return by(right.added_projected_bpr, left.added_projected_bpr) || by(right.total_gain, left.total_gain) || by(right.weakest_gain, left.weakest_gain);
  if (SKILL_KEYS.includes(sortMode as SkillKey)) {
    const key = sortMode as SkillKey;
    return by(right.rating_changes[key], left.rating_changes[key]) || by(right.total_gain, left.total_gain) || by(right.weakest_gain, left.weakest_gain) || by(right.added_projected_bpr, left.added_projected_bpr);
  }
  return by(right.final_total_rating, left.final_total_rating) || by(right.final_weakest_rating, left.final_weakest_rating) || by(right.added_projected_bpr, left.added_projected_bpr);
}

function compareIndividualFit(left: IndividualFitRecommendation, right: IndividualFitRecommendation, sortMode: SortMode) {
  if (sortMode === "total_gain") return by(right.individual_total_gain, left.individual_total_gain) || by(right.individual_weakest_gain, left.individual_weakest_gain) || by(right.projected_bpr, left.projected_bpr);
  if (sortMode === "weakest_gain") return by(right.individual_weakest_gain, left.individual_weakest_gain) || by(right.individual_total_gain, left.individual_total_gain) || by(right.projected_bpr, left.projected_bpr);
  if (sortMode === "added_bpr") return by(right.projected_bpr, left.projected_bpr) || by(right.individual_total_gain, left.individual_total_gain) || by(right.individual_weakest_gain, left.individual_weakest_gain);
  if (SKILL_KEYS.includes(sortMode as SkillKey)) {
    const key = sortMode as SkillKey;
    return by(right.rating_changes_if_added[key], left.rating_changes_if_added[key]) || by(right.individual_total_gain, left.individual_total_gain) || by(right.individual_weakest_gain, left.individual_weakest_gain) || by(right.projected_bpr, left.projected_bpr);
  }
  return by(right.individual_total_gain, left.individual_total_gain) || by(right.individual_weakest_gain, left.individual_weakest_gain) || by(right.projected_bpr, left.projected_bpr);
}

function bestCategory(changes: TeamRatings) {
  return SKILL_KEYS.map((key) => ({ key, value: changes[key] })).sort((left, right) => right.value - left.value)[0];
}

function skillsAsNumbers(skills: Record<SkillKey, number | null>): TeamRatings {
  return SKILL_KEYS.reduce((values, key) => {
    values[key] = skills[key] ?? 0;
    return values;
  }, {} as TeamRatings);
}

function cleanNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return Number(value);
}

function cleanId(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function average(values: number[]) {
  if (!values.length) return 50;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function median(values: number[]) {
  if (!values.length) return Number.POSITIVE_INFINITY;
  const sorted = values.slice().sort((left, right) => left - right);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function by(right: number, left: number) {
  return right === left ? 0 : right - left;
}
