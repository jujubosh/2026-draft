# 2026 Draft War Room

Monte Carlo draft simulator + live draft-day tracker for a 12-team full-PPR
snake league (1QB / 2RB / 2WR / 1TE / 1FLEX / K / DST, 15 rounds).

**Live dashboard:** https://jujubosh.github.io/2026-draft/

## What it does

- Simulates the draft 300× per slot per strategy against ADP-realistic
  opponents, ranks 9 named strategies (Hero RB, Zero RB, Anchor+TE, …) by
  projected starter points, and re-samples every player's season outcome
  (position-sized bust/breakout error) for floor / ceiling / top-3 rate.
- **War Room tab** — strategy rankings with risk bands, strategy-by-slot
  heatmap, round-by-round plan per slot, live intel (injuries, Sleeper
  trends, ESPN depth-chart flags, FantasyPros expert-vs-market gaps), and a
  VORP cheat sheet with ECR + bye weeks.
- **Live Tracker tab** — check off picks on draft day; a rest-of-draft Monte
  Carlo replays the remaining rounds 100× per candidate from the actual
  board and says which pick wins from here. State persists in the browser.

## Refresh (do this the morning of the draft)

```sh
.venv/bin/python refresh.py              # everything: data → sim → dashboard
.venv/bin/python refresh.py --no-sim     # just re-pull data + rebuild page
git add -A && git commit -m "Refresh data" && git push   # deploys the page
```

## Data sources

| Source | Script | Output |
|---|---|---|
| Sleeper projections + PPR ADP | `fetch_data.py` | `players.csv` |
| Sleeper trending + injuries | `fetch_intel.py` | `intel.json` |
| ESPN depth charts (32 teams) | `fetch_depth.py` | `depth.json` |
| FantasyPros expert consensus | `fetch_fp.py` | `fp_rankings.json` |
| Hand-curated camp notes | (edit by hand) | `curated_notes.json` |

`draft_sim.py` → `sim_results.json` + `cheat_sheet.csv`, `analyze.py` →
`report.json`, `build_dashboard.py` → `dashboard.html` + `index.html`
(the GitHub Pages page).

Setup: `python3 -m venv .venv && .venv/bin/pip install requests pandas numpy`
