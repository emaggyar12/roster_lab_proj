import type React from "react";
import { useEffect, useState } from "react";
import { Activity, ClipboardList, Target } from "lucide-react";
import type { Player } from "@/data/players";
import { getTopPlaytypes } from "@/lib/data";
import { SourceBadge } from "@/components/StatusBadge";

export function PlayerDetailPanel({ player }: { player: Player }) {
  const playtypes = getTopPlaytypes(player, 3);
  const isHsRecruit = player.player_source === "hs";
  const isTransfer = player.player_source === "transfer";
  const [animateBars, setAnimateBars] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setAnimateBars(true));
    return () => cancelAnimationFrame(frame);
  }, [player.player_id]);

  return (
    <div className="grid gap-4 border-t border-line bg-white px-4 py-4 text-sm md:grid-cols-[1.2fr_1fr_1fr]">
      <section className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <ClipboardList className="h-4 w-4" />
          Profile
        </div>
        <SourceBadge source={player.player_source} />
        <p className="leading-6 text-slate-700">{player.scouting_summary}</p>
        <p className="leading-6 text-slate-700">{player.fit_explanation}</p>
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <Target className="h-4 w-4" />
          Playtype Probabilities
        </div>
        <div className="space-y-2">
          {playtypes.map((playtype) => (
            <div key={playtype.label} className="grid grid-cols-[92px_1fr_44px] items-center gap-2">
              <span className="truncate text-xs font-medium text-slate-700">{playtype.label}</span>
              <div className="h-2 overflow-hidden rounded bg-slate-200">
                <div
                  className="h-full rounded bg-emerald-600 transition-[width] duration-700 ease-out"
                  style={{ width: animateBars ? `${Math.round(playtype.probability * 100)}%` : "0%" }}
                />
              </div>
              <span className="text-right text-xs tabular-nums text-slate-600">
                {Math.round(playtype.probability * 100)}%
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="grid grid-cols-2 gap-2">
        {isHsRecruit ? (
          <>
            <Metric label="Nat. Rank" value={formatRank(player.hs_national_rank)} />
            <Metric label="Pos. Rank" value={formatRank(player.hs_position_rank)} />
          </>
        ) : isTransfer ? (
          <>
            <Metric label="247 Rank" value={formatRank(player.transfer_247_rank)} />
            <Metric label="247 Stars" value={formatOptionalNumber(player.transfer_247_stars)} />
            <Metric label="247 Rating" value={formatTransferRating(player.transfer_247_rating)} />
            <Metric label="247 Status" value={player.transfer_247_status ?? "N/A"} />
            <Metric
              label="Weight"
              value={formatWeight(
                player.transfer_247_weight && player.transfer_247_weight > 0
                  ? player.transfer_247_weight
                  : player.weight > 0
                    ? player.weight
                    : null,
              )}
            />
            <Metric label="Height" value={player.height || "N/A"} />
          </>
        ) : (
          <>
        <Metric icon={<Activity className="h-4 w-4" />} label="BPR" value={player.projected_bpr.toFixed(1)} />
        <Metric label="MIN" value={player.projected_minutes.toFixed(0)} />
        <Metric label="PTS" value={player.projected_points.toFixed(1)} />
        <Metric label="REB" value={player.projected_rebounds.toFixed(1)} />
        <Metric label="AST" value={player.projected_assists.toFixed(1)} />
          </>
        )}
      </section>
    </div>
  );
}

function formatRank(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `#${Math.round(value)}`;
}

function formatOptionalNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `${Math.round(value)}`;
}

function formatTransferRating(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return value.toFixed(2);
}

function formatWeight(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `${Math.round(value)} lb`;
}

function Metric({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="min-h-16 rounded border border-line bg-panel p-3">
      <div className="flex items-center gap-1 text-xs font-semibold text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1 truncate text-lg font-semibold text-ink">{value}</div>
    </div>
  );
}
