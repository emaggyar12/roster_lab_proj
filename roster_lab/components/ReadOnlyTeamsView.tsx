"use client";

import { useMemo, useState } from "react";
import { Activity, ChevronDown, Search, Users } from "lucide-react";
import clsx from "clsx";
import type { Player } from "@/data/players";
import { getPlayers, getTeamPlayers, getTeams, getTopPlaytypes } from "@/lib/data";
import { SKILL_KEYS, SKILL_LABELS, calculateTeamRatings, normalizeOptimizerPlayer } from "@/lib/optimizer";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { SourceBadge } from "@/components/StatusBadge";

export function ReadOnlyTeamsView() {
  const teams = getTeams();
  const allPlayers = getPlayers();
  const teamOptions = useMemo(() => buildTeamOptions(allPlayers, teams), [allPlayers, teams]);
  const [teamName, setTeamName] = useState(teams[0]?.team_name ?? teamOptions[0] ?? "UConn");
  const roster = useMemo(() => getTeamPlayers(teamName), [teamName]);

  return (
    <section className="space-y-4">
      <div className="grid gap-3 lg:grid-cols-[minmax(260px,420px)_1fr] lg:items-start">
        <TeamCombobox value={teamName} options={teamOptions} onChange={setTeamName} />
        <div>
          <h1 className="text-2xl font-semibold text-ink">{teamName}</h1>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
            Read-only roster scouting view.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 rounded border border-line bg-panel p-2 sm:grid-cols-4">
        <SummaryMetric label="Roster" value={`${roster.length}`} detail={`${roster.length}/15 tracked`} alert={roster.length > 15} />
        <SummaryMetric label="Proj Avg BPR" value={averageBpr(roster).toFixed(2)} />
        <SummaryMetric label="Transfers" value={`${roster.filter((player) => player.player_source === "transfer").length}`} />
        <SummaryMetric label="HS Recruits" value={`${roster.filter((player) => player.player_source === "hs").length}`} />
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(520px,1.03fr)_minmax(520px,.97fr)]">
        <ReadOnlyRosterList players={roster} />
        <div className="space-y-3">
          <TeamSkillRadar players={roster} />
          <DepthChart players={roster} />
        </div>
      </div>
    </section>
  );
}

function buildTeamOptions(players: Player[], teams: ReturnType<typeof getTeams>) {
  const names = new Set<string>();
  teams.forEach((team) => names.add(team.team_name));
  players.forEach((player) => {
    if (player.current_team) names.add(player.current_team);
    if (player.committed_team) names.add(player.committed_team);
    if (player.new_team) names.add(player.new_team);
  });
  return Array.from(names)
    .filter((name) => name && !["Uncommitted", "Unknown Team"].includes(name))
    .sort((a, b) => a.localeCompare(b));
}

