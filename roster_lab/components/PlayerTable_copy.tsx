"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpDown, ChevronDown, Search, SlidersHorizontal } from "lucide-react";
import clsx from "clsx";
import type { Player, PlayerSource } from "@/data/players";
import { getTopPlaytypes } from "@/lib/data";
import { PlayerDetailPanel } from "@/components/PlayerDetailPanel";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { SourceBadge, StatusBadge } from "@/components/StatusBadge";

type SortKey = "projected_bpr" | "fit_score" | "player_name" | "hs_rating" | "hs_stars";
type SortDirection = "asc" | "desc";
export type PlayerMode = "all" | "hs" | "transfer";

export function PlayerTable({
  players,
  playerMode = "all",
  portalDefault = false,
}: {
  players: Player[];
  playerMode?: PlayerMode;
  portalDefault?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState("all");
  const [status, setStatus] = useState("all");
  const [teamQuery, setTeamQuery] = useState("");
  const [classYear, setClassYear] = useState("all");
  const [conference, setConference] = useState("all");
  const [playtype, setPlaytype] = useState("all");
  const [stars, setStars] = useState("all");
  const [minRating, setMinRating] = useState(0);
  const [minBpr, setMinBpr] = useState(0);
  const [portalOnly, setPortalOnly] = useState(portalDefault);
  const [sortKey, setSortKey] = useState<SortKey>("projected_bpr");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [displayCount, setDisplayCount] = useState("20");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const isHsMode = playerMode === "hs";

  const modePlayers = useMemo(
    () => players.filter((player) => playerMode === "all" || player.player_source === playerMode),
    [playerMode, players],
  );

  useEffect(() => {
    setPosition("all");
    setStatus("all");
    setTeamQuery("");
    setClassYear("all");
    setConference("all");
    setPlaytype("all");
    setStars("all");
    setMinRating(0);
    setMinBpr(0);
    setPortalOnly(portalDefault);
    setSortKey(playerMode === "hs" ? "hs_rating" : "projected_bpr");
    setSortDirection("desc");
    setDisplayCount("20");
    setExpandedIds(new Set());
  }, [playerMode, portalDefault]);

  const options = useMemo(() => {
    const unique = (values: string[]) => Array.from(new Set(values.filter(Boolean))).sort();
    return {
      teams: unique(modePlayers.flatMap((player) => [player.current_team, player.committed_team ?? ""])),
      conferences: unique(modePlayers.map((player) => player.conference)),
      playtypes: unique(modePlayers.map((player) => getTopPlaytypes(player, 1)[0]?.label ?? "")),
      stars: unique(modePlayers.map((player) => (player.hs_stars ? `${player.hs_stars}` : ""))),
    };
  }, [modePlayers]);

  const playerSuggestions = useMemo(
    () => Array.from(new Set(modePlayers.map((player) => player.player_name))).sort(),
    [modePlayers],
  );

  const filteredPlayers = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const normalizedTeamQuery = teamQuery.trim().toLowerCase();
    return modePlayers
      .filter((player) => {
        const topPlaytype = getTopPlaytypes(player, 1)[0]?.label;
        return (
          (!normalizedQuery || player.player_name.toLowerCase().includes(normalizedQuery)) &&
          (position === "all" || player.position === position) &&
          (isHsMode || status === "all" || player.portal_status === status) &&
          (!normalizedTeamQuery ||
            player.current_team.toLowerCase().includes(normalizedTeamQuery) ||
            player.committed_team?.toLowerCase().includes(normalizedTeamQuery)) &&
          (isHsMode || classYear === "all" || player.class_year === classYear) &&
          (isHsMode || conference === "all" || player.conference === conference) &&
          (playtype === "all" || topPlaytype === playtype) &&
          (!isHsMode || stars === "all" || `${player.hs_stars}` === stars) &&
          (!isHsMode || !minRating || (player.hs_rating ?? 0) >= minRating) &&
          (isHsMode || player.projected_bpr >= minBpr) &&
          (isHsMode || !portalOnly || player.is_in_portal)
        );
      })
      .sort((a, b) => {
        const multiplier = sortDirection === "asc" ? 1 : -1;
        if (sortKey === "player_name") return multiplier * a.player_name.localeCompare(b.player_name);
        if (sortKey === "hs_rating" || sortKey === "hs_stars") return multiplier * ((a[sortKey] ?? 0) - (b[sortKey] ?? 0));
        return multiplier * (a[sortKey] - b[sortKey]);
      });
  }, [classYear, conference, isHsMode, minBpr, minRating, modePlayers, playtype, portalOnly, position, query, sortDirection, sortKey, stars, status, teamQuery]);

  const visiblePlayers = useMemo(() => {
    if (displayCount === "all") return filteredPlayers;
    return filteredPlayers.slice(0, Number(displayCount));
  }, [displayCount, filteredPlayers]);

  function updateSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection(nextKey === "player_name" ? "asc" : "desc");
  }

  return (
    <section className="space-y-4">
      <div className="rounded border border-line bg-white p-4 shadow-soft">
        <div className={isHsMode ? "grid gap-3 xl:grid-cols-[1.4fr_repeat(5,minmax(128px,1fr))]" : "grid gap-3 xl:grid-cols-[1.3fr_repeat(7,minmax(112px,1fr))]"}>
          <AutocompleteInput label="Search player" value={query} onChange={setQuery} suggestions={playerSuggestions} icon />
          <FilterSelect label="Position" value={position} onChange={setPosition} options={["all", "PG", "SG", "CG", "SF", "PF", "C"]} />
          {!isHsMode ? <FilterSelect label="Class" value={classYear} onChange={setClassYear} options={["all", "Fr", "So", "Jr", "Sr", "Gr"]} /> : null}
          {!isHsMode ? <FilterSelect label="Status" value={status} onChange={setStatus} options={["all", "entered", "committed", "enrolled", "not_in_portal"]} /> : null}
          <AutocompleteInput label="Team" value={teamQuery} onChange={setTeamQuery} suggestions={options.teams} />
          {!isHsMode ? <FilterSelect label="Conference" value={conference} onChange={setConference} options={["all", ...options.conferences]} /> : null}
          <FilterSelect label="Playtype" value={playtype} onChange={setPlaytype} options={["all", ...options.playtypes]} />
          {isHsMode ? <FilterSelect label="Stars" value={stars} onChange={setStars} options={["all", ...options.stars]} /> : null}
          {isHsMode ? (
          <label className="grid h-10 grid-cols-[1fr_56px] items-center rounded border border-line bg-panel px-2 text-xs font-semibold text-slate-500">
            Rating
            <input
              type="number"
              min={0}
              max={100}
              step={0.5}
              value={minRating}
              onChange={(event) => setMinRating(Number(event.target.value))}
              className="h-7 rounded border border-line bg-white px-2 text-sm text-ink outline-none"
            />
          </label>
          ) : (
          <label className="grid h-10 grid-cols-[1fr_56px] items-center rounded border border-line bg-panel px-2 text-xs font-semibold text-slate-500">
            BPR
            <input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={minBpr}
              onChange={(event) => setMinBpr(Number(event.target.value))}
              className="h-7 rounded border border-line bg-white px-2 text-sm text-ink outline-none"
            />
          </label>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          {!isHsMode ? (
          <button
            type="button"
            onClick={() => setPortalOnly((value) => !value)}
            className={clsx(
              "inline-flex h-9 items-center gap-2 rounded border px-3 text-sm font-semibold",
              portalOnly
                ? "border-emerald-600 bg-emerald-600 text-white dark:border-emerald-400 dark:bg-emerald-500 dark:text-slate-950"
                : "border-line bg-panel text-slate-700 dark:text-slate-200",
            )}
          >
            <SlidersHorizontal className="h-4 w-4" />
            In Portal
          </button>
          ) : <div />}
          <div className="text-sm text-slate-600">
            Showing {visiblePlayers.length} of {filteredPlayers.length} players
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded border border-line bg-white shadow-soft">
        {isHsMode ? (
        <div className="hidden gap-3 grid-cols-[2.2fr_.7fr_1.2fr_.7fr_.8fr_.9fr_44px] border-b border-line bg-panel px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 md:grid md:items-center">
          <SortButton label="Player" active={sortKey === "player_name"} direction={sortDirection} onClick={() => updateSort("player_name")} className="justify-self-start" />
          <div className="w-full text-center">Pos</div>
          <div className="w-full text-center">Committed School</div>
          <SortButton label="Stars" active={sortKey === "hs_stars"} direction={sortDirection} onClick={() => updateSort("hs_stars")} align="center" className="w-full" />
          <SortButton label="Rating" active={sortKey === "hs_rating"} direction={sortDirection} onClick={() => updateSort("hs_rating")} align="center" className="w-full" />
          <div className="w-full text-center">Type</div>
          <div />
        </div>
        ) : (
        <div className="hidden gap-3 grid-cols-[2.2fr_.7fr_1fr_.8fr_.9fr_.7fr_.7fr_44px] border-b border-line bg-panel px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 md:grid md:items-center">
          <SortButton label="Player" active={sortKey === "player_name"} direction={sortDirection} onClick={() => updateSort("player_name")} className="justify-self-start" />
          <div className="w-full text-center">Pos</div>
          <div className="w-full text-center">Team</div>
          <div className="w-full text-center">Status</div>
          <div className="w-full text-center">Type</div>
          <SortButton label="BPR" active={sortKey === "projected_bpr"} direction={sortDirection} onClick={() => updateSort("projected_bpr")} align="center" className="w-full" />
          <SortButton label="Fit" active={sortKey === "fit_score"} direction={sortDirection} onClick={() => updateSort("fit_score")} align="center" className="w-full" />
          <div />
        </div>
        )}

        {visiblePlayers.map((player) => {
          const topPlaytype = getTopPlaytypes(player, 1)[0];
          const expanded = expandedIds.has(player.player_id);
          return (
            <article key={player.player_id} className="border-b border-line last:border-b-0">
              <button
                type="button"
                onClick={() =>
                  setExpandedIds((current) => {
                    const next = new Set(current);
                    if (next.has(player.player_id)) {
                      next.delete(player.player_id);
                    } else {
                      next.add(player.player_id);
                    }
                    return next;
                  })
                }
                className={clsx(
                  "grid w-full gap-3 px-4 py-4 text-left hover:bg-panel md:items-center",
                  isHsMode
                    ? "md:grid-cols-[2.2fr_.7fr_1.2fr_.7fr_.8fr_.9fr_44px]"
                    : "md:grid-cols-[2.2fr_.7fr_1fr_.8fr_.9fr_.7fr_.7fr_44px]",
                )}
              >
                <div className="flex min-w-0 items-center gap-3 justify-self-start">
                  <PlayerAvatar player={player} />
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-ink">{player.player_name}</div>
                    <div className="mt-1 truncate text-xs text-slate-500">
                      {player.height} | {player.weight || "N/A"} | {player.class_year} | {topPlaytype?.label}
                    </div>
                  </div>
                </div>
                <div className="w-full text-center text-sm font-semibold text-slate-700">{player.position}</div>
                <div className="w-full text-center text-sm text-slate-700">
                  {player.committed_team ?? player.current_team}
                  {player.committed_team ? <span className="block text-xs text-slate-500">from {player.current_team}</span> : null}
                </div>
                {isHsMode ? (
                  <>
                    <TableNumber value={formatOptional(player.hs_stars, 0)} label="Stars" />
                    <TableNumber value={formatOptional(player.hs_rating, 2)} label="Rating" />
                    <div className="w-full text-center">
                      <SourceBadge source={player.player_source} />
                    </div>
                  </>
                ) : (
                  <>
                <div className="w-full text-center">
                  <StatusBadge status={player.portal_status} />
                </div>
                <div className="w-full text-center">
                  <SourceBadge source={player.player_source} />
                </div>
                <TableNumber value={player.projected_bpr.toFixed(2)} label="BPR" />
                <TableNumber value={`${player.fit_score}`} label="Fit" />
                  </>
                )}
                <ChevronDown className={clsx("h-5 w-5 justify-self-end text-slate-500 transition", expanded && "rotate-180")} />
              </button>
              {expanded ? <PlayerDetailPanel player={player} /> : null}
            </article>
          );
        })}
      </div>
      <div className="flex items-center justify-end gap-2 text-sm text-slate-600">
        <span>Rows</span>
        <select
          value={displayCount}
          onChange={(event) => setDisplayCount(event.target.value)}
          className="h-9 rounded border border-line bg-panel px-3 text-sm text-ink outline-none focus:border-ink"
        >
          {["10", "20", "50", "100", "all"].map((option) => (
            <option key={option} value={option}>
              {option === "all" ? "All" : option}
            </option>
          ))}
        </select>
      </div>
    </section>
  );
}

function formatOptional(value: number | null | undefined, decimals: number) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return value.toFixed(decimals);
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <label className="relative block">
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full appearance-none rounded border border-line bg-panel px-3 pr-8 text-sm outline-none focus:border-ink"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option === "all" ? label : option.replaceAll("_", " ")}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
    </label>
  );
}

