"""One-command refresh: re-pull every data source, re-run the sim, rebuild the page.

    .venv/bin/python refresh.py            # full refresh, 300 sims
    .venv/bin/python refresh.py --sims 50  # quick data refresh, fewer sims
    .venv/bin/python refresh.py --no-sim   # data + dashboard only (keeps last sim run)

Required steps abort the run; intel steps (injuries, depth charts, FantasyPros)
just warn and continue — the dashboard renders without them.
"""
import argparse
import subprocess
import sys
import time

STEPS = [
    # (label, argv, required)
    ("Sleeper projections + ADP  -> players.csv", ["fetch_data.py"], True),
    ("Monte Carlo sim            -> sim_results.json", None, True),  # filled in below
    ("Report tables              -> report.json", ["analyze.py"], True),
    ("Injuries + trending        -> intel.json", ["fetch_intel.py"], False),
    ("ESPN depth charts          -> depth.json", ["fetch_depth.py"], False),
    ("FantasyPros consensus      -> fp_rankings.json", ["fetch_fp.py"], False),
    ("2025 actual stats          -> history.json", ["fetch_history.py"], False),
    ("Dashboard                  -> dashboard.html + index.html", ["build_dashboard.py"], True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=300, help="sims per slot/strategy")
    ap.add_argument("--no-sim", action="store_true", help="skip the Monte Carlo re-run")
    args = ap.parse_args()

    t0 = time.time()
    for label, argv, required in STEPS:
        if argv is None:  # the sim step
            if args.no_sim:
                print(f"~ SKIP  {label}")
                continue
            argv = ["draft_sim.py", str(args.sims)]
        t = time.time()
        r = subprocess.run([sys.executable] + argv, capture_output=True, text=True)
        if r.returncode == 0:
            print(f"+ OK    {label}  ({time.time() - t:.0f}s)")
        else:
            tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
            print(f"{'! FAIL' if required else '~ WARN'}  {label}")
            for line in tail:
                print(f"        {line}")
            if required:
                sys.exit(1)

    print(f"\nDone in {time.time() - t0:.0f}s.")
    print("Publish: git add -A && git commit -m 'Refresh data' && git push")


if __name__ == "__main__":
    main()
