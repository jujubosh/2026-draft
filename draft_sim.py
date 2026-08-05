"""Monte Carlo 2026 fantasy draft simulator.

12-team full-PPR snake draft, 15 rounds.
Lineup: 1 QB / 2 RB / 2 WR / 1 TE / 1 FLEX (RB-WR-TE) / 1 K / 1 DST, 6 bench.

Opponents draft off ADP with noise and roster-need logic. Our team runs one of
several named strategies. Team score = projected points of the optimal starting
lineup plus a small bench-depth credit.
"""
import json
import random
from collections import defaultdict

import numpy as np
import pandas as pd

TEAMS = 12
ROUNDS = 15
LINEUP = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1}
FLEX = 1  # RB/WR/TE
POOL_SIZE = 240  # players actually consumed in a 12x15 draft, with margin

# Position caps for any team (opponents and us)
CAPS = {"QB": 3, "RB": 8, "WR": 8, "TE": 3, "K": 1, "DST": 1}

BENCH_WEIGHT = 0.12  # credit for top-3 skill bench players

# Season-outcome uncertainty: multiplicative lognormal noise on projected points,
# sized to historical projection error by position. Draft picks still use the
# projection (you draft on expectations); outcomes decide rank/floor/ceiling.
OUTCOME_CV = {"QB": 0.22, "RB": 0.34, "WR": 0.30, "TE": 0.32, "K": 0.25, "DST": 0.30}

# Our strategies: scripts for the first rounds ('*' = best VORP available),
# after the script runs out -> VORP best-pick with need logic.
STRATEGIES = {
    "Pure VORP":   [],
    "Robust RB":   ["RB", "RB", "*", "*"],
    "Hero RB":     ["RB", "WR", "WR", "WR"],
    "Zero RB":     ["WR", "WR", "WR", "*"],
    "WR-WR":       ["WR", "WR", "*", "*"],
    "RB-WR-RB":    ["RB", "WR", "RB", "*"],
    "Early TE":    ["*", "TE", "*", "*"],
    "TE Round 3":  ["*", "*", "TE", "*"],
    "Anchor+TE":   ["RB", "WR", "TE", "WR"],
}


def load_pool(path="players.csv"):
    df = pd.read_csv(path)
    df = df[df["pts_ppr"] > 0].copy()
    # Keep a draftable pool: everyone inside ADP range + best of the rest by points
    df = df.sort_values("adp_ppr").reset_index(drop=True)
    in_adp = df[df["adp_ppr"] < 900]
    rest = df[df["adp_ppr"] >= 900].sort_values("pts_ppr", ascending=False)
    pool = pd.concat([in_adp, rest]).drop_duplicates(subset=["player", "pos"])
    pool = pool.head(max(POOL_SIZE, len(in_adp))).reset_index(drop=True)
    pool = compute_vorp(pool)
    return pool


def compute_vorp(df):
    # Replacement rank = starters used league-wide (+flex share) + shallow margin
    repl_rank = {"QB": 14, "RB": 34, "WR": 36, "TE": 14, "K": 12, "DST": 12}
    vorp = np.zeros(len(df))
    for pos, rank in repl_rank.items():
        sub = df[df["pos"] == pos].sort_values("pts_ppr", ascending=False)
        if len(sub) == 0:
            continue
        idx = min(rank - 1, len(sub) - 1)
        baseline = sub["pts_ppr"].iloc[idx]
        vorp[sub.index] = sub["pts_ppr"] - baseline
    df = df.copy()
    df["vorp"] = vorp
    return df


class Board:
    """Draft board state: numpy arrays for speed."""

    def __init__(self, pool):
        self.names = pool["player"].to_numpy()
        self.pos = pool["pos"].to_numpy()
        self.adp = pool["adp_ppr"].to_numpy(dtype=float)
        self.pts = pool["pts_ppr"].to_numpy(dtype=float)
        self.vorp = pool["vorp"].to_numpy(dtype=float)
        self.cv = np.array([OUTCOME_CV[p] for p in self.pos])
        self.available = np.ones(len(pool), dtype=bool)

    def avail_idx(self):
        return np.flatnonzero(self.available)


