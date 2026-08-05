"""Live intel layer: Sleeper trending adds/drops + injuries, ESPN news matched
to the draft pool. Writes intel.json."""
import json
import re

import pandas as pd
import requests

H = {"User-Agent": "curl/8.7.1"}


def fetch_trending(kind, hours=48, limit=200):
    url = f"https://api.sleeper.app/v1/players/nfl/trending/{kind}"
    r = requests.get(url, params={"lookback_hours": hours, "limit": limit}, headers=H, timeout=30)
    r.raise_for_status()
    return {str(x["player_id"]): x["count"] for x in r.json()}


def fetch_espn_news(limit=50):
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
    r = requests.get(url, params={"limit": limit}, headers=H, timeout=30)
    r.raise_for_status()
    out = []
    for a in r.json().get("articles", []):
        out.append(
            {
                "headline": a.get("headline", ""),
                "description": a.get("description", ""),
                "published": a.get("published", ""),
                "link": (a.get("links", {}).get("web", {}) or {}).get("href", ""),
            }
        )
    return out


def main():
    pool = pd.read_csv("players.csv")
    pool["player_id"] = pool["player_id"].astype(str)
    top = pool[pool["adp_ppr"] < 200].copy()

    adds = fetch_trending("add")
    drops = fetch_trending("drop")
    print(f"trending: {len(adds)} adds, {len(drops)} drops")

    top["trend_add"] = top["player_id"].map(adds).fillna(0).astype(int)
    top["trend_drop"] = top["player_id"].map(drops).fillna(0).astype(int)

    news = fetch_espn_news()
    print(f"news articles: {len(news)}")

    # Match articles to pool players by full-name mention
    names = top["player"].tolist()
    matched = []
    for art in news:
        text = f"{art['headline']} {art['description']}"
        hits = [n for n in names if re.search(re.escape(n), text, re.I)]
        if hits:
            matched.append({**art, "players": hits})

    intel = {
        "trending": top[
            (top["trend_add"] > 0) | (top["trend_drop"] > 0)
        ][
            ["player", "pos", "team", "adp_ppr", "trend_add", "trend_drop", "injury_status"]
        ]
        .sort_values("trend_add", ascending=False)
        .to_dict(orient="records"),
        "injuries": top[top["injury_status"].notna()][
            ["player", "pos", "team", "adp_ppr", "injury_status"]
        ]
        .sort_values("adp_ppr")
        .to_dict(orient="records"),
        "news": matched,
        "all_news": news[:25],
    }
    with open("intel.json", "w") as f:
        json.dump(intel, f, indent=1)

    print(f"\nInjured (top 200 ADP): {len(intel['injuries'])}")
    for i in intel["injuries"][:15]:
        print(f"  {i['player']:24s} {i['pos']:3s} ADP {i['adp_ppr']:6.1f}  {i['injury_status']}")
    print(f"\nTop trending adds:")
    for t in intel["trending"][:10]:
        print(f"  {t['player']:24s} {t['pos']:3s} +{t['trend_add']:,}  -{t['trend_drop']:,}")
    print(f"\nPlayer-matched news: {len(matched)}")
    for m in matched[:10]:
        print(f"  [{', '.join(m['players'])}] {m['headline']}")


if __name__ == "__main__":
    main()
