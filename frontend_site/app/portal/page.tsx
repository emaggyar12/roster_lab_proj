import { PlayerTable } from "@/components/PlayerTable";
import { Shell } from "@/components/Shell";
import { getPortalPlayers } from "@/lib/data";

export default function PortalPage() {
  return (
    <Shell>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-ink">Who Is In The Portal</h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
          Portal-first view for entered and committed transfer players with the same sorting and expanded player profiles.
        </p>
      </div>
      <PlayerTable players={getPortalPlayers()} playerMode="transfer" portalDefault />
    </Shell>
  );
}
