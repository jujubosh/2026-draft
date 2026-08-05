"""Turn sim_results.json + cheat_sheet.csv into report tables (report.json)."""
import json

import pandas as pd


def main():
    with open("sim_results.json") as f:
        results = json.load(f)
    df = pd.DataFrame(results)

    # Strategy x slot matrix of mean starter points
    matrix = df.pivot(index="strategy", columns="slot", values="mean_starters")

    # Overall strategy ranking (mean across slots)
    overall = (
        df.groupby("strategy")
        .agg(
            mean_starters=("mean_starters", "mean"),
            mean_total=("mean_total", "mean"),
            floor_p10=("floor_p10", "mean"),
            ceiling_p90=("ceiling_p90", "mean"),
            top3_rate=("top3_rate", "mean"),
        )
        .sort_values("mean_starters", ascending=False)
    )

    # Best strategy per slot + its most common early picks
    best_by_slot = []
    for slot in sorted(df["slot"].unique()):
        sub = df[df["slot"] == slot].sort_values("mean_starters", ascending=False)
        top = sub.iloc[0]
        second = sub.iloc[1]
        best_by_slot.append(
            {
                "slot": int(slot),
                "strategy": top["strategy"],
                "mean_starters": round(top["mean_starters"], 1),
                "edge_over_2nd": round(top["mean_starters"] - second["mean_starters"], 1),
                "second": second["strategy"],
                "common_picks": top["common_picks"],
            }
        )

    sheet = pd.read_csv("cheat_sheet.csv")

    report = {
        "matrix": {
            "strategies": matrix.index.tolist(),
            "slots": [int(c) for c in matrix.columns],
            "values": [[round(v, 1) for v in row] for row in matrix.values],
        },
        "overall": [
            {
                "strategy": s,
                "mean_starters": round(r.mean_starters, 1),
                "floor_p10": round(r.floor_p10, 1),
                "ceiling_p90": round(r.ceiling_p90, 1),
                "top3_rate": round(r.top3_rate, 3),
            }
            for s, r in overall.iterrows()
        ],
        "best_by_slot": best_by_slot,
        "cheat_sheet": sheet.head(180).to_dict(orient="records"),
    }
    with open("report.json", "w") as f:
        json.dump(report, f, indent=1)

    print("OVERALL STRATEGY RANKING (mean starter pts across all 12 slots):")
    print(overall.round(1).to_string())
    print("\nBEST STRATEGY PER SLOT:")
    for b in best_by_slot:
        print(
            f"  Slot {b['slot']:2d}: {b['strategy']:12s} {b['mean_starters']:7.1f} "
            f"(+{b['edge_over_2nd']:.1f} over {b['second']})"
        )


if __name__ == "__main__":
    main()
