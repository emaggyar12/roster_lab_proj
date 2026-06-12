"use client";

import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { Activity, ChevronDown, ClipboardCheck, RotateCcw, Search, UserCheck, Users, X } from "lucide-react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import type { Player } from "@/data/players";
import { getHsPlayers, getPlayers, getPortalPlayers, getTeamPlayers, getTeams, getTopPlaytypes } from "@/lib/data";
import { SKILL_KEYS, SKILL_LABELS, calculateTeamRatings, normalizeOptimizerPlayer } from "@/lib/optimizer";
import { saveOptimizerRoster } from "@/lib/optimizerStorage";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { SourceBadge } from "@/components/StatusBadge";

type TargetPool = "transfer" | "hs" | "all";
type WorkbenchView = "roster" | "browse";
type TargetSort = "bpr_desc" | "bpr_asc" | "name_asc";
type PortalStatusFilter = "all" | "entered" | "committed" | "enrolled" | "withdrawn";

const ROSTER_LIMIT = 15;
const PORTAL_STATUS_SET = new Set(["not_in_portal", "entered", "committed", "enrolled", "withdrawn"]);
const ROSTER_MANAGEMENT_STORAGE_KEY = "roster-lab-roster-management-state";

type SavedRosterManagementState = {
  teamName: string;
  removedIds: string[];
  addedIds: string[];
  targetPool: TargetPool;
  workbenchView: WorkbenchView;
};

function readSavedRosterManagementState(): SavedRosterManagementState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(ROSTER_MANAGEMENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SavedRosterManagementState>;
    if (!parsed.teamName || !Array.isArray(parsed.removedIds) || !Array.isArray(parsed.addedIds)) return null;
    return {
      teamName: parsed.teamName,
      removedIds: parsed.removedIds.filter((id): id is string => typeof id === "string"),
      addedIds: parsed.addedIds.filter((id): id is string => typeof id === "string"),
      targetPool: parsed.targetPool === "hs" || parsed.targetPool === "all" ? parsed.targetPool : "transfer",
      workbenchView: parsed.workbenchView === "browse" ? "browse" : "roster",
    };
  } catch {
    return null;
  }
}

