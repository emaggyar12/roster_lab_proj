"use client";

import type React from "react";
import { useMemo, useState } from "react";
import { ChevronDown, Minus, Plus, RotateCcw, UserCheck, Users } from "lucide-react";
import clsx from "clsx";
import type { Player } from "@/data/players";
import { getHsPlayers, getPortalPlayers, getTeamPlayers, getTeams, getTopPlaytypes } from "@/lib/data";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { SourceBadge } from "@/components/StatusBadge";

type TargetPool = "transfer" | "hs" | "all";

export function PortalSimulator() {
  const teams = getTeams();
  const [teamId, setTeamId] = useState(teams[0]?.team_id ?? "uconn");
  const [removedIds, setRemovedIds] = useState<string[]>([]);
  const [addedIds, setAddedIds] = useState<string[]>([]);
  const [targetPool, setTargetPool] = useState<TargetPool>("transfer");
  const team = teams.find((candidate) => candidate.team_id === teamId) ?? teams[0];

  const currentRoster = useMemo(() => getTeamPlayers(team.team_name), [team.team_name]);
  const targetPlayers = useMemo(
    () => {
      const pool =
        targetPool === "transfer"
          ? getPortalPlayers()
          : targetPool === "hs"
            ? getHsPlayers()
            : [...getPortalPlayers(), ...getHsPlayers()];
      return pool.filter((player) => !currentRoster.some((rosterPlayer) => rosterPlayer.player_id === player.player_id));
    },
    [currentRoster, targetPool],
  );
  const removedPlayers = currentRoster.filter((player) => removedIds.includes(player.player_id));
  const addedPlayers = targetPlayers.filter((player) => addedIds.includes(player.player_id));
  const activeRoster = currentRoster.filter((player) => !removedIds.includes(player.player_id));
  const projectedRoster = [...activeRoster, ...addedPlayers];
  const projectedBpr =
    projectedRoster.length === 0
      ? 0
      : projectedRoster.reduce((total, player) => total + player.projected_bpr, 0) / projectedRoster.length;
  const scholarshipCount = Math.max(0, team.scholarships_used - removedPlayers.length + addedPlayers.length);

  function toggleRemoved(playerId: string) {
    setRemovedIds((ids) => (ids.includes(playerId) ? ids.filter((id) => id !== playerId) : [...ids, playerId]));
  }

  function toggleAdded(playerId: string) {
    setAddedIds((ids) => (ids.includes(playerId) ? ids.filter((id) => id !== playerId) : [...ids, playerId]));
  }

  function resetScenario() {
    setRemovedIds([]);
    setAddedIds([]);
  }

  return (
    <section className="space-y-4">
      <div className="rounded border border-line bg-white p-4 shadow-soft">
        <div className="grid gap-4 lg:grid-cols-[280px_1fr_auto] lg:items-center">
          <label className="relative block">
            <select
              value={teamId}
              onChange={(event) => {
                setTeamId(event.target.value);
                resetScenario();
              }}
              className="h-10 w-full appearance-none rounded border border-line bg-panel px-3 pr-8 text-sm outline-none focus:border-ink"
            >
              {teams.map((candidate) => (
                <option key={candidate.team_id} value={candidate.team_id}>
                  {candidate.team_name}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          </label>
          <div className="text-sm text-slate-700">
            <span className="font-semibold text-ink">{team.style}</span>
            <span className="ml-2 text-slate-500">Needs: {team.needs.join(", ")}</span>
          </div>
          <button
            type="button"
            onClick={resetScenario}
            className="inline-flex h-10 items-center justify-center gap-2 rounded border border-line bg-panel px-3 text-sm font-semibold text-slate-700"
          >
            <RotateCcw className="h-4 w-4" />
            Reset
          </button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <SummaryMetric label="Roster" value={`${projectedRoster.length}`} detail={`${scholarshipCount}/${team.roster_limit} scholarships`} />
        <SummaryMetric label="Projected BPR" value={projectedBpr.toFixed(1)} detail="Average roster projection" />
        <SummaryMetric label="Departures" value={`${removedPlayers.length}`} detail={removedPlayers.map((p) => p.player_name).join(", ") || "None"} />
        <SummaryMetric label="Additions" value={`${addedPlayers.length}`} detail={addedPlayers.map((p) => p.player_name).join(", ") || "None"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <RosterList title="Current Roster" icon={<Users className="h-4 w-4" />} players={currentRoster} selectedIds={removedIds} onToggle={toggleRemoved} mode="remove" />
        <div className="space-y-3">
          <div className="grid grid-cols-3 rounded border border-line bg-panel p-1">
            {[
              ["transfer", "Transfers"],
              ["hs", "HS"],
              ["all", "Both"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setTargetPool(value as TargetPool);
                  setAddedIds([]);
                }}
                className={
                  targetPool === value
                    ? "h-9 rounded bg-emerald-600 px-3 text-sm font-semibold text-white dark:bg-emerald-500 dark:text-slate-950"
                    : "h-9 rounded px-3 text-sm font-semibold text-slate-600 hover:bg-surface dark:text-slate-300"
                }
              >
                {label}
              </button>
            ))}
          </div>
          <RosterList title="Add Targets" icon={<UserCheck className="h-4 w-4" />} players={targetPlayers} selectedIds={addedIds} onToggle={toggleAdded} mode="add" />
        </div>
      </div>
    </section>
  );
}

function SummaryMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="min-h-28 rounded border border-line bg-white p-4 shadow-soft">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
      <div className="mt-2 line-clamp-2 text-sm text-slate-600">{detail}</div>
    </div>
  );
}

