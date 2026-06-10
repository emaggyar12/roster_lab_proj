import { ReadOnlyTeamsView } from "@/components/ReadOnlyTeamsView";
import { Shell } from "@/components/Shell";

export default function TeamPage({ params }: { params: { teamId: string } }) {
  return (
    <Shell>
      <ReadOnlyTeamsView initialTeamId={params.teamId} />
    </Shell>
  );
}
