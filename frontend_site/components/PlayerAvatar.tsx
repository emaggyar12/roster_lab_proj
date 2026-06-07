import type { Player } from "@/data/players";

export function PlayerAvatar({ player, size = "md" }: { player: Player; size?: "sm" | "md" | "lg" }) {
  const sizeClass = size === "sm" ? "h-9 w-9 text-xs" : size === "lg" ? "h-14 w-14 text-base" : "h-11 w-11 text-sm";
  const initials = player.player_name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  return (
    <div className={`${sizeClass} shrink-0 overflow-hidden rounded-full border border-line bg-panel`}>
      {player.profile_image_url ? (
        <img
          src={player.profile_image_url}
          alt={player.player_name}
          className="h-full w-full object-cover"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center font-semibold text-muted">{initials}</div>
      )}
    </div>
  );
}