function AutocompleteInput({
  label,
  value,
  onChange,
  suggestions,
  icon = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  suggestions: string[];
  icon?: boolean;
}) {
  const [focused, setFocused] = useState(false);
  const filteredSuggestions = useMemo(() => {
    const normalized = value.trim().toLowerCase();
    const values = normalized
      ? suggestions.filter((suggestion) => suggestion.toLowerCase().includes(normalized))
      : suggestions;
    return values.slice(0, 80);
  }, [suggestions, value]);

  return (
    <label className="relative block">
      {icon ? <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /> : null}
      <input
        value={value}
        onFocus={() => setFocused(false)}
        onBlur={() => window.setTimeout(() => setFocused(false), 120)}
        onChange={(event) => {
          onChange(event.target.value);
          setFocused(true);
        }}
        className={clsx(
          "h-10 w-full rounded border border-line bg-panel pr-9 text-sm outline-none focus:border-ink",
          icon ? "pl-9" : "pl-3",
        )}
        placeholder={label}
      />
      <button
        type="button"
        aria-label={`Show ${label} options`}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setFocused((open) => !open)}
        className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded text-slate-500 hover:bg-panel"
      >
        <ChevronDown className={clsx("h-4 w-4 transition", focused && "rotate-180")} />
      </button>
      {focused && filteredSuggestions.length ? (
        <div className="absolute left-0 right-0 top-11 z-20 max-h-72 overflow-auto rounded border border-line bg-white py-1 shadow-soft">
          {filteredSuggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                onChange(suggestion);
                setFocused(false);
              }}
              className="block w-full truncate px-3 py-2 text-left text-sm text-ink hover:bg-panel"
            >
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}
    </label>
  );
}

function SortButton({
  label,
  active,
  direction,
  onClick,
  align = "left",
  className,
}: {
  label: string;
  active: boolean;
  direction: SortDirection;
  onClick: () => void;
  align?: "left" | "center";
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "inline-flex items-center gap-1",
        align === "center" ? "justify-center text-center" : "justify-start text-left",
        active ? "text-ink" : "text-slate-500",
        className,
      )}
    >
      {label}
      <ArrowUpDown
        className={clsx(
          "h-3.5 w-3.5 transition",
          active && direction === "desc" && "rotate-180",
        )}
      />
    </button>
  );
}

function TableNumber({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm font-semibold tabular-nums text-ink md:w-full md:justify-center md:text-center">
      <span className="text-xs font-medium text-slate-500 md:hidden">{label}</span>
      <span>{value}</span>
    </div>
  );
}