function TeamCombobox({ value, options, onChange }: { value: string; options: string[]; onChange: (value: string) => void }) {
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const filtered = options.filter((option) => option.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 18);

  return (
    <div className="relative">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && filtered[0]) {
              onChange(filtered[0]);
              setQuery(filtered[0]);
              setOpen(false);
            }
          }}
          placeholder="Search college team..."
          className="h-11 w-full rounded border border-line bg-panel px-9 text-sm text-ink outline-none focus:border-ink"
        />
        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
      </div>
      {open ? (
        <div className="absolute z-20 mt-2 max-h-72 w-full overflow-auto rounded border border-line bg-white shadow-soft">
          {filtered.length ? (
            filtered.map((option) => (
              <button
                type="button"
                key={option}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onChange(option);
                  setQuery(option);
                  setOpen(false);
                }}
                className="block w-full px-3 py-2 text-left text-sm font-semibold text-slate-700 hover:bg-panel"
              >
                {option}
              </button>
            ))
          ) : (
            <div className="px-3 py-2 text-sm text-slate-500">No team found</div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function SummaryMetric({ label, value, detail, alert = false }: { label: string; value: string; detail?: string; alert?: boolean }) {
  return (
    <div className={clsx("min-h-16 rounded border bg-white px-2.5 py-2 shadow-soft", alert ? "border-rose-500/70" : "border-line")}>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold leading-none text-ink">{value}</div>
      {detail ? <div className={clsx("mt-1 line-clamp-1 text-[11px] font-semibold", alert ? "text-rose-500" : "text-slate-600")}>{detail}</div> : null}
    </div>
  );
}

function ReadOnlyRosterList({ players }: { players: Player[] }) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredPlayers = normalizedQuery
    ? players.filter((player) => [player.player_name, player.position, player.current_team, player.new_team, player.committed_team].filter(Boolean).some((value) => String(value).toLowerCase().includes(normalizedQuery)))
    : players;
  return (
    <div className="overflow-hidden rounded border border-line bg-white shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-panel px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <Users className="h-4 w-4" />
          Current Roster
        </div>
        <div className="text-xs font-semibold text-slate-500">{filteredPlayers.length}/{players.length} players</div>
      </div>
      <div className="border-b border-line bg-panel px-3 pb-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search roster..."
            className="h-8 w-full rounded border border-line bg-white px-8 text-xs font-semibold text-ink outline-none placeholder:text-slate-400 focus:border-ink dark:bg-panel"
          />
        </div>
      </div>
      <div className="h-[520px] overflow-y-auto divide-y divide-line">
        {filteredPlayers.map((player) => (
          <div key={player.player_id} className="grid gap-3 px-3 py-2.5 md:grid-cols-[1fr_auto] md:items-center">
            <PlayerLine player={player} />
            <div className="text-right text-xs font-semibold tabular-nums text-ink">BPR {player.projected_bpr.toFixed(2)}</div>
          </div>
        ))}
        {!filteredPlayers.length ? <div className="px-3 py-8 text-center text-sm text-slate-500">No roster players match that search.</div> : null}
      </div>
    </div>
  );
}

function PlayerLine({ player }: { player: Player }) {
  const topPlaytype = getTopPlaytypes(player, 1)[0]?.label || player.returning_role || "";
  return (
    <div className="flex min-w-0 items-center gap-3">
      <PlayerAvatar player={player} size="sm" />
      <div className="min-w-0">
        <div className="truncate font-semibold text-ink">{player.player_name}</div>
        <div className="mt-1 truncate text-xs text-slate-500">
          {player.position} | {player.height} | {player.current_team} | {topPlaytype}
        </div>
        <div className="mt-1">
          <SourceBadge source={player.player_source} />
        </div>
      </div>
    </div>
  );
}

function TeamSkillRadar({ players }: { players: Player[] }) {
  const optimizerPlayers = players.map(normalizeOptimizerPlayer).filter((player): player is NonNullable<ReturnType<typeof normalizeOptimizerPlayer>> => Boolean(player));
  const ratings = calculateTeamRatings(optimizerPlayers);
  const values = SKILL_KEYS.map((key) => ({ label: SKILL_LABELS[key], value: ratings[key] }));

  return (
    <div className="rounded border border-line bg-white p-3 shadow-soft">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink">
        <Activity className="h-4 w-4" />
        Team Skills Radar
      </div>
      <MiniRadar values={values} />
    </div>
  );
}

function MiniRadar({ values }: { values: Array<{ label: string; value: number }> }) {
  const center = 90;
  const maxRadius = 58;
  const angles = values.map((_, index) => -90 + index * 72);
  const outerPoints = angles.map((angle) => polarPoint(center, center, maxRadius, angle));
  const polygon = values
    .map((skill, index) => polarPoint(center, center, maxRadius * (Math.max(0, Math.min(100, skill.value)) / 100), angles[index]))
    .map((point) => `${point.x},${point.y}`)
    .join(" ");

  return (
    <div className="grid gap-2 md:grid-cols-[160px_1fr] md:items-center">
      <svg viewBox="0 0 180 180" className="mx-auto h-36 w-36 overflow-visible">
        {[0.25, 0.5, 0.75, 1].map((scale) => (
          <polygon
            key={scale}
            points={outerPoints.map((point) => `${center + (point.x - center) * scale},${center + (point.y - center) * scale}`).join(" ")}
            fill={scale === 1 ? "currentColor" : "none"}
            stroke="currentColor"
            className={scale === 1 ? "text-slate-200/50" : "text-slate-300"}
            strokeWidth="1"
          />
        ))}
        <polygon points={polygon} className="fill-emerald-500/25 stroke-emerald-500" strokeWidth="3" />
      </svg>
      <div className="space-y-2">
        {values.map((skill) => (
          <div key={skill.label} className="flex items-center justify-between rounded border border-line bg-panel px-2.5 py-1.5 text-xs">
            <span className="font-semibold text-slate-600">{skill.label}</span>
            <span className="font-semibold tabular-nums text-ink">{skill.value.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DepthChart({ players }: { players: Player[] }) {
  const groups = [
    ["Guards", players.filter((player) => ["PG", "SG", "CG"].includes(player.position))],
    ["Wings", players.filter((player) => ["SF", "PF"].includes(player.position))],
    ["Bigs", players.filter((player) => player.position === "C")],
  ] as const;
  return (
    <div className="rounded border border-line bg-white shadow-soft">
      <div className="border-b border-line px-3 py-2">
        <div className="text-sm font-semibold text-ink">Projected Depth Chart</div>
        <div className="mt-1 text-xs text-slate-500">{players.length} players sorted by projected BPR</div>
      </div>
      <div className="max-h-[300px] overflow-y-auto p-3">
        <div className="grid gap-3 lg:grid-cols-3">
          {groups.map(([label, group]) => (
            <div key={label}>
              <div className="mb-1 inline-flex rounded bg-panel px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {label} <span className="ml-2 text-slate-400">({group.length})</span>
              </div>
              <div className="space-y-0.5">
                {group
                  .slice()
                  .sort((a, b) => b.projected_bpr - a.projected_bpr)
                  .map((player) => (
                    <div key={player.player_id} className="grid grid-cols-[minmax(0,1fr)_2.25rem] items-center gap-2 text-xs">
                      <span className="truncate text-slate-700">{player.player_name}</span>
                      <span className="text-right tabular-nums text-slate-600">{player.projected_bpr.toFixed(2)}</span>
                    </div>
                  ))}
                {!group.length ? <div className="text-sm italic text-slate-400">No players</div> : null}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function averageBpr(players: Player[]) {
  if (!players.length) return 0;
  return players.reduce((sum, player) => sum + player.projected_bpr, 0) / players.length;
}

function polarPoint(centerX: number, centerY: number, radius: number, angleDegrees: number) {
  const angle = (Math.PI / 180) * angleDegrees;
  return {
    x: Number((centerX + radius * Math.cos(angle)).toFixed(3)),
    y: Number((centerY + radius * Math.sin(angle)).toFixed(3)),
  };
}
