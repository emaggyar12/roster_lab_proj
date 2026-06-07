"use client";

import { PlayerTable } from "@/components/PlayerTable";
import type { PlayerMode } from "@/components/PlayerTable";
import { Shell } from "@/components/Shell";
import { getPlayers } from "@/lib/data";
import { useMemo, useState } from "react";

export default function HomePage() {
  const players = getPlayers();
  const [mode, setMode] = useState<PlayerMode>("all");
  const visiblePlayers = useMemo(
    () => players.filter((player) => mode === "all" || player.player_source === mode),
    [mode, players],
  );
  const portalCount = visiblePlayers.filter((player) => player.is_in_portal).length;

  return (
    <Shell>
      <PageHeader
        title="Player Leaderboard"
        description="Search, filter, sort, and expand players across the roster and transfer portal pool."
        mode={mode}
        onModeChange={setMode}
      />
      <div className="mb-4 grid gap-3 md:grid-cols-4">
        <Metric label="Tracked Players" value={`${visiblePlayers.length}`} />
        <Metric label="In Portal" value={`${portalCount}`} />
        <Metric label={mode === "hs" ? "Average Rating" : "Average BPR"} value={averageMetric(visiblePlayers, mode)} />
        <Metric label={mode === "hs" ? "Top Rating" : "Top Fit"} value={topMetric(visiblePlayers, mode)} />
      </div>
      <PlayerTable players={players} playerMode={mode} />
    </Shell>
  );
}

function PageHeader({
  title,
  description,
  mode,
  onModeChange,
}: {
  title: string;
  description: string;
  mode: PlayerMode;
  onModeChange: (mode: PlayerMode) => void;
}) {
  const options: Array<{ label: string; value: PlayerMode }> = [
    { label: "All", value: "all" },
    { label: "HS Recruits", value: "hs" },
    { label: "Transfers", value: "transfer" },
  ];

  return (
    <div className="mb-5 grid gap-4 lg:grid-cols-[1fr_auto] lg:items-start">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
      </div>
      <div className="grid grid-cols-3 rounded border border-line bg-panel p-1">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onModeChange(option.value)}
            className={
              mode === option.value
                ? "h-10 rounded bg-emerald-600 px-4 text-sm font-semibold text-white dark:bg-emerald-500 dark:text-slate-950"
                : "h-10 rounded px-4 text-sm font-semibold text-slate-600 hover:bg-surface dark:text-slate-300"
            }
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-white p-4 shadow-soft">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
    </div>
  );
}

function averageMetric(players: ReturnType<typeof getPlayers>, mode: PlayerMode) {
  if (!players.length) return "0";
  if (mode === "hs") {
    const ratings = players.map((player) => player.hs_rating).filter((value): value is number => value !== null && value !== undefined);
    if (!ratings.length) return "N/A";
    return (ratings.reduce((sum, value) => sum + value, 0) / ratings.length).toFixed(2);
  }
  return (players.reduce((sum, player) => sum + player.projected_bpr, 0) / players.length).toFixed(1);
}

function topMetric(players: ReturnType<typeof getPlayers>, mode: PlayerMode) {
  if (!players.length) return "0";
  if (mode === "hs") {
    const ratings = players.map((player) => player.hs_rating).filter((value): value is number => value !== null && value !== undefined);
    if (!ratings.length) return "N/A";
    return Math.max(...ratings).toFixed(2);
  }
  return `${Math.max(...players.map((player) => player.fit_score))}`;
}
