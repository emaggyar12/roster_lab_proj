export type Team = {
  team_id: string;
  team_name: string;
  conference: string;
  roster_limit: number;
  scholarships_used: number;
  style: string;
  needs: string[];
};

export const teams: Team[] = [
  {
    team_id: "uconn",
    team_name: "UConn",
    conference: "Big East",
    roster_limit: 15,
    scholarships_used: 11,
    style: "Paint pressure, rim protection, NBA-size wings",
    needs: ["Backup lead guard", "Stretch frontcourt option", "Bench shooting"],
  },
  {
    team_id: "duke",
    team_name: "Duke",
    conference: "ACC",
    roster_limit: 15,
    scholarships_used: 12,
    style: "Five-out spacing with freshman creator usage",
    needs: ["Veteran combo guard", "Physical defensive wing"],
  },
  {
    team_id: "indiana",
    team_name: "Indiana",
    conference: "Big Ten",
    roster_limit: 15,
    scholarships_used: 10,
    style: "Rim-first half court with transition wings",
    needs: ["Point-of-attack guard", "Shooting four", "Backup center"],
  },
  {
    team_id: "ucla",
    team_name: "UCLA",
    conference: "Big Ten",
    roster_limit: 15,
    scholarships_used: 11,
    style: "Switchable defense and late-clock isolation",
    needs: ["Frontcourt size", "Movement shooter", "Secondary ball handler"],
  },
  {
    team_id: "providence",
    team_name: "Providence",
    conference: "Big East",
    roster_limit: 15,
    scholarships_used: 9,
    style: "Physical rebounding with two-guard creation",
    needs: ["Starting wing", "Rim protector", "Reserve point guard"],
  },
];
