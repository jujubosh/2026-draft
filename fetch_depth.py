"""Scrape ESPN team depth charts (offense, QB/RB/WR/TE) -> depth.json."""
import datetime
import io
import json
import re
import time

import pandas as pd
import requests

H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# ESPN slug -> Sleeper team code
TEAMS = {
    "buf": "BUF", "mia": "MIA", "ne": "NE", "nyj": "NYJ",
    "bal": "BAL", "cin": "CIN", "cle": "CLE", "pit": "PIT",
    "hou": "HOU", "ind": "IND", "jax": "JAX", "ten": "TEN",
    "den": "DEN", "kc": "KC", "lv": "LV", "lac": "LAC",
    "dal": "DAL", "nyg": "NYG", "phi": "PHI", "wsh": "WAS",
    "chi": "CHI", "det": "DET", "gb": "GB", "min": "MIN",
    "atl": "ATL", "car": "CAR", "no": "NO", "tb": "TB",
    "ari": "ARI", "lar": "LAR", "sf": "SF", "sea": "SEA",
}

# Injury/status markers ESPN appends to names on the depth page
MARKERS = {"Q", "O", "D", "IR", "PUP", "SUS", "NFI", "P"}
SKILL = {"QB", "RB", "WR", "TE"}


def clean_name(raw):
    """'Jahmyr Gibbs Q' -> ('Jahmyr Gibbs', 'Q'); '-' -> (None, None)."""
    raw = str(raw).strip()
    if raw in ("-", "nan", ""):
        return None, None
    parts = raw.split()
    status = None
    while parts and parts[-1] in MARKERS:
        status = parts.pop()
    return " ".join(parts), status


def norm(name):
    n = re.sub(r"[.'’]", "", name.lower())
    n = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", n)
    return n


def fetch_team(slug):
    url = f"https://www.espn.com/nfl/team/depth/_/name/{slug}"
    r = requests.get(url, headers=H, timeout=30)
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    # Offense: tables[0] = position labels (first label eaten as header),
    # tables[1] = player grid (Starter/2nd/3rd/4th)
    labels = [tables[0].columns[0]] + tables[0].iloc[:, 0].tolist()
    grid = tables[1]
    rows = []
    for li, label in enumerate(labels):
        if label not in SKILL or li >= len(grid):
            continue
        for rank, col in enumerate(grid.columns, start=1):
            name, status = clean_name(grid.iloc[li][col])
            if name:
                rows.append(
                    {"name": name, "pos": label, "rank": rank, "status": status}
                )
    return rows


def main():
    out = {}
    for slug, team in TEAMS.items():
        try:
            rows = fetch_team(slug)
        except Exception as e:
            print(f"  {team}: FAILED ({e})")
            continue
        for r in rows:
            r["team"] = team
            out.setdefault(norm(r["name"]), r)
        print(f"  {team}: {len(rows)} players")
        time.sleep(0.4)

    depth = {
        "as_of": datetime.date.today().isoformat(),
        "players": list(out.values()),
    }
    with open("depth.json", "w") as f:
        json.dump(depth, f, indent=1)
    print(f"\nSaved depth.json: {len(out)} players across {len(TEAMS)} teams")


if __name__ == "__main__":
    main()
