"""
Author: Alex Wardwell
Created: 8/17/26

Calculates performance score describing how well a flex load can follow a regulation signal.
Adapted from HPWH_C4.py; retains its PJM-style scoring algorithm and configured
30-minute window. This is a research metric, not official PJM market scoring.
Reads B2 regulation_tracking.csv; writes summaries under the run's Ready_data.
Run directly for the latest completed pair or pass --run-dir / --run-id.

@modified by: 
@modified date: 
"""

from pathlib import Path
import json

try:
    from .C3_Normalized_Regulation import resolve_run, load_tracking
except ImportError:
    from C3_Normalized_Regulation import resolve_run, load_tracking
import numpy as np
import pandas as pd
import argparse


# ---------------------------------------------------------------------------
# SCORING SETTINGS
# ---------------------------------------------------------------------------

SCORING_WINDOW_MINUTES = 5.0 * 6.0
MAX_TIMESTEP_MINUTES = 1.0
MIN_CONTIGUOUS_MINUTES = 15.0


# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

RUN_DIR = None  # Default: latest completed B1/B2 pair.


def load_vpp_data(path):
    """Load and prepare the B2 VPP state log."""
    df = load_tracking(path)

    required = {
        "Time",
        "Up Regulation Capacity (kW)",
        "Down Regulation Capacity (kW)",
        "Target Delta (kW)",
        "Actual Fleet Delta (kW)",
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"VPP log is missing required columns: {sorted(missing)}"

        )

    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    numeric_columns = [
        "Up Regulation Capacity (kW)",
        "Down Regulation Capacity (kW)",
        "Target Delta (kW)",
        "Actual Fleet Delta (kW)",
    ]
    df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric, errors="coerce")

    invalid_rows = df[["Time", *numeric_columns]].isna().any(axis=1)
    if invalid_rows.any():
        raise ValueError(
            f"VPP log contains {int(invalid_rows.sum())} row(s) with an invalid "
            "timestamp or required numeric value."
        )

    if df.empty:
        raise ValueError("VPP log contains no scoreable rows.")

    df = df.sort_values("Time")
    duplicate_times = df["Time"].duplicated(keep=False)
    if duplicate_times.any():
        raise ValueError(
            f"VPP log contains {int(duplicate_times.sum())} row(s) with duplicate timestamps."
        )

    capacity_columns = [
        "Up Regulation Capacity (kW)",
        "Down Regulation Capacity (kW)",
    ]
    if (df[capacity_columns] <= 0).any().any():
        raise ValueError("Up and down regulation capacities must remain greater than zero.")

    # Infer the actual simulation timestep from timestamps.
    diffs_seconds = df["Time"].diff().dt.total_seconds().dropna()
    if diffs_seconds.empty:
        raise ValueError("VPP log must contain at least two timestamps.")

    timestep_seconds = float(diffs_seconds.median())
    if not np.isfinite(timestep_seconds) or timestep_seconds <= 0:
        raise ValueError("Could not infer a positive VPP log timestep.")

    if not np.allclose(diffs_seconds, timestep_seconds, rtol=0.0, atol=1e-6):
        raise ValueError(
            "VPP log timestamps are not regularly spaced. Delay scoring requires "
            "a complete, regular time series."
        )

    timestep_minutes = timestep_seconds / 60.0
    if timestep_minutes > MAX_TIMESTEP_MINUTES + 1e-9:
        raise ValueError(
            f"VPP log timestep is {timestep_minutes:g} minutes. C4 requires "
            f"{MAX_TIMESTEP_MINUTES:g}-minute resolution or finer."
        )

    window_steps = SCORING_WINDOW_MINUTES / timestep_minutes
    if not np.isclose(window_steps, round(window_steps), rtol=0.0, atol=1e-9):
        raise ValueError(
            f"The {timestep_minutes:g}-minute timestep does not divide evenly into "
            f"the {SCORING_WINDOW_MINUTES:g}-minute scoring window."
        )

    duration_minutes = (df["Time"].iloc[-1] - df["Time"].iloc[0]).total_seconds() / 60.0
    if duration_minutes < MIN_CONTIGUOUS_MINUTES:
        raise ValueError(
            f"VPP log spans only {duration_minutes:g} minutes. At least "
            f"{MIN_CONTIGUOUS_MINUTES:g} contiguous minutes are required."
        )

    return df, float(timestep_minutes)


