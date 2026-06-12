# Transfer Portal Frontend

Next.js prototype for a college basketball front office portal tool.

## Run

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## What Is Implemented

- Player leaderboard with search, filters, sorting, portal toggle, and expandable player profiles.
- In-portal view using the same table controls.
- Team pages with roster context and recommended portal fits.
- Transfer portal simulator with player removals, portal additions, scholarship tracking, roster count, and projected BPR.
- Recommendations view ranking portal players for the selected team.

## Data Replacement

Mock data lives in `data/players.ts` and `data/teams.ts`. Data access is isolated in `lib/data.ts`; replace those functions with API or database calls when the real backend is ready.
