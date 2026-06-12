import { PortalSimulator } from "@/components/PortalSimulator";
import { Shell } from "@/components/Shell";

export default function RostersPage() {
  return (
    <Shell>
      <div className="mb-3">
        <h1 className="text-2xl font-semibold text-ink">Roster Management</h1>
      </div>
      <PortalSimulator />
    </Shell>
  );
}