def opponent_pick(board, roster_counts, percept, pick_no, round_no, rng):
    """Pick best player on this opponent's own noisy board, with need logic."""
    avail = board.avail_idx()
    pos_counts = roster_counts

    need_k = pos_counts["K"] < 1
    need_dst = pos_counts["DST"] < 1
    rounds_left = ROUNDS - round_no + 1

    # Force K/DST at the end so lineups are legal
    forced = []
    if rounds_left <= (1 if not need_dst else 2) and need_k:
        forced.append("K")
    if rounds_left <= (1 if not need_k else 2) and need_dst:
        forced.append("DST")
    if forced:
        cand = avail[np.isin(board.pos[avail], forced)]
        if len(cand):
            cand = cand[np.argsort(board.adp[cand])]
            return cand[0]

    def legal(i):
        p = board.pos[i]
        if pos_counts[p] >= CAPS[p]:
            return False
        # Don't draft K/DST before round 13, or a 2nd QB/TE before round 8
        if p in ("K", "DST") and round_no < 13:
            return False
        if p == "QB" and pos_counts["QB"] >= 1 and round_no < 8:
            return False
        if p == "TE" and pos_counts["TE"] >= 1 and round_no < 8:
            return False
        return True

    cand = np.array([i for i in avail if legal(i)])
    if len(cand) == 0:
        cand = avail
    return cand[np.argmin(percept[cand])]


def our_pick(board, roster_counts, round_no, script, rng):
    """Our pick: follow strategy script early, then VORP with need logic."""
    avail = board.avail_idx()
    rounds_left = ROUNDS - round_no + 1

    need_k = roster_counts["K"] < 1
    need_dst = roster_counts["DST"] < 1
    forced = []
    if rounds_left <= (1 if not need_dst else 2) and need_k:
        forced.append("K")
    if rounds_left <= (1 if not need_k else 2) and need_dst:
        forced.append("DST")
    if forced:
        cand = avail[np.isin(board.pos[avail], forced)]
        if len(cand):
            return cand[np.argmax(board.pts[cand])]

    scripted = script[round_no - 1] if round_no <= len(script) else "*"

    def legal(i):
        p = board.pos[i]
        if roster_counts[p] >= CAPS[p]:
            return False
        if p in ("K", "DST") and round_no < 13:
            return False
        # QB discipline: 1 QB before round 10, take him rounds 5-10
        if p == "QB":
            if roster_counts["QB"] >= 1:
                return False
            if round_no < 5:
                return False
        if p == "TE" and roster_counts["TE"] >= 2:
            return False
        return True

    if scripted != "*":
        cand = np.array([i for i in avail if board.pos[i] == scripted and legal(i)])
        if len(cand):
            return cand[np.argmax(board.vorp[cand])]

    cand = np.array([i for i in avail if legal(i)])
    if len(cand) == 0:
        cand = avail
    # Positional urgency: if QB still unfilled by round 8, boost QB value
    bonus = np.zeros(len(cand))
    if roster_counts["QB"] == 0 and round_no >= 8:
        bonus[board.pos[cand] == "QB"] += 15.0
    if roster_counts["TE"] == 0 and round_no >= 9:
        bonus[board.pos[cand] == "TE"] += 12.0
    score = board.vorp[cand] + bonus
    return cand[np.argmax(score)]


def score_roster(board, picks, pts=None):
    """Optimal lineup points + bench credit. pts overrides projections
    (e.g. a sampled season outcome)."""
    if pts is None:
        pts = board.pts
    by_pos = defaultdict(list)
    for i in picks:
        by_pos[board.pos[i]].append(pts[i])
    for p in by_pos:
        by_pos[p].sort(reverse=True)

    starters = 0.0
    used = defaultdict(int)
    for pos, n in LINEUP.items():
        vals = by_pos.get(pos, [])
        take = vals[:n]
        starters += sum(take)
        used[pos] = len(take)

    flex_pool = []
    for pos in ("RB", "WR", "TE"):
        flex_pool.extend(by_pos.get(pos, [])[used[pos]:])
    flex_pool.sort(reverse=True)
    starters += sum(flex_pool[:FLEX])

    bench = sorted(flex_pool[FLEX:], reverse=True)[:3]
    return starters + BENCH_WEIGHT * sum(bench), starters


