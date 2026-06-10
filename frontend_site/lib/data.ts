import { players, type Player, type PlayerSource, type PortalStatus } from "@/data/players";
import { canonicalizeInstitution } from "@/data/teamAliases";
import { teams, type Team } from "@/data/teams";

export type PlayerFilters = {
  query?: string;
  team?: string;
  position?: string;
  classYear?: string;
  portalStatus?: string;
  conference?: string;
  playtype?: string;
  playerSource?: PlayerSource;
  minBpr?: number;
  portalOnly?: boolean;
  availableOnly?: boolean;
};

export function getPlayers(filters: PlayerFilters = {}) {
  const filterTeam = canonicalizeInstitution(filters.team);

  return players.filter((player) => {
    const query = filters.query?.trim().toLowerCase();
    const topPlaytype = getTopPlaytypes(player, 1)[0]?.label;
    return (
      (!query ||
        player.player_name.toLowerCase().includes(query) ||
        player.current_team.toLowerCase().includes(query) ||
        player.previous_team?.toLowerCase().includes(query) ||
        player.new_team?.toLowerCase().includes(query)) &&
      (!filterTeam ||
        player.current_team === filterTeam ||
        player.committed_team === filterTeam ||
        player.new_team === filterTeam) &&
      (!filters.position || player.position === filters.position) &&
      (!filters.classYear || player.class_year === filters.classYear) &&
      (!filters.portalStatus || player.portal_status === filters.portalStatus) &&
      (!filters.conference || player.conference === filters.conference) &&
      (!filters.playtype || topPlaytype === filters.playtype) &&
      (!filters.playerSource || player.player_source === filters.playerSource) &&
      (!filters.minBpr || player.projected_bpr >= filters.minBpr) &&
      (!filters.portalOnly || player.is_in_portal) &&
      (!filters.availableOnly || player.portal_status === "entered")
    );
  });
}

export function getPortalPlayers() {
  return players.filter((player) => player.player_source === "transfer" && player.is_in_portal && !player.draft_status);
}

export function getHsPlayers() {
  return players.filter((player) => player.player_source === "hs" && !player.draft_status);
}

export function getTeams() {
  return teams;
}

export function getTeam(teamId: string): Team | undefined {
  return teams.find((team) => team.team_id === teamId);
}

export function getTeamPlayers(teamName: string) {
  const canonicalTeamName = canonicalizeInstitution(teamName) ?? teamName;

  return players.filter(
    (player) =>
      !player.draft_status &&
      (player.current_team === canonicalTeamName ||
        player.committed_team === canonicalTeamName ||
        player.new_team === canonicalTeamName),
  );
}

export function getRecommendations(teamName: string, source: "all" | PlayerSource = "all") {
  return players
    .filter((player) => player.player_source !== "roster")
    .filter((player) => source === "all" || player.player_source === source)
    .map((player) => ({
      ...player,
      fit_score: Math.min(99, player.fit_score + teamAdjustment(teamName, player.position)),
    }))
    .sort((a, b) => b.fit_score - a.fit_score || b.projected_bpr - a.projected_bpr);
}

export function getTopPlaytypes(player: Player, count = 3) {
  return Object.entries(player.playtype_probabilities)
    .sort((a, b) => b[1] - a[1])
    .slice(0, count)
    .map(([label, probability]) => ({ label, probability }));
}

export function formatStatus(status: PortalStatus) {
  return status
    .split("_")
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

function teamAdjustment(teamName: string, position: Player["position"]) {
  if (teamName === "Indiana" && ["PG", "PF", "C"].includes(position)) return 6;
  if (teamName === "UCLA" && ["SG", "SF", "C"].includes(position)) return 5;
  if (teamName === "UConn" && ["PG", "PF"].includes(position)) return 4;
  if (teamName === "Providence" && ["SF", "C"].includes(position)) return 6;
  return 0;
}