export function PortalSimulator() {
  const router = useRouter();
  const teams = getTeams();
  const allPlayers = getPlayers();
  const teamOptions = useMemo(() => buildTeamOptions(allPlayers, teams), [allPlayers, teams]);
  const savedState = useMemo(readSavedRosterManagementState, []);
  const [teamName, setTeamName] = useState(savedState?.teamName ?? teams[0]?.team_name ?? teamOptions[0] ?? "UConn");
  const [removedIds, setRemovedIds] = useState<string[]>(savedState?.removedIds ?? []);
  const [addedIds, setAddedIds] = useState<string[]>(savedState?.addedIds ?? []);
  const [targetPool, setTargetPool] = useState<TargetPool>(savedState?.targetPool ?? "transfer");
  const [workbenchView, setWorkbenchView] = useState<WorkbenchView>(savedState?.workbenchView ?? "roster");

  const currentRoster = useMemo(() => getTeamPlayers(teamName), [teamName]);
  const transferTargets = useMemo(() => getPortalPlayers(), []);
  const hsTargets = useMemo(() => getHsPlayers(), []);
  const targetPlayers = useMemo(() => {
    const pool =
      targetPool === "transfer"
        ? transferTargets
        : targetPool === "hs"
          ? hsTargets
          : [...transferTargets, ...hsTargets];
    return pool.filter((player) => !currentRoster.some((rosterPlayer) => rosterPlayer.player_id === player.player_id));
  }, [currentRoster, hsTargets, targetPool, transferTargets]);

  const removedPlayers = currentRoster.filter((player) => removedIds.includes(player.player_id));
  const addedPlayers = targetPlayers.filter((player) => addedIds.includes(player.player_id));
  const activeRoster = currentRoster.filter((player) => !removedIds.includes(player.player_id));
  const projectedRoster = [...activeRoster, ...addedPlayers];
  const projectedBpr =
    projectedRoster.length === 0
      ? 0
      : projectedRoster.reduce((total, player) => total + player.projected_bpr, 0) / projectedRoster.length;
  const scholarshipCount = Math.max(0, currentRoster.length - removedPlayers.length + addedPlayers.length);
  const isOverRosterLimit = scholarshipCount > ROSTER_LIMIT;

  useEffect(() => {
    window.localStorage.setItem(
      ROSTER_MANAGEMENT_STORAGE_KEY,
      JSON.stringify({ teamName, removedIds, addedIds, targetPool, workbenchView }),
    );
  }, [addedIds, removedIds, targetPool, teamName, workbenchView]);

  function resetScenario() {
    setRemovedIds([]);
    setAddedIds([]);
    window.localStorage.removeItem(ROSTER_MANAGEMENT_STORAGE_KEY);
  }

  function selectTeam(nextTeamName: string) {
    setTeamName(nextTeamName);
    resetScenario();
  }

  function toggleRemoved(playerId: string) {
    setRemovedIds((ids) => (ids.includes(playerId) ? ids.filter((id) => id !== playerId) : [...ids, playerId]));
  }

  function toggleAdded(playerId: string) {
    setAddedIds((ids) => (ids.includes(playerId) ? ids.filter((id) => id !== playerId) : [...ids, playerId]));
  }

  function loadToOptimizer() {
    saveOptimizerRoster({
      teamName,
      playerIds: projectedRoster.map((player) => player.player_id),
      loadedAt: new Date().toISOString(),
    });
    router.push("/optimizer");
  }

  const summaryMetrics = (
    <div className="grid grid-cols-2 gap-2 rounded border border-line bg-panel p-2 sm:grid-cols-4">
      <SummaryMetric
        label="Roster"
        value={`${projectedRoster.length}`}
        detail={`${scholarshipCount}/${ROSTER_LIMIT} spots`}
        alert={isOverRosterLimit}
      />
      <SummaryMetric label="Proj Avg BPR" value={projectedBpr.toFixed(2)} />
      <SummaryMetric label="Departures" value={`${removedPlayers.length}`} />
      <SummaryMetric label="Arrivals" value={`${addedPlayers.length}`} />
    </div>
  );

  return (
    <section className="space-y-2">
      <div className="grid gap-2 lg:grid-cols-[minmax(260px,420px)_auto] lg:items-start">
        <TeamCombobox value={teamName} options={teamOptions} onChange={selectTeam} />
        <div className="flex flex-wrap justify-start gap-2 lg:justify-end">
          <button
            type="button"
            onClick={loadToOptimizer}
            className="inline-flex h-9 items-center justify-center gap-2 rounded bg-emerald-600 px-3 text-sm font-semibold text-white hover:bg-emerald-700 dark:bg-emerald-500 dark:text-slate-950"
          >
            <ClipboardCheck className="h-4 w-4" />
            Load to Optimizer
          </button>
          <button
            type="button"
            onClick={resetScenario}
            className="inline-flex h-9 items-center justify-center gap-2 rounded border border-line bg-panel px-3 text-sm font-semibold text-slate-700"
          >
            <RotateCcw className="h-4 w-4" />
            Reset
          </button>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(520px,1.03fr)_minmax(520px,.97fr)]">
        <div className="space-y-3">
          <div className="grid grid-cols-2 rounded border border-line bg-panel p-1">
            {[
              ["roster", "Current Roster"],
              ["browse", "Browse Portal"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setWorkbenchView(value as WorkbenchView)}
                className={
                  workbenchView === value
                    ? "h-9 rounded bg-emerald-600 px-4 text-sm font-semibold text-white dark:bg-emerald-500 dark:text-slate-950"
                    : "h-9 rounded px-4 text-sm font-semibold text-slate-600 hover:bg-surface dark:text-slate-300"
                }
              >
                {label}
              </button>
            ))}
          </div>

          {workbenchView === "roster" ? (
            <RosterDecisionList players={currentRoster} selectedIds={removedIds} onToggle={toggleRemoved} />
          ) : (
            <TargetBrowser
              players={targetPlayers}
              selectedIds={addedIds}
              onToggle={toggleAdded}
              targetPool={targetPool}
              onTargetPoolChange={(pool) => {
                setTargetPool(pool);
                setAddedIds([]);
              }}
            />
          )}
          {summaryMetrics}
        </div>

        <div className="space-y-3">
          <IncomingPlayers players={addedPlayers} onRemove={toggleAdded} />
          <div className="grid gap-3">
            <TeamSkillRadar players={projectedRoster} />
            <DepthChart players={projectedRoster} addedIds={addedIds} />
          </div>
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
  const filtered = options
    .filter((option) => option.toLowerCase().includes(query.trim().toLowerCase()))
    .slice(0, 18);

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

