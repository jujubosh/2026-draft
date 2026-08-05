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

    report["intel"] = intel

    # Tracker pool: every draftable player incl. K/DST, with VORP + depth
    from draft_sim import load_pool

    pool = load_pool()
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
            }
        )
    report["tracker_pool"] = tracker

    # Trim cheat sheet to the fields the page uses
    keep = [
        "player", "pos", "team", "adp_ppr", "pts_ppr", "rec",
        "vorp", "vorp_rank", "adp_rank", "value_gap", "injury_status",
        "depth_rank", "depth_status", "ecr", "tier", "bye",
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
