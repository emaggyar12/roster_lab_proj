import clsx from "clsx";
import { formatStatus } from "@/lib/data";
import type { PlayerSource, PortalStatus } from "@/data/players";

const statusStyles: Record<PortalStatus, string> = {
  not_in_portal: "border-slate-300 bg-slate-100 text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200",
  entered: "border-amber-300 bg-amber-100 text-amber-800 dark:border-amber-500 dark:bg-amber-950 dark:text-amber-200",
  committed: "border-blue-300 bg-blue-100 text-blue-800 dark:border-blue-500 dark:bg-blue-950 dark:text-blue-200",
  enrolled: "border-emerald-300 bg-emerald-100 text-emerald-800 dark:border-emerald-500 dark:bg-emerald-950 dark:text-emerald-200",
  withdrawn: "border-rose-300 bg-rose-100 text-rose-800 dark:border-rose-500 dark:bg-rose-950 dark:text-rose-200",
};

const sourceStyles: Record<PlayerSource, string> = {
  transfer: "border-cyan-300 bg-cyan-100 text-cyan-800 dark:border-cyan-500 dark:bg-cyan-950 dark:text-cyan-200",
  hs: "border-violet-300 bg-violet-100 text-violet-800 dark:border-violet-500 dark:bg-violet-950 dark:text-violet-200",
  roster: "border-slate-300 bg-slate-100 text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200",
};

export function StatusBadge({ status }: { status: PortalStatus }) {
  return (
    <span
      className={clsx(
        "inline-flex h-7 items-center whitespace-nowrap rounded border px-2 text-xs font-semibold",
        statusStyles[status],
      )}
    >
      {formatStatus(status)}
    </span>
  );
}

export function SourceBadge({ source }: { source: PlayerSource }) {
  const label = source === "hs" ? "HS Recruit" : source === "transfer" ? "Transfer" : "Roster";
  return (
    <span
      className={clsx(
        "inline-flex h-7 items-center whitespace-nowrap rounded border px-2 text-xs font-semibold",
        sourceStyles[source],
      )}
    >
      {label}
    </span>
  );
}
