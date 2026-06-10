export const OPTIMIZER_ROSTER_STORAGE_KEY = "roster-lab-optimizer-roster";

export type OptimizerRosterPayload = {
  teamName: string;
  playerIds: string[];
  loadedAt: string;
};

export function saveOptimizerRoster(payload: OptimizerRosterPayload) {
  window.localStorage.setItem(OPTIMIZER_ROSTER_STORAGE_KEY, JSON.stringify(payload));
}

export function readOptimizerRoster(): OptimizerRosterPayload | null {
  try {
    const raw = window.localStorage.getItem(OPTIMIZER_ROSTER_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<OptimizerRosterPayload>;
    if (!parsed.teamName || !Array.isArray(parsed.playerIds)) return null;
    return {
      teamName: parsed.teamName,
      playerIds: parsed.playerIds.filter((id): id is string => typeof id === "string"),
      loadedAt: typeof parsed.loadedAt === "string" ? parsed.loadedAt : "",
    };
  } catch {
    return null;
  }
}