function RosterList({
  title,
  icon,
  players,
  selectedIds,
  onToggle,
  mode,
}: {
  title: string;
  icon: React.ReactNode;
  players: Player[];
  selectedIds: string[];
  onToggle: (playerId: string) => void;
  mode: "add" | "remove";
}) {
  return (
    <div className="overflow-hidden rounded border border-line bg-white shadow-soft">
      <div className="flex items-center gap-2 border-b border-line bg-panel px-4 py-3 text-sm font-semibold text-ink">
        {icon}
        {title}
      </div>
      <div className="divide-y divide-line">
        {players.map((player) => {
          const selected = selectedIds.includes(player.player_id);
          const topPlaytype = getTopPlaytypes(player, 1)[0]?.label;
          return (
            <button
              type="button"
              key={player.player_id}
              onClick={() => onToggle(player.player_id)}
              className={clsx(
                "grid w-full grid-cols-[1fr_auto] items-center gap-3 px-4 py-3 text-left hover:bg-panel",
                selected && (mode === "add" ? "bg-emerald-50 dark:bg-emerald-950" : "bg-rose-50 dark:bg-rose-950"),
              )}
            >
              <div className="flex min-w-0 items-center gap-3">
                <PlayerAvatar player={player} size="sm" />
                <div className="min-w-0">
                <div className="truncate font-semibold text-ink">{player.player_name}</div>
                <div className="mt-1 truncate text-xs text-slate-500">
                  {player.position} | {player.height} | {player.current_team} | {topPlaytype}
                </div>
                <div className="mt-2">
                  <SourceBadge source={player.player_source} />
                </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold tabular-nums text-ink">BPR {player.projected_bpr.toFixed(1)}</span>
                <span
                  className={clsx(
                    "flex h-8 w-8 items-center justify-center rounded border",
                    selected
                      ? "border-emerald-600 bg-emerald-600 text-white dark:border-emerald-400 dark:bg-emerald-500 dark:text-slate-950"
                      : "border-line bg-panel text-slate-700 dark:text-slate-200",
                  )}
                >
                  {mode === "add" ? <Plus className="h-4 w-4" /> : <Minus className="h-4 w-4" />}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
