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

  return players.filter((player) => {
    if (player.draft_status) return false;
    if (player.player_source === "transfer") return isTransferRosterMemberForTeam(player, canonicalTeamName);
    return player.current_team === canonicalTeamName || player.committed_team === canonicalTeamName || player.new_team === canonicalTeamName;
  });
}

export function isTransferOutgoingFromTeam(player: Player, teamName: string) {
  if (player.player_source !== "transfer") return false;
  const canonicalTeamName = canonicalTeam(teamName);
  if (!canonicalTeamName) return false;
  const sourceTeams = getTransferSourceTeams(player);
  if (!sourceTeams.includes(canonicalTeamName)) return false;
  return !getTransferDestinationTeams(player).includes(canonicalTeamName);
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

function isTransferRosterMemberForTeam(player: Player, canonicalTeamName: string) {
  const selectedTeam = canonicalTeam(canonicalTeamName);
  if (!selectedTeam) return false;
  const destinationTeams = getTransferDestinationTeams(player);
  if (destinationTeams.includes(selectedTeam)) return true;
  const sourceTeams = getTransferSourceTeams(player);
  if (!sourceTeams.includes(selectedTeam)) return false;
  return destinationTeams.some((destinationTeam) => sourceTeams.includes(destinationTeam));
}

function getTransferSourceTeams(player: Player) {
  return uniqueTeams([player.current_team, player.previous_team]);
}

function getTransferDestinationTeams(player: Player) {
  return uniqueTeams([player.new_team, player.committed_team]);
}

function uniqueTeams(values: Array<string | undefined>) {
  return Array.from(new Set(values.map(canonicalTeam).filter((value): value is string => Boolean(value))));
}

function canonicalTeam(value: string | undefined) {
  const rawValue = value?.trim();
  if (!rawValue) return null;
  const canonicalValue = canonicalizeInstitution(rawValue) ?? rawValue;
  const lowerValue = canonicalValue.toLowerCase();
  if (lowerValue === "n/a" || lowerValue === "na" || lowerValue === "unknown" || lowerValue === "uncommitted") return null;
  return canonicalValue;
}
