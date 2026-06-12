import type React from "react";
import { useEffect, useState } from "react";
import { Activity, ClipboardList, Target } from "lucide-react";
import clsx from "clsx";
import type { Player } from "@/data/players";
import { getTopPlaytypes } from "@/lib/data";
import { SourceBadge } from "@/components/StatusBadge";

export function PlayerDetailPanel({ player }: { player: Player }) {
  const playtypes = getTopPlaytypes(player, 3);
  const isHsRecruit = player.player_source === "hs";
  const isTransfer = player.player_source === "transfer";
  const isReturning = Boolean(player.returning_bvt_pid);
  const [animateBars, setAnimateBars] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setAnimateBars(true));
    return () => cancelAnimationFrame(frame);
  }, [player.player_id]);

  if (isReturning) {
    return (
      <div className="border-t border-line bg-white px-4 py-4 text-sm">
        <div className="grid gap-4 xl:grid-cols-[1.2fr_.8fr] xl:items-stretch">
          <ReturningSeasonStats player={player} />
          <SkillRadar player={player} animate={animateBars} />
        </div>
      </div>
    );
  }

  if (isTransfer) {
    return (
      <div className="border-t border-line bg-white px-4 py-4 text-sm">
        <div className="grid gap-4 xl:grid-cols-[.95fr_1.05fr] xl:items-stretch">
          <TransferProfileCard player={player} playtypes={playtypes} animate={animateBars} />
          <SkillRadar player={player} animate={animateBars} />
        </div>
      </div>
    );
  }

  if (isHsRecruit) {
    return (
      <div className="border-t border-line bg-white px-4 py-4 text-sm">
        <div className="grid gap-4 xl:grid-cols-[.95fr_1.05fr] xl:items-stretch">
          <HsProfileCard player={player} playtypes={playtypes} animate={animateBars} />
          <SkillRadar player={player} animate={animateBars} />
        </div>
      </div>
    );
  }

  return (
    <div className="border-t border-line bg-white px-4 py-4 text-sm">
      <div className="grid gap-4 md:grid-cols-[1.2fr_1fr_1fr]">
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
            </>
          ) : (
            <>
              <Metric icon={<Activity className="h-4 w-4" />} label="BPR" value={player.projected_bpr.toFixed(2)} />
              <Metric label="MIN" value={player.projected_minutes.toFixed(0)} />
              <Metric label="PTS" value={player.projected_points.toFixed(2)} />
              <Metric label="REB" value={player.projected_rebounds.toFixed(2)} />
              <Metric label="AST" value={player.projected_assists.toFixed(2)} />
            </>
          )}
        </section>
      </div>
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