def _slope_correlation_score(pair, t_res):
    """Return the documented low-variation slope fallback on a 0-to-1 scale."""
    elapsed_minutes = np.arange(len(pair), dtype=float) * t_res
    target_values = pair["target"].to_numpy(dtype=float)
    actual_values = pair["actual"].to_numpy(dtype=float)

    # Normalize both slopes to the target's kW scale so their difference is
    # dimensionless and comparable between fleets of different sizes.
    scale_kw = max(float(np.max(np.abs(target_values))), 1.0)
    target_slope = np.polyfit(elapsed_minutes, target_values / scale_kw, 1)[0]
    actual_slope = np.polyfit(elapsed_minutes, actual_values / scale_kw, 1)[0]
    return float(np.clip(1.0 - abs(target_slope - actual_slope), 0.0, 1.0))


def pjm_delay_corr(target, actual, timestamp, t_res):
    """
    Calculate delay and correlation scores for the trailing configured scoring window
    ending at `timestamp`.

    Parameters
    ----------
    target : pd.Series
        Target Delta (kW), indexed by timestamp.
    actual : pd.Series
        Actual Fleet Delta (kW), indexed by timestamp.
    timestamp : pd.Timestamp
        End of the scoring window.
    t_res : float
        Data timestep in minutes.
    """
    candidates = []

    target = target.sort_index()
    actual = actual.sort_index()

    window_end = pd.Timestamp(timestamp)
    window_start = window_end - pd.Timedelta(minutes=SCORING_WINDOW_MINUTES)

    delay_steps = int(round(SCORING_WINDOW_MINUTES / t_res))
    delay_minutes = np.arange(delay_steps + 1, dtype=float) * t_res
    minimum_samples = delay_steps + 1
    window_actual = actual.loc[window_start:window_end].rename("actual")

    for delay_min in delay_minutes:
        shifted_target = target.rename("target").copy()
        shifted_target.index = shifted_target.index + pd.Timedelta(minutes=float(delay_min))
        shifted_target = shifted_target.loc[window_start:window_end]
        pair = pd.concat([shifted_target, window_actual], axis=1).dropna()

        if len(pair) < minimum_samples:
            corr = np.nan
        else:
            target_scale = max(float(pair["target"].abs().max()), 1.0)
            flat_threshold = max(1e-9, target_scale * 1e-6)
            if pair["target"].std() <= flat_threshold:
                corr = _slope_correlation_score(pair, t_res)
            elif pair["actual"].std() <= 1e-12:
                # A varying request and constant response have no useful
                # correlation and must not disappear from the average.
                corr = 0.0
            else:
                corr = pair["target"].corr(pair["actual"])

        delay_score = abs(
            (delay_min - SCORING_WINDOW_MINUTES) / SCORING_WINDOW_MINUTES
        )

        if np.isfinite(corr):
            candidates.append(
                {
                    "delay_min": float(delay_min),
                    "corr_score": float(corr),
                    "delay_score": float(delay_score),
                    "selection_score": float(corr + delay_score),
                }
            )

    if not candidates:
        return {
            "delay_min": np.nan,
            "corr_score": np.nan,
            "delay_score": np.nan,
            "selection_score": np.nan,
        }

    return max(candidates, key=lambda x: x["selection_score"])


def pjm_precision(target, actual, up_reg_cap_kw, dwn_reg_cap_kw):
    """Calculate direction-aware precision for the asymmetric Combo fleet."""
    pair = pd.concat(
        [
            target.rename("target"),
            actual.rename("actual"),
            up_reg_cap_kw.rename("up_capacity"),
            dwn_reg_cap_kw.rename("down_capacity"),
        ],
        axis=1,
    ).dropna()

    if pair.empty:
        return np.nan

    # Positive target means increased fleet consumption in B2. At a zero target, use
    # the direction of any unintended response so that it is penalized against
    # the capacity on the side where it occurred.
    capacity = np.where(
        pair["target"] > 0,
        pair["up_capacity"],
        np.where(
            pair["target"] < 0,
            pair["down_capacity"],
            np.where(pair["actual"] >= 0, pair["up_capacity"], pair["down_capacity"]),
        ),
    )

    if not np.isfinite(capacity).all() or (capacity <= 0).any():
        return np.nan

    normalized_error = (pair["target"] - pair["actual"]).abs().to_numpy() / capacity
    return float(np.clip(1.0 - normalized_error.mean(), 0.0, 1.0))