function targetDisplayBpr(player: Player) {
  if (player.player_source === "transfer") return player.transfer_bpr ?? null;
  if (player.player_source === "hs") return player.hs_bpr ?? player.projected_bpr;
  return player.projected_bpr;
}

function targetSortBpr(player: Player) {
  return targetDisplayBpr(player) ?? Number.NEGATIVE_INFINITY;
}

function formatTargetBpr(player: Player) {
  const value = targetDisplayBpr(player);
  return value == null ? "N/A" : value.toFixed(2);
}

function RosterDecisionList({
  players,
  selectedIds,
  onToggle,
}: {
  players: Player[];
  selectedIds: string[];
  onToggle: (playerId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const filteredPlayers = useMemo(() => {
    const normalizedQuery = normalizeSearch(query);
    if (!normalizedQuery) return players;
    return players.filter((player) => playerMatchesQuery(player, normalizedQuery));
  }, [players, query]);

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
        <SearchInput value={query} onChange={setQuery} placeholder="Search roster..." />
      </div>
      <div className="h-[430px] overflow-y-auto divide-y divide-line">
        {filteredPlayers.map((player) => {
          const leaving = selectedIds.includes(player.player_id);
          return (
            <div
              key={player.player_id}
              className={clsx(
                "grid gap-3 px-3 py-2.5 md:grid-cols-[118px_1fr_auto] md:items-center",
                leaving && "bg-rose-50 dark:bg-rose-950",
              )}
            >
              <div className="flex items-center gap-3 text-sm">
                <DecisionButton active={!leaving} label="Stay" onClick={() => leaving && onToggle(player.player_id)} tone="stay" />
                <DecisionButton active={leaving} label="Leave" onClick={() => !leaving && onToggle(player.player_id)} tone="leave" />
              </div>
              <PlayerLine player={player} added={false} crossedOut={leaving} />
              <div className="text-right text-xs font-semibold tabular-nums text-ink">BPR {player.projected_bpr.toFixed(2)}</div>
            </div>
          );
        })}
        {!filteredPlayers.length ? <div className="px-3 py-8 text-center text-sm text-slate-500">No roster players match that search.</div> : null}
      </div>
    </div>
  );
}

function DecisionButton({ active, label, onClick, tone }: { active: boolean; label: string; onClick: () => void; tone: "stay" | "leave" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "inline-flex items-center gap-1 text-xs font-semibold",
        active ? (tone === "stay" ? "text-emerald-700" : "text-rose-700") : "text-slate-400",
      )}
    >
      <span className={clsx("h-4 w-4 rounded-full border", active ? (tone === "stay" ? "border-emerald-500 bg-emerald-500" : "border-rose-500 bg-rose-500") : "border-slate-400")} />
      {label}
    </button>
  );
}

