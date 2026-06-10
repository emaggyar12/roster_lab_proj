import { RosterOptimizer } from "@/components/RosterOptimizer";
import { Shell } from "@/components/Shell";

export default function OptimizerPage() {
  return (
    <Shell>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-ink">Optimizer</h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
          Load a roster from Roster Management, set target guard/forward/center counts, and find transfer or high-school additions that best complete the team.
        </p>
      </div>
      <RosterOptimizer />
    </Shell>
  );
}