def main(run_dir=None, run_id=None):
    run_dir = resolve_run(RUN_DIR if run_dir is None and run_id is None else run_dir, run_id)
    vpp_path = run_dir / "regulation_tracking.csv"
    df, t_res = load_vpp_data(vpp_path)

    delay_corr = []
    indexed = df.set_index("Time")
    target = indexed["Target Delta (kW)"]
    actual = indexed["Actual Fleet Delta (kW)"]
    for timestamp in target.index:
        delay_corr.append(pjm_delay_corr(target, actual, timestamp, t_res))

    delay_corr_df = pd.DataFrame(delay_corr, index=target.index)
    hourly_scores = []
    hourly_components = []
    hourly_rows = []

    for hour, hour_data in indexed.groupby(pd.Grouper(freq="h")):
        if hour_data.empty:
            continue

        hour_span = (hour_data.index[-1] - hour_data.index[0]).total_seconds() / 60.0
        if hour_span < MIN_CONTIGUOUS_MINUTES:
            continue

        hour_delay_corr = delay_corr_df.loc[hour_data.index]
        avg_corr = hour_delay_corr["corr_score"].mean()
        avg_delay = hour_delay_corr["delay_score"].mean()
        precision = pjm_precision(
            hour_data["Target Delta (kW)"],
            hour_data["Actual Fleet Delta (kW)"],
            hour_data["Up Regulation Capacity (kW)"],
            hour_data["Down Regulation Capacity (kW)"],
        )

        components = np.array([avg_corr, avg_delay, precision], dtype=float)
        if np.isfinite(components).all():
            hourly_scores.append(float(components.mean()))
            hourly_components.append(components)
            hourly_rows.append({"Time": hour, "Correlation": avg_corr,
                                "Delay": avg_delay, "Precision": precision,
                                "Performance": float(components.mean())})

    if not hourly_scores:
        raise ValueError(
            "VPP log did not contain an hour with enough valid data to calculate all "
            "three performance components."
        )

    mean_components = np.mean(np.vstack(hourly_components), axis=0)
    print(
        "PJM-style components: "
        f"correlation={mean_components[0]:.6f}, "
        f"delay={mean_components[1]:.6f}, "
        f"precision={mean_components[2]:.6f}",
        f"correlation (straight)={target.corr(actual)}",
        flush=True,
    )

    score = float(np.mean(hourly_scores))
    output_dir = run_dir / "Ready_data"
    output_dir.mkdir(exist_ok=True)
    delay_corr_df.rename_axis("Time").to_csv(output_dir / "C4_delay_correlation.csv")
    pd.DataFrame(hourly_rows).to_csv(output_dir / "C4_hourly_scores.csv", index=False)
    straight_corr = target.corr(actual)
    summary = {
        "run_id": run_dir.name, "performance_score": score,
        "correlation_score": float(mean_components[0]),
        "delay_score": float(mean_components[1]),
        "precision_score": float(mean_components[2]),
        "zero_lag_correlation": float(straight_corr) if np.isfinite(straight_corr) else None,
        "scoring_window_minutes": SCORING_WINDOW_MINUTES,
        "timestep_minutes": t_res, "hours_scored": len(hourly_scores),
        "method": "PJM-style; retained HPWH C4 algorithm, not official market scoring",
    }
    (output_dir / "C4_performance_summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Performance results saved to: {output_dir}")
    return score

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run-dir", type=Path)
    group.add_argument("--run-id", help="Folder name under Combo/Results")
    args = parser.parse_args()
    score = main(args.run_dir, args.run_id)
    print(f"PJM-style performance score: {score:.6f}")