function TargetBrowser({
  players,
  selectedIds,
  onToggle,
  targetPool,
  onTargetPoolChange,
}: {
  players: Player[];
  selectedIds: string[];
  onToggle: (playerId: string) => void;
  targetPool: TargetPool;
  onTargetPoolChange: (pool: TargetPool) => void;
}) {
  const [query, setQuery] = useState("");
  const [classFilter, setClassFilter] = useState("all");
  const [positionFilter, setPositionFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<PortalStatusFilter>("all");
  const [sort, setSort] = useState<TargetSort>("bpr_desc");
  const [filtersOpen, setFiltersOpen] = useState(false);

  const classOptions = useMemo(() => uniqueValues(players.map((player) => player.class_year)), [players]);
  const positionOptions = useMemo(() => uniqueValues(players.map((player) => player.position)), [players]);
  const statusOptions = useMemo(
    () =>
      uniqueValues(
        players
          .filter((player) => player.player_source === "transfer")
          .map((player) => toPortalStatus(player.transfer_247_status) ?? toPortalStatus(player.portal_status) ?? ""),
      ),
    [players],
  );
  const filteredPlayers = useMemo(() => {
    const normalizedQuery = normalizeSearch(query);
    return players
      .filter((player) => (normalizedQuery ? playerMatchesQuery(player, normalizedQuery) : true))
      .filter((player) => classFilter === "all" || player.class_year === classFilter)
      .filter((player) => positionFilter === "all" || player.position === positionFilter)
      .filter((player) => {
        if (statusFilter === "all" || player.player_source !== "transfer") return true;
        return (toPortalStatus(player.transfer_247_status) ?? toPortalStatus(player.portal_status)) === statusFilter;
      })
      .slice()
      .sort((left, right) => {
        if (sort === "bpr_asc") return targetSortBpr(left) - targetSortBpr(right);
        if (sort === "name_asc") return left.player_name.localeCompare(right.player_name);
        return targetSortBpr(right) - targetSortBpr(left);
      });
  }, [classFilter, players, positionFilter, query, sort, statusFilter]);

  return (
    <div className="overflow-hidden rounded border border-line bg-white shadow-soft">
      <div className="grid grid-cols-3 border-b border-line bg-panel p-1">
        {[
          ["transfer", "Transfers"],
          ["hs", "High School"],
          ["all", "Both"],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => onTargetPoolChange(value as TargetPool)}
            className={
              targetPool === value
                ? "h-8 rounded bg-emerald-600 px-3 text-sm font-semibold text-white dark:bg-emerald-500 dark:text-slate-950"
                : "h-8 rounded px-3 text-sm font-semibold text-slate-600 hover:bg-surface dark:text-slate-300"
            }
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 border-b border-line bg-panel px-3 py-1.5 text-sm font-semibold text-ink">
        <UserCheck className="h-4 w-4" />
        Browse Targets
        <span className="ml-auto text-xs font-semibold text-slate-500">{filteredPlayers.length} shown</span>
      </div>
      <div className="grid gap-2 border-b border-line bg-panel px-3 py-1.5 sm:grid-cols-[minmax(180px,1fr)_auto]">
        <SearchInput value={query} onChange={setQuery} placeholder="Search targets..." />
        <button
          type="button"
          onClick={() => setFiltersOpen((open) => !open)}
          className={clsx(
            "h-8 rounded border px-3 text-xs font-semibold",
            filtersOpen || classFilter !== "all" || positionFilter !== "all" || statusFilter !== "all" || sort !== "bpr_desc"
              ? "border-emerald-500 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
              : "border-line bg-white text-slate-700 dark:bg-panel dark:text-slate-200",
          )}
        >
          Filters
        </button>
      </div>
      {filtersOpen ? (
        <div className="grid gap-2 border-b border-line bg-panel px-3 py-1.5 sm:grid-cols-4">
          <FilterSelect value={classFilter} onChange={setClassFilter} options={classOptions} label="Class" />
          <FilterSelect value={positionFilter} onChange={setPositionFilter} options={positionOptions} label="POS" />
          <FilterSelect value={statusFilter} onChange={(value) => setStatusFilter(value as PortalStatusFilter)} options={statusOptions} label="Status" />
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as TargetSort)}
            className="h-8 rounded border border-line bg-white px-2 text-xs font-semibold text-slate-700 outline-none focus:border-ink dark:bg-panel dark:text-slate-200"
            aria-label="Sort targets"
          >
            <option value="bpr_desc">BPR ↓</option>
            <option value="bpr_asc">BPR ↑</option>
            <option value="name_asc">Name A-Z</option>
          </select>
        </div>
      ) : null}
      <div className={clsx("overflow-y-auto divide-y divide-line", filtersOpen ? "h-[360px]" : "h-[395px]")}>
        {filteredPlayers.map((player) => {
          const selected = selectedIds.includes(player.player_id);
          return (
            <button
              type="button"
              key={player.player_id}
              onClick={() => onToggle(player.player_id)}
              className={clsx(
                "grid w-full grid-cols-[1fr_auto] items-center gap-3 px-3 py-2 text-left hover:bg-panel",
                selected && "bg-emerald-50 dark:bg-emerald-950",
              )}
            >
              <PlayerLine player={player} added={selected} />
              <div className="flex items-center gap-3">
                <span className="text-xs font-semibold tabular-nums text-ink">BPR {formatTargetBpr(player)}</span>
                <span className={clsx("flex h-8 w-8 items-center justify-center rounded border", selected ? "border-emerald-600 bg-emerald-600 text-white" : "border-line bg-panel text-slate-700")}>
                  {selected ? <X className="h-4 w-4" /> : "+"}
                </span>
              </div>
            </button>
          );
        })}
        {!filteredPlayers.length ? <div className="px-3 py-8 text-center text-sm text-slate-500">No targets match those filters.</div> : null}
      </div>
    </div>
  );
}

function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-8 w-full rounded border border-line bg-white px-8 text-xs font-semibold text-ink outline-none placeholder:text-slate-400 focus:border-ink dark:bg-panel"
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
          aria-label="Clear search"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

