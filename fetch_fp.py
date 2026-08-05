"""Fetch FantasyPros PPR expert-consensus ranks (ECR) -> fp_rankings.json.

Second opinion vs Sleeper: the draft page embeds `var ecrData = {...}` with
every player's consensus rank, tier, bye week, and expert spread.
"""
import json
import re

import requests

URL = "https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def main():
    r = requests.get(URL, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    m = re.search(r"var ecrData = (\{.*?\});\n", r.text)
    if not m:
        raise RuntimeError("ecrData blob not found — FantasyPros page layout changed")
    data = json.loads(m.group(1))

    players = []
    for p in data.get("players", []):
        pos = p.get("player_position_id")
        if pos not in ("QB", "RB", "WR", "TE", "K", "DST"):
            continue
        players.append(
            {
                "player": p["player_name"],
                "team": p.get("player_team_id"),
                "pos": pos,
                "ecr": p["rank_ecr"],
                "pos_rank": p.get("pos_rank"),
                "tier": p.get("tier"),
                "bye": p.get("player_bye_week"),
                "rank_min": p.get("rank_min"),
                "rank_max": p.get("rank_max"),
                "rank_std": p.get("rank_std"),
            }
        )

    out = {
        "as_of": data.get("last_updated"),
        "experts": data.get("total_experts"),
        "scoring": data.get("scoring"),
        "players": players,
    }
    with open("fp_rankings.json", "w") as f:
        json.dump(out, f, indent=1)
    print(
        f"Saved {len(players)} players to fp_rankings.json "
        f"({out['experts']} experts, updated {out['as_of']})"
    )


if __name__ == "__main__":
    main()
