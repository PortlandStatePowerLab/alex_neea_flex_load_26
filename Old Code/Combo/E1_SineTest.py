"""Increase sine frequency until C4's PJM-style score falls below a threshold.

Reuses the most recent completed baseline for every B2 controlled simulation;
never runs B1. No plots are generated. Sweep summaries are retained under
Combo/Results/SineTests/<sweep_id>; simulations, C4 outputs, and sampled sine
signals are saved in separate controlled subfolders of the selected baseline.
Edit the settings below or use --help for command-line overrides.
"""

import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path
import uuid

THRESHOLD = 0.65
START_FREQUENCY = 0.01  # cycles per minute (period = 100 minutes)
FREQUENCY_STEP = 0.01  # additive increase, cycles per minute
MAX_ITERATIONS = 50
OUTPUT_DIR = Path(__file__).resolve().parent / "Results" / "SineTests"


def find_latest_baseline(results_dir):
    """Select by B1's timestamped run ID, unaffected by later controlled runs."""
    candidates = []
    for path in Path(results_dir).rglob("manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("status") != "complete":
                continue
            created = dt.datetime.strptime(manifest["run_id"][:15], "%Y%m%d_%H%M%S")
            if not all((path.parent / name).is_file() for name in ("baseline.csv", "capacity.csv")):
                continue
            candidates.append((created, path.stat().st_mtime_ns, path.parent))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not candidates:
        raise FileNotFoundError(f"No completed baseline found in {results_dir}. Run B1 separately first.")
    return max(candidates, key=lambda item: item[:2])[2].resolve()


def run_trial(frequency, trial_dir, baseline_dir):
    """Run the real pipeline without changing source files or opening plots."""
    try:
        from . import B2_Regulation as b2
        from . import C4_Performance_Score as c4
    except ImportError:
        import B2_Regulation as b2
        import C4_Performance_Score as c4

    timestep = float(b2.CONFIG["t_res"])
    if not math.isfinite(timestep) or timestep <= 0:
        raise ValueError("Simulation timestep must be finite and positive")
    if timestep > c4.MAX_TIMESTEP_MINUTES:
        raise ValueError("Simulation timestep is too coarse for C4 scoring")
    if frequency >= 0.5 / timestep:
        raise ValueError(f"Frequency {frequency:g} cycles/min must be below "
                         f"Nyquist ({0.5 / timestep:g} cycles/min)")
    # B2 validates that the other physical settings match B1's configuration.
    saved = b2.CONFIG.copy()
    try:
        controlled = b2.main(str(baseline_dir), sine_freq=frequency)
        run_dir = Path(controlled["manifest_path"]).resolve().parent
        (trial_dir / "run_paths.json").write_text(json.dumps({
            "baseline_dir": str(baseline_dir), "run_dir": str(run_dir)
        }, indent=2), encoding="utf-8")
        # B2's tracking log contains the precise signal actually dispatched.
        import pandas as pd
        tracking = pd.read_csv(run_dir / "regulation_tracking.csv",
                               usecols=["Time", "reg_sig", "target_delta_kw"])
        tracking.to_csv(run_dir / "sine_signal.csv", index=False)
        score = float(c4.main(run_dir=run_dir))
        return score, run_dir
    finally:
        b2.CONFIG.clear()
        b2.CONFIG.update(saved)


def save_results(sweep_dir, summary, history):
    """Checkpoint after every trial, including errors and interruptions."""
    (sweep_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    with (sweep_dir / "frequency_results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "iteration", "frequency_cycles_per_minute", "period_minutes",
            "score", "passed", "status", "trial_dir", "run_dir", "error"])
        writer.writeheader()
        writer.writerows(history)


def run_sweep(threshold=THRESHOLD, start_frequency=START_FREQUENCY,
              frequency_step=FREQUENCY_STEP, max_iterations=MAX_ITERATIONS,
              output_dir=OUTPUT_DIR, trial_runner=None):
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    if any(not math.isfinite(v) or v <= 0 for v in (start_frequency, frequency_step)):
        raise ValueError("start_frequency and frequency_step must be finite and positive")
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    baseline_dir = None
    if trial_runner is None:
        try:
            from . import B2_Regulation as b2
        except ImportError:
            import B2_Regulation as b2
        baseline_dir = find_latest_baseline(b2.CONFIG.get(
            "RESULTS_DIR", Path(__file__).resolve().parent / "Results"))
        print(f"Using existing baseline: {baseline_dir}", flush=True)
        trial_runner = lambda frequency, trial_dir: run_trial(frequency, trial_dir, baseline_dir)
    sweep_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    sweep_dir = Path(output_dir).resolve() / sweep_id
    sweep_dir.mkdir(parents=True)
    summary = {"sweep_id": sweep_id, "status": "running", "threshold": threshold,
               "baseline_dir": str(baseline_dir) if baseline_dir else None,
               "start_frequency_cycles_per_minute": start_frequency,
               "frequency_step_cycles_per_minute": frequency_step,
               "max_iterations": max_iterations, "completed_trials": 0,
               "failure_rule": "score < threshold (equality passes)",
               "failed_frequency_cycles_per_minute": None,
               "last_passing_frequency_cycles_per_minute": None}
    history = []
    save_results(sweep_dir, summary, history)
    print(f"Sweep results: {sweep_dir}", flush=True)
    for iteration in range(1, max_iterations + 1):
        frequency = start_frequency + (iteration - 1) * frequency_step
        trial_dir = sweep_dir / f"trial_{iteration:03d}"
        trial_dir.mkdir()
        row = {"iteration": iteration, "frequency_cycles_per_minute": frequency,
               "period_minutes": 1 / frequency, "trial_dir": str(trial_dir),
               "run_dir": "", "score": "", "passed": "", "status": "running", "error": ""}
        history.append(row)
        save_results(sweep_dir, summary, history)
        print(f"Trial {iteration}/{max_iterations}: {frequency:g} cycles/min "
              f"(period {1 / frequency:g} min)", flush=True)
        try:
            score, run_dir = trial_runner(frequency, trial_dir)
            score = float(score)
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError(f"C4 returned an invalid score: {score}")
            passed = score >= threshold
            row.update(score=score, passed=passed, status="complete", run_dir=str(run_dir))
            summary["completed_trials"] += 1
            if passed:
                summary["last_passing_frequency_cycles_per_minute"] = frequency
            else:
                summary.update(status="threshold_failed", failed_score=score,
                               failed_frequency_cycles_per_minute=frequency)
            print(f"Score {score:.6f}: {'PASS' if passed else 'FAIL'} "
                  f"(threshold {threshold:g})", flush=True)
            save_results(sweep_dir, summary, history)
            if not passed:
                print(f"Failed at {frequency:g} cycles/min (period {1 / frequency:g} min). "
                      f"Results: {sweep_dir}", flush=True)
                return summary
        except (Exception, KeyboardInterrupt) as exc:
            status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "error"
            row.update(status=status, error=repr(exc))
            summary.update(status=status, error=repr(exc),
                           error_frequency_cycles_per_minute=frequency)
            save_results(sweep_dir, summary, history)
            print(f"Sweep {status} at {frequency:g} cycles/min; "
                  f"no threshold failure established for this trial. Results: {sweep_dir}", flush=True)
            raise
    summary["status"] = "max_iterations_reached"
    save_results(sweep_dir, summary, history)
    print(f"No threshold failure in {max_iterations} trials. "
          f"Highest tested frequency: {frequency:g} cycles/min. Results: {sweep_dir}", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument("--start-frequency", type=float, default=START_FREQUENCY,
                        help="Starting frequency in cycles per minute")
    parser.add_argument("--frequency-step", type=float, default=FREQUENCY_STEP,
                        help="Additive frequency increment in cycles per minute")
    parser.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    run_sweep(args.threshold, args.start_frequency, args.frequency_step,
              args.max_iterations, args.output_dir)


if __name__ == "__main__":
    main()
