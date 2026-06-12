"use client";

import { PlayerTable } from "@/components/PlayerTable";
import type { PlayerMode } from "@/components/PlayerTable";
import { Shell } from "@/components/Shell";
import { players } from "@/data/players";
import { useMemo, useState } from "react";

export default function PlayersPage() {
  const [mode, setMode] = useState<PlayerMode>("all");
  const tablePlayers = useMemo(
    () =>
      mode === "all"
        ? players.filter((player) => player.player_source === "roster" && !player.draft_status)
        : mode === "draft"
          ? players.filter((player) => player.draft_status)
          : players.filter((player) => !player.draft_status),
    [mode],
  );

  return (
    <Shell>
      <PageHeader
        title="Player Leaderboard"
        description="Search, filter, sort, and expand players across the roster and transfer portal pool."
        mode={mode}
        onModeChange={setMode}
      />
      <PlayerTable players={tablePlayers} playerMode={mode} />
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
    { label: "Returning", value: "all" },
    { label: "HS Recruits", value: "hs" },
    { label: "Transfers", value: "transfer" },
    { label: "Draft", value: "draft" },
  ];

  return (
    <div className="mb-5 grid gap-4 lg:grid-cols-[1fr_auto] lg:items-start">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
      </div>
      <div className="grid grid-cols-4 rounded border border-line bg-panel p-1">
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
