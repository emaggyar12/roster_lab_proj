import { draftPlayerIds } from "./draftPlayers";
import { hsRecruitPlayers } from "./hsRecruits";
import { returningPlayers } from "./returningPlayers";
import { canonicalizeInstitution } from "./teamAliases";
import { transferPlayers } from "./transferPlayers";

export type PortalStatus = "not_in_portal" | "entered" | "committed" | "enrolled" | "withdrawn";
export type PlayerSource = "transfer" | "hs" | "roster";

export type Player = {
  player_id: string;
  player_name: string;
  player_source: PlayerSource;
  position: "PG" | "SG" | "CG" | "SF" | "PF" | "C" | "N/A";
  height: string;
  weight: number;
  class_year: "Fr" | "So" | "Jr" | "Sr" | "Gr" | "N/A";
  current_team: string;
  previous_team?: string;
  new_team?: string;
  conference: string;
  portal_status: PortalStatus;
  is_in_portal: boolean;
  committed_team?: string;
  projected_bpr: number;
  projected_minutes: number;
  projected_points: number;
  projected_rebounds: number;
  projected_assists: number;
  playtype_probabilities: Record<string, number>;
  fit_score: number;
  recommendation_rank: number;
  fit_explanation: string;
  scouting_summary: string;
  profile_image_url?: string | null;
  transfer_247_status?: string | null;
  transfer_247_stars?: number | null;
  transfer_247_rating?: number | null;
  transfer_247_rank?: number | null;
  transfer_247_weight?: number | null;
  transfer_247_player_key?: number | null;
  transfer_barttorvik_trid?: number | null;
  transfer_bpr?: number | null;
  returning_bvt_pid?: number | null;
  returning_barttorvik_trid?: number | null;
  returning_role?: string | null;
  returning_current_bpr?: number | null;
  returning_projected_bpr?: number | null;
  season_basic_bpr?: number | null;
  season_gp?: number | null;
  season_mp?: number | null;
  season_oreb?: number | null;
  season_dreb?: number | null;
  season_treb?: number | null;
  season_ast?: number | null;
  season_stl?: number | null;
  season_blk?: number | null;
  season_pts?: number | null;
  season_ft_pct?: number | null;
  skill_spacing_percentile?: number | null;
  skill_facilitating_percentile?: number | null;
  skill_rim_protection_percentile?: number | null;
  skill_defense_percentile?: number | null;
  skill_finishing_percentile?: number | null;
  hs_rating?: number | null;
  hs_stars?: number | null;
  hs_national_rank?: number | null;
  hs_position_rank?: number | null;
  hs_bpr?: number | null;
  hs_player_key?: number;
  draft_status?: boolean;
  top3_roles?: Array<{ label: string | null; probability: number | null }>;
};

export const basePlayers: Player[] = [];

const rosterPlayers = basePlayers.filter((player) => player.player_source !== "transfer");

function canonicalizePlayerInstitutions(player: Player): Player {
  return {
    ...player,
    draft_status: draftPlayerIds.has(player.player_id) || undefined,
    current_team: canonicalizeInstitution(player.current_team) ?? player.current_team,
    previous_team: canonicalizeInstitution(player.previous_team),
    new_team: canonicalizeInstitution(player.new_team),
    committed_team: canonicalizeInstitution(player.committed_team),
  };
}

export const players: Player[] = [...rosterPlayers, ...returningPlayers, ...transferPlayers, ...hsRecruitPlayers].map(canonicalizePlayerInstitutions);
