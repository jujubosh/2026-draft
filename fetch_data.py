"""Fetch 2026 season projections + PPR ADP from Sleeper's public API -> players.csv."""
import requests
import pandas as pd

URL = "https://api.sleeper.com/projections/nfl/2026"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def fetch(position):
    r = requests.get(
        URL,
        params={
            "season_type": "regular",
            "position[]": position,
            "order_by": "adp_ppr",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def main():
    rows = []
    for pos in POSITIONS:
        data = fetch(pos)
        print(f"{pos}: {len(data)} players")
        for entry in data:
            stats = entry.get("stats") or {}
            player = entry.get("player") or {}
            pts = stats.get("pts_ppr")
            if pts is None or pts <= 0:
                continue
            name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            rows.append(
                {
                    "player_id": entry.get("player_id"),
                    "player": name,
                    "pos": pos if pos != "DEF" else "DST",
                    "team": entry.get("team") or "FA",
                    "adp_ppr": stats.get("adp_ppr") or 999.0,
                    "pts_ppr": pts,
                    "games": stats.get("gp"),
                    "rec": stats.get("rec"),
                    "rec_yd": stats.get("rec_yd"),
                    "rec_td": stats.get("rec_td"),
                    "rush_att": stats.get("rush_att"),
                    "rush_yd": stats.get("rush_yd"),
                    "rush_td": stats.get("rush_td"),
                    "pass_yd": stats.get("pass_yd"),
                    "pass_td": stats.get("pass_td"),
                    "injury_status": player.get("injury_status"),
                    "years_exp": player.get("years_exp"),
                }
            )
    df = pd.DataFrame(rows)
    df = df.sort_values("adp_ppr").reset_index(drop=True)
    df.to_csv("players.csv", index=False)
    print(f"\nSaved {len(df)} players to players.csv")

    # Daily ADP snapshot so the dashboard can show risers/fallers between refreshes
    import datetime
    import json
    try:
        with open("adp_snapshots.json") as f:
            snaps = json.load(f)
    except FileNotFoundError:
        snaps = []
    today = datetime.date.today().isoformat()
    snaps = [s for s in snaps if s["date"] != today]
    snaps.append(
        {"date": today,
         "adp": {str(r["player_id"]): r["adp_ppr"] for r in rows if r["adp_ppr"] < 300}}
    )
    snaps = snaps[-30:]
    with open("adp_snapshots.json", "w") as f:
        json.dump(snaps, f)
    print(f"ADP snapshot saved ({len(snaps)} day{'s' if len(snaps) != 1 else ''} on file)")
    print(df.head(15)[["player", "pos", "team", "adp_ppr", "pts_ppr", "rec"]].to_string())


if __name__ == "__main__":
    main()