function FilterSelect({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  label: string;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-8 rounded border border-line bg-white px-2 text-xs font-semibold text-slate-700 outline-none focus:border-ink dark:bg-panel dark:text-slate-200"
      aria-label={`Filter by ${label}`}
    >
      <option value="all">{label}: All</option>
      {options.map((option) => (
        <option key={option} value={option}>
          {label}: {option}
        </option>
      ))}
    </select>
  );
}

function PlayerLine({ player, added, crossedOut = false }: { player: Player; added: boolean; crossedOut?: boolean }) {
  const topPlaytype = getTopPlaytypes(player, 1)[0]?.label || player.returning_role || "";
  return (
    <div className="flex min-w-0 items-center gap-3">
      <PlayerAvatar player={player} size="sm" />
      <div className="min-w-0">
        <div className={clsx("truncate font-semibold", added ? "text-emerald-700" : "text-ink", crossedOut && "line-through decoration-2")}>{added ? "+ " : ""}{player.player_name}</div>
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

function IncomingPlayers({ players, onRemove }: { players: Player[]; onRemove: (playerId: string) => void }) {
  const incomingBpr = players.reduce((sum, player) => sum + player.projected_bpr, 0);
  return (
    <div className="rounded border border-emerald-200 bg-emerald-50 p-3 shadow-soft dark:border-emerald-900 dark:bg-emerald-950">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">Incoming Players ({players.length})</div>
        <div className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">+{incomingBpr.toFixed(2)} BPR</div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {players.length ? (
          players.map((player) => (
            <div key={player.player_id} className="rounded border border-emerald-200 bg-white px-2.5 py-1.5 shadow-soft dark:border-emerald-800 dark:bg-panel">
              <div className="flex items-start gap-2">
                <div>
                  <div className="text-sm font-semibold text-ink">{player.player_name}</div>
                  <div className="mt-1 text-xs text-slate-500">{player.current_team} · +{player.projected_bpr.toFixed(2)} BPR</div>
                </div>
                <button type="button" onClick={() => onRemove(player.player_id)} className="text-rose-500 hover:text-rose-700">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="text-sm text-slate-500">No additions selected.</div>
        )}
      </div>
    </div>
  );
}

function DepthChart({ players, addedIds }: { players: Player[]; addedIds: string[] }) {
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
      <div className="max-h-[255px] overflow-y-auto p-3">
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
                    <span className={clsx("truncate", addedIds.includes(player.player_id) ? "font-semibold text-emerald-700" : "text-slate-700")}>
                      {addedIds.includes(player.player_id) ? "+ " : ""}{player.player_name}
                    </span>
                    <span className={clsx("text-right tabular-nums", addedIds.includes(player.player_id) ? "font-semibold text-emerald-700" : "text-slate-600")}>{player.projected_bpr.toFixed(2)}</span>
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

function TeamSkillRadar({ players }: { players: Player[] }) {
  const optimizerPlayers = players.map(normalizeOptimizerPlayer).filter((player): player is NonNullable<ReturnType<typeof normalizeOptimizerPlayer>> => Boolean(player));
  const ratings = calculateTeamRatings(optimizerPlayers);
  const values = SKILL_KEYS.map((key) => ({
    label: SKILL_LABELS[key],
    value: ratings[key],
  }));

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
    .map((skill, index) => polarPoint(center, center, maxRadius * (skill.value / 100), angles[index]))
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

function polarPoint(centerX: number, centerY: number, radius: number, angleDegrees: number) {
  const angle = (Math.PI / 180) * angleDegrees;
  return {
    x: Number((centerX + radius * Math.cos(angle)).toFixed(3)),
    y: Number((centerY + radius * Math.sin(angle)).toFixed(3)),
  };
}

function normalizeSearch(value: string) {
  return value.trim().toLowerCase();
}

function playerMatchesQuery(player: Player, normalizedQuery: string) {
  const topPlaytype = getTopPlaytypes(player, 1)[0]?.label || player.returning_role || "";
  return [
    player.player_name,
    player.current_team,
    player.previous_team,
    player.new_team,
    player.committed_team,
    player.position,
    player.class_year,
    topPlaytype,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalizedQuery));
}

function uniqueValues(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value) && value !== "N/A"))).sort((a, b) =>
    a.localeCompare(b),
  );
}

function toPortalStatus(value: string | null | undefined) {
  if (!value) return null;
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "_");
  return PORTAL_STATUS_SET.has(normalized) ? normalized : null;
}