def run_draft(pool, our_slot, strategy_name, seed):
    rng = np.random.default_rng(seed)
    board = Board(pool)
    rosters = [[] for _ in range(TEAMS)]
    counts = [defaultdict(int) for _ in range(TEAMS)]
    script = STRATEGIES[strategy_name]

    # Each opponent drafts off their own noisy copy of ADP. Noise scales with
    # ADP (top picks barely move; late-round players swing by rounds).
    sigma = np.clip(0.8 + 0.09 * board.adp, 0.8, 25.0)
    percepts = board.adp[None, :] + rng.normal(0.0, 1.0, (TEAMS, len(board.adp))) * sigma[None, :]

    pick_no = 0
    for rnd in range(1, ROUNDS + 1):
        order = range(TEAMS) if rnd % 2 == 1 else range(TEAMS - 1, -1, -1)
        for team in order:
            pick_no += 1
            if team == our_slot:
                idx = our_pick(board, counts[team], rnd, script, rng)
            else:
                idx = opponent_pick(board, counts[team], percepts[team], pick_no, rnd, rng)
            board.available[idx] = False
            rosters[team].append(idx)
            counts[team][board.pos[idx]] += 1

    total, starters = score_roster(board, rosters[our_slot])

    # Sample one season outcome for the whole pool (shared across all 12 teams)
    factor = np.exp(rng.normal(-0.5 * board.cv**2, board.cv))
    pts_out = board.pts * factor
    out_total, out_starters = score_roster(board, rosters[our_slot], pts=pts_out)
    opp_out = [
        score_roster(board, rosters[t], pts=pts_out)[0]
        for t in range(TEAMS) if t != our_slot
    ]
    return {
        "total": total,
        "starters": starters,
        "out_starters": out_starters,
        "rank": 1 + sum(1 for s in opp_out if s > out_total),
        "picks": [(board.names[i], board.pos[i]) for i in rosters[our_slot]],
    }


def main(n_sims=300, out="sim_results.json"):
    pool = load_pool()
    print(f"Pool: {len(pool)} players")
    results = []
    pick_log = defaultdict(lambda: defaultdict(int))  # (slot,strategy) -> player -> count

    total_jobs = TEAMS * len(STRATEGIES)
    job = 0
    for slot in range(TEAMS):
        for strat in STRATEGIES:
            job += 1
            totals, starters, outs, ranks = [], [], [], []
            first8 = defaultdict(int)
            for s in range(n_sims):
                r = run_draft(pool, slot, strat, seed=slot * 100003 + hash(strat) % 100000 + s)
                totals.append(r["total"])
                starters.append(r["starters"])
                outs.append(r["out_starters"])
                ranks.append(r["rank"])
                for rd, (name, pos) in enumerate(r["picks"][:8], 1):
                    first8[(rd, name, pos)] += 1
            results.append(
                {
                    "slot": slot + 1,
                    "strategy": strat,
                    "mean_total": float(np.mean(totals)),
                    "mean_starters": float(np.mean(starters)),
                    "floor_p10": float(np.percentile(outs, 10)),
                    "ceiling_p90": float(np.percentile(outs, 90)),
                    "mean_rank": float(np.mean(ranks)),
                    "top3_rate": float(np.mean([r <= 3 for r in ranks])),
                    "common_picks": sorted(
                        (
                            {"round": rd, "player": nm, "pos": ps, "rate": c / n_sims}
                            for (rd, nm, ps), c in first8.items()
                            if c / n_sims >= 0.12
                        ),
                        key=lambda x: (x["round"], -x["rate"]),
                    ),
                }
            )
            print(
                f"[{job}/{total_jobs}] slot {slot+1:2d} {strat:12s} "
                f"starters={np.mean(starters):7.1f} rank={np.mean(ranks):4.1f}"
            )

    with open(out, "w") as f:
        json.dump(results, f, indent=1)
    print(f"\nSaved {out}")

    # Cheat sheet: VORP ranking with ADP value gap
    sheet = pool[pool["pos"].isin(["QB", "RB", "WR", "TE"])].copy()
    sheet = sheet.sort_values("vorp", ascending=False).reset_index(drop=True)
    sheet["vorp_rank"] = sheet.index + 1
    sheet["adp_rank"] = sheet["adp_ppr"].rank(method="first").astype(int)
    sheet["value_gap"] = sheet["adp_rank"] - sheet["vorp_rank"]
    sheet.to_csv("cheat_sheet.csv", index=False)
    print("Saved cheat_sheet.csv")


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    main(n_sims=n)
