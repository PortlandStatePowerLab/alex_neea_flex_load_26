"""Compare capacity commitments, gains and timesteps using fresh controlled runs.

Example: python Combo/E2_TrackingTuning.py --frequency .1 --fractions .5 .75 1 --gains .6 .8 1 --timesteps 1 .5
One baseline is reused for every gain/commitment at the SAME timestep. Each
new timestep requires its own baseline. Results checkpoint after each trial.
"""
import argparse
import csv
import datetime as dt
import itertools
import json
import math
from pathlib import Path
import uuid


def run_comparison(frequency=.1, fractions=(.5, .75, 1.), gains=(.6, .8, 1.),
                   timesteps=(1., .5), output_dir=None):
    try:
        from . import B1_Baseline as b1, B2_Regulation as b2, C4_Performance_Score as c4
    except ImportError:
        import B1_Baseline as b1
        import B2_Regulation as b2
        import C4_Performance_Score as c4
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("Frequency must be finite and positive")
    for values, low, high, label in ((fractions, 0, 1, "fractions"), (gains, 0, 1, "gains"),
                                     (timesteps, 0, 1, "timesteps")):
        if not values or any(not math.isfinite(v) or not low < v <= high for v in values):
            raise ValueError(f"{label} must contain values in (0, 1]")
    if any(frequency >= .5 / step for step in timesteps):
        raise ValueError("Frequency must be below Nyquist at every timestep")
    root = Path(output_dir) if output_dir else Path(__file__).resolve().parent / "Results" / "TrackingTuning"
    root = root / (dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    saved = [b1.CONFIG.copy(), b2.CONFIG.copy()]
    rows = []
    def checkpoint():
        (root / "comparison.json").write_text(json.dumps(rows, indent=2, allow_nan=False))
        if rows:
            columns = list(dict.fromkeys(key for row in rows for key in row))
            with (root / "comparison.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
    try:
        for step in timesteps:
            for module in (b1, b2):
                module.CONFIG.update(t_res=step, RESULTS_DIR=str(root / f"timestep_{step:g}"),
                                     MIN_HOLD_STEPS=max(1, round(module.CONFIG["MIN_HOLD_MINUTES"] / step)),
                                     CONTROL_INTERVAL_STEPS=1)
            baseline = b1.main()
            baseline_dir = Path(baseline["manifest_path"]).parent
            for fraction, gain in itertools.product(fractions, gains):
                row = dict(timestep_minutes=step, capacity_fraction=fraction, feedback_gain=gain,
                           frequency_cycles_per_minute=frequency, status="running")
                rows.append(row)
                checkpoint()
                try:
                    b2.CONFIG.update(REGULATION_CAPACITY_FRACTION=fraction, FEEDBACK_GAIN=gain)
                    controlled = b2.main(str(baseline_dir), sine_freq=frequency)
                    run_dir = Path(controlled["manifest_path"]).parent
                    row["run_dir"] = str(run_dir)
                    row.update(json.loads((run_dir / "tracking_summary.json").read_text()))
                    row["performance_score"] = float(c4.main(run_dir=run_dir))
                    row["status"] = "complete"
                except Exception as exc:
                    row.update(status="failed", error=repr(exc))
                    raise
                finally:
                    checkpoint()
    finally:
        for module, config in zip((b1, b2), saved):
            module.CONFIG.clear()
            module.CONFIG.update(config)
    print(f"Tracking comparison saved: {root}", flush=True)
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frequency", type=float, default=.1)
    parser.add_argument("--fractions", type=float, nargs="+", default=[.5, .75, 1.])
    parser.add_argument("--gains", type=float, nargs="+", default=[.6, .8, 1.])
    parser.add_argument("--timesteps", type=float, nargs="+", default=[1., .5])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    run_comparison(args.frequency, args.fractions, args.gains, args.timesteps, args.output_dir)
