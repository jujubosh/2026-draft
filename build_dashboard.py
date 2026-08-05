"""Inject report.json into dashboard_template.html -> dashboard.html."""
import base64
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
    news_raw = []
    try:
        with open("intel.json") as f:
            raw = json.load(f)
        intel["injuries"] = raw.get("injuries", [])
        news_raw = raw.get("news", [])
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

    # 2025 actual production + team defenses (Sleeper, keyed by player_id / team)
    hist, defenses = {}, {}
    try:
        with open("history.json") as f:
            hraw = json.load(f)
        hist = hraw.get("players", {})
        defenses = hraw.get("defenses", {})
    except FileNotFoundError:
        pass

    # Defense quality rank: blend points-allowed (game script: fewer opponent
    # points = more drives for your offense) with fantasy production
    def_rank = {}
    if defenses:
        teams = list(defenses)
        by_allow = sorted(teams, key=lambda t: defenses[t].get("pts_allow") or 999)
        by_pts = sorted(teams, key=lambda t: -(defenses[t].get("pts_std") or 0))
        blend = {t: by_allow.index(t) + by_pts.index(t) for t in teams}
        for i, t in enumerate(sorted(teams, key=lambda t: blend[t]), 1):
            def_rank[t] = i

    # Curated O-line tiers (team_context.json — hand-edited, 1 elite .. 5 bad)
    oline = {}
    try:
        with open("team_context.json") as f:
            oline = {t: v["tier"] for t, v in json.load(f).get("oline", {}).items()}
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

        # Environment (football context): supporting evidence only — a steal
        # still needs at least one price-based signal (see env_plus below)
        env_plus = []
        team = r.get("team")
        ol = oline.get(team)
        dteam = def_rank.get(team)
        if r["pos"] == "RB":
            if ol and ol <= 2:
                env_plus.append(f"runs behind a {'top-tier' if ol == 1 else 'good'} O-line")
            if dteam and dteam <= 8:
                env_plus.append(f"2025 top-{dteam} defense keeps his offense on the field")
            if ol and ol >= 4 and adp < 120:
                minus.append("below-average O-line in front of him")

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
            if len(up) >= 2:
                r["_steal"] = ["rookie upside: " + " · ".join(up)]
            if len(minus) >= 2:
                r["_avoid"] = minus
            continue

        if ppg25 is not None:
            # Support evidence, not a price signal — production alone isn't a steal
            if gp >= 12 and ppg25 >= 0.9 * ppg26:
                env_plus.append(f"proved it in 2025: {ppg25:.1f} PPR/gm over {gp:.0f} games")
            if gp >= 6 and ppg26 > 1.3 * ppg25 and adp < 120:
                minus.append(f"priced for a {(ppg26 / ppg25 - 1) * 100:.0f}% jump on his 2025 pace")
            if gp <= 9 and adp < 100:
                minus.append(f"played only {gp:.0f} games in 2025")
        elif h is None and adp < 100:
            minus.append("no 2025 stats on record")

        if plus and len(plus) + len(env_plus) >= 2:
            r["_steal"] = plus + env_plus
            steals.append({"player": r["player"], "pos": r["pos"], "team": r["team"],
                           "adp": adp, "reasons": plus + env_plus})
        if len(minus) >= 2:
            r["_avoid"] = minus
            avoids.append({"player": r["player"], "pos": r["pos"], "team": r["team"],
                           "adp": adp, "reasons": minus})

    rookies.sort(key=lambda x: -x["upside"])
    intel["steals"] = sorted(steals, key=lambda x: x["adp"])[:10]
    intel["avoids"] = sorted(avoids, key=lambda x: x["adp"])[:10]
    intel["rookies"] = [x for x in rookies if x["reasons"]][:8]

    # QB + pass-catcher stacks priced as values (correlated weekly upside)
    by_team_qb, by_team_pc = {}, {}
    for r in report["cheat_sheet"]:
        if r.get("adp_ppr", 999) >= 170 or not r.get("team"):
            continue
        if r["pos"] == "QB":
            by_team_qb.setdefault(r["team"], []).append(r)
        elif r["pos"] in ("WR", "TE"):
            by_team_pc.setdefault(r["team"], []).append(r)
    stacks = []
    for team, qbs in by_team_qb.items():
        qb = max(qbs, key=lambda x: x["pts_ppr"])
        for pc in sorted(by_team_pc.get(team, []), key=lambda x: -x["pts_ppr"])[:2]:
            stacks.append(
                {"team": team,
                 "qb": qb["player"], "qb_adp": qb["adp_ppr"],
                 "pc": pc["player"], "pc_pos": pc["pos"], "pc_adp": pc["adp_ppr"],
                 "pts": round(qb["pts_ppr"] + pc["pts_ppr"]),
                 "value": (qb.get("value_gap") or 0) + (pc.get("value_gap") or 0)}
            )
    stacks.sort(key=lambda x: (-x["value"], x["qb_adp"]))
    intel["stacks"] = [s for s in stacks if s["value"] >= 8][:8]

    # RB situations: curated O-line tier + 2025 defense rank
    good_env, bad_env = [], []
    for r in report["cheat_sheet"]:
        if r["pos"] != "RB" or r.get("adp_ppr", 999) >= 140:
            continue
        ol = oline.get(r.get("team"))
        if not ol:
            continue
        entry = {"player": r["player"], "pos": "RB", "team": r["team"],
                 "adp": r["adp_ppr"], "oline": ol,
                 "def_rank": def_rank.get(r.get("team"))}
        (good_env if ol <= 2 else bad_env if ol >= 4 else []).append(entry)
    intel["rb_env"] = {
        "good": sorted(good_env, key=lambda x: x["adp"])[:8],
        "bad": sorted(bad_env, key=lambda x: x["adp"])[:6],
    }

    report["intel"] = intel

    # Slot deep dive (deep_dive.py) — page renders a fallback note without it
    try:
        with open("deep_dive.json") as f:
            report["deep"] = json.load(f)
    except FileNotFoundError:
        report["deep"] = None

    # Player news: ESPN headlines matched to pool players (newest first)
    news_by_player = {}
    for art in news_raw:
        date = (art.get("published") or "")[5:10].replace("-", "/")
        for pname in art.get("players", []):
            hits = news_by_player.setdefault(pname, [])
            if len(hits) < 2:
                hits.append(f"{date}: {art['headline']}")
    intel["player_news"] = news_raw[:10]

    # Tracker pool: every draftable player incl. K/DST, with the full rollup
    # (flags, environment, ECR, bye, news) so draft day never needs the other tab
    flag_by_key = {}
    for r in report["cheat_sheet"]:
        flag_by_key[(norm(r["player"]), r["pos"])] = {
            "steal": " · ".join(r.get("_steal") or []) or None,
            "avoid": " · ".join(r.get("_avoid") or []) or None,
        }
    tracker = []
    for _, r in pool.iterrows():
        d = depth_by_name.get((norm(r["player"]), r["pos"]))
        f = fp_by_name.get((norm(r["player"]), r["pos"]))
        fl = flag_by_key.get((norm(r["player"]), r["pos"]), {})
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
                "oline": oline.get(r["team"]),
                "def_rank": def_rank.get(r["team"]),
                "steal": fl.get("steal"),
                "avoid": fl.get("avoid"),
                "news": " • ".join(news_by_player.get(r["player"], [])) or None,
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
    # Maker mark, inlined so it works everywhere (artifact CSP blocks external images)
    try:
        with open("logo.jpg", "rb") as f:
            logo = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        logo = ""
    html = html.replace("__LOGO__", logo)
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
