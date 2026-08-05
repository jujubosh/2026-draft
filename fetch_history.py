"""Fetch 2025 actual season stats from Sleeper -> history.json.

Keyed by Sleeper player_id (same ids as the projections in players.csv), so
matching is exact. Used to judge whether a 2026 projection is backed by real
production or priced on a hoped-for leap.
"""
import json

import requests

URL = "https://api.sleeper.com/stats/nfl/2025"
POSITIONS = ["QB", "RB", "WR", "TE"]


def main():
    players = {}
    for pos in POSITIONS:
        r = requests.get(
            URL,
            params={"season_type": "regular", "position[]": pos, "order_by": "pts_ppr"},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        print(f"{pos}: {len(data)} players")
        for e in data:
            st = e.get("stats") or {}
            pl = e.get("player") or {}
            pts = st.get("pts_ppr")
            if pts is None:
                continue
            players[e["player_id"]] = {
                "player": f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip(),
                "pos": pos,
                "team": e.get("team"),
                "pts_ppr": round(pts, 1),
                "gp": st.get("gp"),
                "gms_active": st.get("gms_active"),
            }

    # Team defenses 2025: fantasy pts (playmaking) + points allowed (game script)
    r = requests.get(
        URL,
        params={"season_type": "regular", "position[]": "DEF", "order_by": "pts_std"},
        timeout=60,
    )
    r.raise_for_status()
    defenses = {}
    for e in r.json():
        st = e.get("stats") or {}
        defenses[e["player_id"]] = {
            "pts_std": st.get("pts_std"),
            "pts_allow": st.get("pts_allow"),
            "forced_punts": st.get("def_forced_punts"),
        }
    print(f"DEF: {len(defenses)} teams")

    with open("history.json", "w") as f:
        json.dump({"season": 2025, "players": players, "defenses": defenses}, f, indent=1)
    print(f"\nSaved {len(players)} players + {len(defenses)} defenses to history.json")


if __name__ == "__main__":
    main()
