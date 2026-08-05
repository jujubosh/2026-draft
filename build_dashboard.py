"""Inject report.json into dashboard_template.html -> dashboard.html."""
import datetime
import json
import re


def norm(name):
    n = re.sub(r"[.'’]", "", name.lower())
    n = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", n)
    return n


def main():
    with open("report.json") as f:
        report = json.load(f)

    # Live intel layer (optional files — dashboard renders without them)
    intel = {"injuries": [], "trending": [], "notes": [], "as_of": None}
    try:
        with open("intel.json") as f:
            raw = json.load(f)
        intel["injuries"] = raw.get("injuries", [])
        intel["trending"] = [
            t for t in raw.get("trending", [])
            if t.get("trend_add", 0) >= 1000 and t.get("adp_ppr", 999) < 200
        ][:12]
    except FileNotFoundError:
        pass
    try:
        with open("curated_notes.json") as f:
            cur = json.load(f)
        intel["notes"] = cur.get("notes", [])
        intel["as_of"] = cur.get("as_of")
    except FileNotFoundError:
        pass
    # Depth charts (ESPN) — annotate cheat sheet + build mismatch watchlists
    depth_by_name = {}
    try:
        with open("depth.json") as f:
            dd = json.load(f)
        intel["depth_as_of"] = dd.get("as_of")
        for p in dd.get("players", []):
            depth_by_name[(norm(p["name"]), p["pos"])] = p
    except FileNotFoundError:
        pass

    not_starters, cheap_starters = [], []
    for r in report["cheat_sheet"]:
        d = depth_by_name.get((norm(r["player"]), r["pos"]))
        r["depth_rank"] = d["rank"] if d else None
        r["depth_status"] = d.get("status") if d else None
        if not d or r["pos"] == "QB":
            continue
        adp = r.get("adp_ppr", 999)
        if d["rank"] >= 2 and adp < 110:
            not_starters.append(
                {"player": r["player"], "pos": r["pos"], "team": r["team"],
                 "adp_ppr": adp, "rank": d["rank"]}
            )
        elif d["rank"] == 1 and adp > 100:
            cheap_starters.append(
                {"player": r["player"], "pos": r["pos"], "team": r["team"],
                 "adp_ppr": adp, "pts_ppr": r["pts_ppr"]}
            )
    intel["depth_flags"] = {
        "not_starters": sorted(not_starters, key=lambda x: x["adp_ppr"])[:10],
        "cheap_starters": sorted(cheap_starters, key=lambda x: -x["pts_ppr"])[:10],
    }

    # FantasyPros expert consensus (second opinion vs Sleeper)
    fp_by_name = {}
    try:
        with open("fp_rankings.json") as f:
            fp = json.load(f)
        intel["fp_as_of"] = fp.get("as_of")
        intel["fp_experts"] = fp.get("experts")
        for p in fp.get("players", []):
            fp_by_name[(norm(p["player"]), p["pos"])] = p
    except FileNotFoundError:
        pass

    disagreements = []
    for r in report["cheat_sheet"]:
        f = fp_by_name.get((norm(r["player"]), r["pos"]))
        r["ecr"] = f["ecr"] if f else None
        r["tier"] = f.get("tier") if f else None
        r["bye"] = f.get("bye") if f else None
        if f and r["pos"] in ("QB", "RB", "WR", "TE") and r.get("adp_ppr", 999) < 150:
            gap = round(r["adp_ppr"]) - f["ecr"]  # + = experts like him more than the market
            if abs(gap) >= 12:
                disagreements.append(
                    {"player": r["player"], "pos": r["pos"], "team": r["team"],
                     "adp_ppr": r["adp_ppr"], "ecr": f["ecr"], "gap": gap}
                )
    disagreements.sort(key=lambda x: -abs(x["gap"]))
    intel["fp_disagreements"] = disagreements[:10]

    # Pool (needed for player_id / rookie flags and the tracker below)
    from draft_sim import load_pool

    pool = load_pool()
    pool_info = {}
    for _, r in pool.iterrows():
        ye = r.get("years_exp")
        pool_info[(norm(r["player"]), r["pos"])] = {
            "pid": str(r["player_id"]),
            "rookie": bool(ye == 0),  # NaN != 0 -> False
        }

    # ADP movement between the two most recent snapshots (news shows up as ADP moves)
    try:
        with open("adp_snapshots.json") as f:
            snaps = json.load(f)
    except FileNotFoundError:
        snaps = []
    if len(snaps) >= 2:
        cur, prev = snaps[-1], snaps[-2]
        moves = []
        for _, r in pool.iterrows():
            pid = str(r["player_id"])
            a, b = prev["adp"].get(pid), cur["adp"].get(pid)
            if a and b and min(a, b) < 130 and abs(a - b) >= 6:
                moves.append(
                    {"player": r["player"], "pos": r["pos"], "team": r["team"],
                     "from": round(a, 1), "to": round(b, 1), "delta": round(a - b, 1)}
                )
        moves.sort(key=lambda x: -abs(x["delta"]))
        intel["adp_movers"] = {"since": prev["date"], "moves": moves[:10]}

    # 2025 actual production (Sleeper, keyed by player_id)
    hist = {}
    try:
        with open("history.json") as f:
            hist = json.load(f).get("players", {})
    except FileNotFoundError:
        pass

    # Steals / stay-aways: a player lists only when >=2 independent signals agree
    trending_names = {t["player"] for t in intel["trending"]}
    steals, avoids, rookies = [], [], []
    for r in report["cheat_sheet"]:
        info = pool_info.get((norm(r["player"]), r["pos"]))
        r["rookie"] = info["rookie"] if info else False
        if r["pos"] not in ("QB", "RB", "WR", "TE") or r.get("adp_ppr", 999) >= 170:
            continue
        adp = r["adp_ppr"]
        ecr = r.get("ecr")
        h = hist.get(info["pid"]) if info else None
        gp = (h or {}).get("gp") or 0
        ppg25 = h["pts_ppr"] / gp if h and gp >= 1 else None
        ppg26 = r["pts_ppr"] / 17.0

        plus, minus = [], []
        if r.get("value_gap", 0) >= 8:
            plus.append(f"projected {r['value_gap']} spots better than his draft price")
        if ecr and round(adp) - ecr >= 12:
            plus.append(f"experts rank him {round(adp) - ecr} spots above his ADP")
        if r.get("depth_rank") == 1 and adp > 100:
            plus.append("listed starter going after pick 100")
        if r["player"] in trending_names:
            plus.append("hot add on Sleeper this week")

        if r.get("value_gap", 0) <= -8:
            minus.append(f"drafted {-r['value_gap']} spots ahead of his projection")
        if ecr and round(adp) - ecr <= -12:
            minus.append(f"experts rank him {ecr - round(adp)} spots below his ADP")
        dr = r.get("depth_rank") or 1
        if dr >= 2 and adp < 110:
            minus.append(f"ESPN lists him {({2: '2nd', 3: '3rd'}.get(dr, str(dr) + 'th'))} string")
        if r.get("injury_status") in ("PUP", "IR", "Out", "Doubtful"):
            minus.append(f"currently {r['injury_status']}")

        if r["rookie"]:
            # Rookies get their own list — 2025 production signals don't apply
            f = fp_by_name.get((norm(r["player"]), r["pos"]))
            best_case = int(f["rank_min"]) if f and f.get("rank_min") else None
            up = []
            if best_case is not None and round(adp) - best_case >= 15:
                up.append(f"most bullish expert has him #{best_case} overall (ADP {adp:.0f})")
            if r.get("value_gap", 0) >= 5:
                up.append(f"projection already says {r['value_gap']} spots too cheap")
            if r["player"] in trending_names:
                up.append("hot add on Sleeper this week")
            rookies.append(
                {"player": r["player"], "pos": r["pos"], "team": r["team"],
                 "adp": adp, "reasons": up,
                 "upside": (round(adp) - best_case if best_case is not None else 0)
                           + max(0, r.get("value_gap", 0))}
            )
            continue

        if ppg25 is not None:
            if gp >= 12 and ppg25 >= 0.9 * ppg26:
                plus.append(f"proved it in 2025: {ppg25:.1f} PPR/gm over {gp:.0f} games")
            if gp >= 6 and ppg26 > 1.3 * ppg25 and adp < 120:
                minus.append(f"priced for a {(ppg26 / ppg25 - 1) * 100:.0f}% jump on his 2025 pace")
            if gp <= 9 and adp < 100:
                minus.append(f"played only {gp:.0f} games in 2025")
        elif h is None and adp < 100:
            minus.append("no 2025 stats on record")

        if len(plus) >= 2:
            steals.append({"player": r["player"], "pos": r["pos"], "team": r["team"],
                           "adp": adp, "reasons": plus})
        if len(minus) >= 2:
            avoids.append({"player": r["player"], "pos": r["pos"], "team": r["team"],
                           "adp": adp, "reasons": minus})

    rookies.sort(key=lambda x: -x["upside"])
    intel["steals"] = sorted(steals, key=lambda x: x["adp"])[:10]
    intel["avoids"] = sorted(avoids, key=lambda x: x["adp"])[:10]
    intel["rookies"] = [x for x in rookies if x["reasons"]][:8]

    report["intel"] = intel

    # Tracker pool: every draftable player incl. K/DST, with VORP + depth
    tracker = []
    for _, r in pool.iterrows():
        d = depth_by_name.get((norm(r["player"]), r["pos"]))
        f = fp_by_name.get((norm(r["player"]), r["pos"]))
        tracker.append(
            {
                "player": r["player"],
                "pos": r["pos"],
                "team": r["team"],
                "adp": round(float(r["adp_ppr"]), 1),
                "pts": round(float(r["pts_ppr"]), 1),
                "vorp": round(float(r["vorp"]), 1),
                "rec": None if r["rec"] != r["rec"] else float(r["rec"]),
                "depth_rank": d["rank"] if d else None,
                "injury": None if r["injury_status"] != r["injury_status"] else r["injury_status"],
                "ecr": f["ecr"] if f else None,
                "bye": f.get("bye") if f else None,
                "rookie": pool_info.get((norm(r["player"]), r["pos"]), {}).get("rookie", False),
            }
        )
    report["tracker_pool"] = tracker

    # Trim cheat sheet to the fields the page uses
    keep = [
        "player", "pos", "team", "adp_ppr", "pts_ppr", "rec",
        "vorp", "vorp_rank", "adp_rank", "value_gap", "injury_status",
        "depth_rank", "depth_status", "ecr", "tier", "bye", "rookie",
    ]
    report["cheat_sheet"] = [
        {k: (None if str(r.get(k)) == "nan" else r.get(k)) for k in keep}
        for r in report["cheat_sheet"]
    ]

    with open("dashboard_template.html") as f:
        html = f.read()
    def denan(obj):
        if isinstance(obj, dict):
            return {k: denan(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [denan(v) for v in obj]
        if isinstance(obj, float) and obj != obj:
            return None
        return obj

    html = html.replace("__DATA__", json.dumps(denan(report), separators=(",", ":")))
    html = html.replace("__DATA_DATE__", datetime.date.today().strftime("%B %-d, %Y"))
    with open("dashboard.html", "w") as f:
        f.write(html)
    # index.html is what GitHub Pages serves — same page with a doc shell
    with open("index.html", "w") as f:
        f.write("<!doctype html>\n<meta charset=\"utf-8\">\n"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
                + html)
    print(f"dashboard.html + index.html written ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