function HsProfileCard({
  player,
  playtypes,
  animate,
}: {
  player: Player;
  playtypes: { label: string; probability: number }[];
  animate: boolean;
}) {
  const hsMetrics = [
    { label: "Nat. Rank", value: formatRank(player.hs_national_rank) },
    { label: "Pos. Rank", value: formatRank(player.hs_position_rank) },
    { label: "Stars", value: formatOptionalNumber(player.hs_stars) },
    { label: "BPR", value: formatStat(player.hs_bpr, 2), emphasized: true },
  ];

  return (
    <section className="rounded border border-line bg-panel px-4 py-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <ClipboardList className="h-4 w-4" />
            Recruit Profile
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <SourceBadge source={player.player_source} />
            <span className="rounded border border-line bg-white px-2 py-1 text-xs font-semibold text-slate-600">
              {player.current_team}
            </span>
          </div>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>Projected role</div>
          <div className="mt-1 text-sm font-semibold text-ink">{playtypes[0]?.label ?? "N/A"}</div>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {hsMetrics.map((metric) => (
          <div
            key={metric.label}
            className={clsx(
              "rounded border border-line bg-white px-3 py-2 shadow-soft",
              metric.emphasized && "border-sky-300 dark:border-sky-600",
            )}
          >
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{metric.label}</div>
            <div className="mt-1 text-lg font-semibold tabular-nums text-ink">{metric.value}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr] lg:items-start">
        <div className="space-y-2 leading-6 text-slate-700">
          <p>{player.scouting_summary}</p>
          <p>{player.fit_explanation}</p>
        </div>
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <Target className="h-4 w-4" />
            Playtype Probabilities
          </div>
          <div className="space-y-2">
            {playtypes.map((playtype) => (
              <div key={playtype.label} className="grid grid-cols-[82px_1fr_38px] items-center gap-2">
                <span className="truncate text-xs font-medium text-slate-700">{playtype.label}</span>
                <div className="h-2 overflow-hidden rounded bg-slate-200">
                  <div
                    className="h-full rounded bg-emerald-600 transition-[width] duration-700 ease-out"
                    style={{ width: animate ? `${Math.round(playtype.probability * 100)}%` : "0%" }}
                  />
                </div>
                <span className="text-right text-xs tabular-nums text-slate-600">
                  {Math.round(playtype.probability * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function TransferProfileCard({
  player,
  playtypes,
  animate,
}: {
  player: Player;
  playtypes: { label: string; probability: number }[];
  animate: boolean;
}) {
  const transferMetrics = [
    { label: "247 Rank", value: formatRank(player.transfer_247_rank) },
    { label: "Transfer Rating", value: formatTransferRating(player.transfer_247_rating) },
    { label: "BPR", value: formatStat(player.transfer_bpr, 2), emphasized: true },
  ];

  return (
    <section className="rounded border border-line bg-panel px-4 py-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <ClipboardList className="h-4 w-4" />
            Transfer Profile
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <SourceBadge source={player.player_source} />
            <span className="rounded border border-line bg-white px-2 py-1 text-xs font-semibold text-slate-600">
              {player.current_team} → {player.new_team ?? "Uncommitted"}
            </span>
          </div>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>Projected role</div>
          <div className="mt-1 text-sm font-semibold text-ink">{playtypes[0]?.label ?? "N/A"}</div>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {transferMetrics.map((metric) => (
          <div
            key={metric.label}
            className={clsx(
              "rounded border border-line bg-white px-3 py-2 shadow-soft",
              metric.emphasized && "border-sky-300 dark:border-sky-600",
            )}
          >
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{metric.label}</div>
            <div className="mt-1 text-lg font-semibold tabular-nums text-ink">{metric.value}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr] lg:items-start">
        <div className="space-y-2 leading-6 text-slate-700">
          <p>{player.scouting_summary}</p>
          <p>{player.fit_explanation}</p>
        </div>
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <Target className="h-4 w-4" />
            Playtype Probabilities
          </div>
          <div className="space-y-2">
            {playtypes.map((playtype) => (
              <div key={playtype.label} className="grid grid-cols-[82px_1fr_38px] items-center gap-2">
                <span className="truncate text-xs font-medium text-slate-700">{playtype.label}</span>
                <div className="h-2 overflow-hidden rounded bg-slate-200">
                  <div
                    className="h-full rounded bg-emerald-600 transition-[width] duration-700 ease-out"
                    style={{ width: animate ? `${Math.round(playtype.probability * 100)}%` : "0%" }}
                  />
                </div>
                <span className="text-right text-xs tabular-nums text-slate-600">
                  {Math.round(playtype.probability * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function SeasonStats({ player }: { player: Player }) {
  const hasStats = [
    player.season_basic_bpr,
    player.season_gp,
    player.season_mp,
    player.season_oreb,
    player.season_dreb,
    player.season_treb,
    player.season_ast,
    player.season_stl,
    player.season_blk,
    player.season_pts,
  ].some((value) => value !== null && value !== undefined && !Number.isNaN(value));

  if (!hasStats) return null;

  return (
    <>
      <div className="col-span-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <Activity className="h-4 w-4" />
        2025-2026 Stats
      </div>
      <Metric label="BPR" value={formatStat(player.season_basic_bpr, 2)} />
      <Metric label="GP" value={formatStat(player.season_gp, 0)} />
      <Metric label="MP" value={formatStat(player.season_mp, 2)} />
      <Metric label="OREB" value={formatStat(player.season_oreb, 2)} />
      <Metric label="DREB" value={formatStat(player.season_dreb, 2)} />
      <Metric label="TREB" value={formatStat(player.season_treb, 2)} />
      <Metric label="AST" value={formatStat(player.season_ast, 2)} />
      <Metric label="STL" value={formatStat(player.season_stl, 2)} />
      <Metric label="BLK" value={formatStat(player.season_blk, 2)} />
      <Metric label="PTS" value={formatStat(player.season_pts, 2)} />
    </>
  );
}

function ReturningSeasonStats({ player }: { player: Player }) {
  const primaryStats = [
    { label: "PPG", value: formatStat(player.season_pts, 2) },
    { label: "RPG", value: formatStat(player.season_treb, 2) },
    { label: "APG", value: formatStat(player.season_ast, 2) },
    { label: "SPG", value: formatStat(player.season_stl, 2) },
    { label: "BPG", value: formatStat(player.season_blk, 2) },
  ];
  const secondaryStats = [
    { label: "GP", value: formatStat(player.season_gp, 0) },
    { label: "MP", value: formatStat(player.season_mp, 2) },
    { label: "FT", value: formatPercent(player.season_ft_pct) },
    { label: "BPR", value: formatStat(player.season_basic_bpr, 2), emphasized: true },
  ];

  return (
    <section className="rounded border border-line bg-panel px-4 py-4">
      <div className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">2025-26 Season Stats</div>
      <div className="grid gap-4">
        <div className="grid grid-cols-2 justify-items-center gap-4 sm:grid-cols-5">
          {primaryStats.map((stat) => (
            <ReturningStat key={stat.label} stat={stat} />
          ))}
        </div>
        <div className="grid grid-cols-2 justify-items-center gap-4 border-t border-line pt-4 sm:grid-cols-4">
          {secondaryStats.map((stat) => (
            <ReturningStat key={stat.label} stat={stat} />
          ))}
        </div>
      </div>
    </section>
  );
}

function ReturningStat({ stat }: { stat: { label: string; value: string; emphasized?: boolean } }) {
  return (
    <div
      className={clsx(
        "min-w-20 text-center",
        stat.emphasized && "rounded border border-sky-300 bg-white px-4 py-2 shadow-soft dark:border-sky-600",
      )}
    >
      <div className="text-xl font-semibold tabular-nums text-ink">{stat.value}</div>
      <div className="mt-1 text-xs font-medium uppercase tracking-wide text-slate-500">{stat.label}</div>
    </div>
  );
}

function hasSeasonStats(player: Player) {
  return [
    player.season_basic_bpr,
    player.season_gp,
    player.season_mp,
    player.season_treb,
    player.season_ast,
    player.season_stl,
    player.season_blk,
    player.season_pts,
  ].some((value) => value !== null && value !== undefined && !Number.isNaN(value));
}

function SkillRadar({ player, animate }: { player: Player; animate: boolean }) {
  const skills = [
    { label: "Spacing", value: player.skill_spacing_percentile },
    { label: "Facilitating", value: player.skill_facilitating_percentile },
    { label: "Rim Protection", value: player.skill_rim_protection_percentile },
    { label: "Defense", value: player.skill_defense_percentile },
    { label: "Finishing", value: player.skill_finishing_percentile },
  ];
  const hasAnySkill = skills.some((skill) => skill.value !== null && skill.value !== undefined && !Number.isNaN(skill.value));
  if (!hasAnySkill) return null;
  const subtitle =
    player.player_source === "hs"
      ? "Projected freshman skill percentiles"
      : "Role-shaped radar by BartTorvik PID";

  const center = 110;
  const maxRadius = 72;
  const angles = skills.map((_, index) => -90 + index * 72);
  const outerPoints = angles.map((angle) => polarPoint(center, center, maxRadius, angle));
  const labelPoints = angles.map((angle) => polarPoint(center, center, maxRadius + 11, angle));
  const polygonPoints = skills
    .map((skill, index) => {
      const value = normalizePercentile(skill.value);
      return polarPoint(center, center, maxRadius * (value / 100), angles[index]);
    })
    .map((point) => `${point.x},${point.y}`)
    .join(" ");

  return (
    <section className="rounded border border-line bg-panel px-4 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Skill Percentiles</div>
          <div className="mt-1 text-xs text-slate-500">{subtitle}</div>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-[240px_1fr] md:items-center">
        <div className="relative mx-auto h-60 w-60">
          <svg viewBox="0 0 220 220" className="h-full w-full overflow-visible">
            <g
              style={{
                transformOrigin: `${center}px ${center}px`,
                transform: animate ? "scale(1)" : "scale(0)",
                opacity: animate ? 1 : 0,
                transition: "transform 520ms cubic-bezier(0.2, 0.9, 0.2, 1), opacity 350ms ease-out",
              }}
            >
              {[0.25, 0.5, 0.75, 1].map((scale) => (
                <polygon
                  key={scale}
                  points={outerPoints
                    .map((point) => `${center + (point.x - center) * scale},${center + (point.y - center) * scale}`)
                    .join(" ")}
                  fill={scale === 1 ? "currentColor" : "none"}
                  stroke="currentColor"
                  className={scale === 1 ? "text-slate-200/50" : "text-slate-300"}
                  strokeWidth="1"
                />
              ))}
              {outerPoints.map((point, index) => (
                <line
                  key={skills[index].label}
                  x1={center}
                  y1={center}
                  x2={point.x}
                  y2={point.y}
                  stroke="currentColor"
                  className="text-slate-300"
                  strokeWidth="1"
                />
              ))}
            </g>
            <polygon
              points={polygonPoints}
              className="fill-emerald-500/25 stroke-emerald-500"
              strokeWidth="3"
              style={{
                transformOrigin: `${center}px ${center}px`,
                transform: animate ? "scale(1)" : "scale(0)",
                opacity: animate ? 1 : 0,
                transition: "transform 650ms cubic-bezier(0.2, 0.9, 0.2, 1), opacity 450ms ease-out",
              }}
            />
            {skills.map((skill, index) => {
              const value = normalizePercentile(skill.value);
              const point = polarPoint(center, center, maxRadius * (value / 100), angles[index]);
              return (
                <circle
                  key={skill.label}
                  cx={point.x}
                  cy={point.y}
                  r="4"
                  className="fill-emerald-500 stroke-white"
                  strokeWidth="2"
                  style={{
                    transformOrigin: `${center}px ${center}px`,
                    transform: animate ? "scale(1)" : "scale(0)",
                    transition: "transform 650ms cubic-bezier(0.2, 0.9, 0.2, 1)",
                  }}
                />
              );
            })}
            {skills.map((skill, index) => {
              const point = labelPoints[index];
              return (
                <text
                  key={`${skill.label}-label`}
                  x={point.x}
                  y={point.y}
                  textAnchor={radarLabelAnchor(point.x, center)}
                  dominantBaseline="middle"
                  className="fill-slate-500 text-[7px] font-semibold"
                >
                  {radarAxisLabel(skill.label)}
                </text>
              );
            })}
          </svg>
        </div>
        <div className="grid gap-2">
          {skills.map((skill) => (
            <div key={skill.label} className="grid grid-cols-[1fr_auto] items-center gap-3 rounded border border-line bg-white px-3 py-2">
              <span className="text-sm font-semibold text-slate-600">{skill.label}</span>
              <span className={clsx("min-w-14 rounded px-2 py-1 text-center text-sm font-bold tabular-nums", percentileBadgeClass(skill.value))}>
                {formatPercentile(skill.value)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function polarPoint(centerX: number, centerY: number, radius: number, angleDegrees: number) {
  const angle = (Math.PI / 180) * angleDegrees;
  return {
    x: Number((centerX + radius * Math.cos(angle)).toFixed(3)),
    y: Number((centerY + radius * Math.sin(angle)).toFixed(3)),
  };
}

function radarAxisLabel(label: string) {
  if (label === "Facilitating") return "Facil.";
  if (label === "Rim Protection") return "Rim";
  if (label === "Finishing") return "Finish";
  return label;
}

function radarLabelAnchor(x: number, center: number): "start" | "middle" | "end" {
  if (x < center - 8) return "end";
  if (x > center + 8) return "start";
  return "middle";
}

function normalizePercentile(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function formatPercentile(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return value.toFixed(2);
}

function percentileBadgeClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "border border-slate-300 bg-slate-100 text-slate-600";
  }
  if (value >= 80) return "border border-emerald-300 bg-emerald-100 text-emerald-800";
  if (value >= 60) return "border border-lime-300 bg-lime-100 text-lime-800";
  if (value >= 40) return "border border-amber-300 bg-amber-100 text-amber-800";
  if (value >= 20) return "border border-orange-300 bg-orange-100 text-orange-800";
  return "border border-rose-300 bg-rose-100 text-rose-800";
}

function formatStat(value: number | null | undefined, decimals: number) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return value.toFixed(decimals);
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(2)}%`;
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
