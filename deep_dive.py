"""Deep dive per draft slot: re-run the slot's winning strategy at high sim
count and record what the sim actually took every round -> deep_dive.json.

For each round, the output is a decision chain: the most common pick, then —
among the sims that didn't take him (usually because he was gone) — the next
choice, and so on. `rate` is the share of all sims; `cond` is the share of the
sims remaining at that link in the chain ("if the guys above are gone").
"""
import json
from collections import defaultdict

import numpy as np

from draft_sim import ROUNDS, TEAMS, load_pool, run_draft

N_SIMS = 1500


def main():
    pool = load_pool()
    with open("report.json") as f:
        best = {b["slot"]: b["strategy"] for b in json.load(f)["best_by_slot"]}

    out = {}
    for slot in range(1, TEAMS + 1):
        strat = best[slot]
        by_round = [defaultdict(int) for _ in range(ROUNDS)]
        starters, outs, ranks = [], [], []
        for s in range(N_SIMS):
            r = run_draft(pool, slot - 1, strat, seed=900000 + slot * 131071 + s)
            starters.append(r["starters"])
            outs.append(r["out_starters"])
            ranks.append(r["rank"])
            for rd, (name, pos) in enumerate(r["picks"]):
                by_round[rd][(name, pos)] += 1

        rounds = []
        for rd in range(ROUNDS):
            total = sum(by_round[rd].values())
            opts = sorted(by_round[rd].items(), key=lambda kv: -kv[1])
            chain, remaining = [], total
            for (name, pos), c in opts[:4]:
                chain.append(
                    {"player": name, "pos": pos,
                     "rate": round(c / total, 3),
                     "cond": round(c / remaining, 3) if remaining else 0}
                )
                remaining -= c
            pos_mix = defaultdict(int)
            for (name, pos), c in by_round[rd].items():
                pos_mix[pos] += c
            pick_no = rd * TEAMS + (slot if rd % 2 == 0 else TEAMS + 1 - slot)
            rounds.append(
                {"round": rd + 1, "pick": pick_no, "options": chain,
                 "pos_mix": {p: round(c / total, 3) for p, c in
                             sorted(pos_mix.items(), key=lambda kv: -kv[1])}}
            )

        out[str(slot)] = {
            "strategy": strat,
            "mean_starters": round(float(np.mean(starters)), 1),
            "floor_p10": round(float(np.percentile(outs, 10)), 1),
            "ceiling_p90": round(float(np.percentile(outs, 90)), 1),
            "top3_rate": round(float(np.mean([x <= 3 for x in ranks])), 3),
            "rounds": rounds,
        }
        print(f"slot {slot:2d}: {strat:12s} {out[str(slot)]['mean_starters']:7.1f} "
              f"starter pts, top-3 {out[str(slot)]['top3_rate']*100:.0f}%")

    with open("deep_dive.json", "w") as f:
        json.dump({"n_sims": N_SIMS, "slots": out}, f, indent=1)
    print("\nSaved deep_dive.json")


if __name__ == "__main__":
    main()
