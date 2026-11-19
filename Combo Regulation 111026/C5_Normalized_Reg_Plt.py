"""
Author: Alex Wardwell
Created: 8/12/26

@modified by: 
@modified date: 
"""

import argparse
from pathlib import Path
import numpy as np

try:
    from .C1_parse_OCHRE_data_final import select_run, RESULTS_DIR
except ImportError:
    from C1_parse_OCHRE_data_final import select_run, RESULTS_DIR

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


RUN_DIR = None  # Default: latest completed B1/B2 pair.
PLOT_POINTS = None  # None plots all reporting samples; first-day warm-up is already removed.


def resolve_run(run_dir=None, run_id=None):
    if run_dir is not None and run_id is not None:
        raise ValueError("Use either run_dir or run_id, not both")
    return select_run(RESULTS_DIR / run_id if run_id is not None else run_dir)


def load_tracking(path):
    """Translate B2's tracking schema for C3/C4 without importing simulations."""
    data = pd.read_csv(path)
    data = data.rename(columns={
        "reg_sig": "Regulation Signal",
        "target_delta_kw": "Target Delta (kW)",
        "Actual Delta (kW)": "Actual Fleet Delta (kW)",
        "Up Capacity (kW)": "Up Regulation Capacity (kW)",
        "Down Capacity (kW)": "Down Regulation Capacity (kW)",
    })
    numeric = ["Regulation Signal", "Target Delta (kW)", "Actual Fleet Delta (kW)",
               "Up Regulation Capacity (kW)", "Down Regulation Capacity (kW)"]
    missing = {"Time", *numeric} - set(data.columns)
    if missing:
        raise ValueError(f"{path}: missing tracking columns {sorted(missing)}")
    data["Time"] = pd.to_datetime(data["Time"], errors="raise")
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="raise")
    if (data.empty or data["Time"].isna().any() or data["Time"].duplicated().any()
            or not np.isfinite(data[numeric].to_numpy()).all()):
        raise ValueError(f"{path}: empty, duplicate, missing, or nonfinite tracking samples")
    return data.sort_values("Time").reset_index(drop=True)


def load_normalized_response(vpp_log_file):
    """Load aligned regulation request and capacity-normalized fleet response."""
    data = load_tracking(vpp_log_file)
    required_columns = {
        "Time",
        "Regulation Signal",
        "Up Regulation Capacity (kW)",
        "Down Regulation Capacity (kW)",
        "Actual Fleet Delta (kW)",
    }
    missing_columns = required_columns - set(data.columns)
    if missing_columns:
        raise ValueError(
            f"{vpp_log_file} is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    numeric_columns = [
        "Regulation Signal",
        "Up Regulation Capacity (kW)",
        "Down Regulation Capacity (kW)",
        "Actual Fleet Delta (kW)",
    ]
    data[numeric_columns] = data[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    data = data.dropna(subset=["Time", *numeric_columns]).copy()
    if data.empty:
        raise ValueError(f"No usable fleet-response rows were found in: {vpp_log_file}")
    if (
        (data["Up Regulation Capacity (kW)"] <= 0).any()
        or (data["Down Regulation Capacity (kW)"] <= 0).any()
    ):
        raise ValueError(
            "Up and down regulation capacities must be greater than zero."
        )

    up_request = data["Regulation Signal"] >= 0
    data["normalization_capacity_kw"] = data[
        "Down Regulation Capacity (kW)"
    ]
    data.loc[
        up_request, "normalization_capacity_kw"
    ] = data.loc[
        up_request, "Up Regulation Capacity (kW)"
    ]
    data["normalized_actual_response"] = (
        data["Actual Fleet Delta (kW)"]
        / data["normalization_capacity_kw"]
    )

    return data.sort_values("Time")


def select_hour_windows(response):
    """Rank complete, uniformly sampled [start, start + 1 hour) windows."""
    response = response.sort_values("Time").reset_index(drop=True)
    steps = response["Time"].diff().dropna()
    if steps.empty:
        raise ValueError("At least one complete hour of tracking samples is required.")
    step = steps.median()
    hour = pd.Timedelta(hours=1)
    count = round(hour / step)
    if count < 2 or abs(count * step - hour) > pd.Timedelta(milliseconds=1):
        raise ValueError("Tracking sample interval must evenly divide one hour.")
    errors = (response["normalized_actual_response"] - response["Regulation Signal"]) ** 2
    scores = errors.rolling(count).mean()
    # A gap invalidates every candidate that crosses it.
    regular = response["Time"].diff().eq(step)
    complete = regular.rolling(count - 1).sum().eq(count - 1)
    scores = scores.where(complete).dropna()
    if scores.empty:
        raise ValueError("No complete, gap-free one-hour tracking window was found.")
    return {
        kind: (response.iloc[end - count + 1:end + 1].copy(), float(np.sqrt(scores.loc[end])))
        for kind, end in (("best", scores.idxmin()), ("worst", scores.idxmax()))
    }


def plot_hour(response, kind, rmse, plot_file, y_limit, no_show):
    """Save a selected hour with compact text and an in-axes legend."""
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(response["Time"], response["normalized_actual_response"],
            label="(controlled - baseline) / regulation capacity", color="green")
    ax.plot(response["Time"], response["Regulation Signal"],
            label="regulation signal", color="mediumorchid", linestyle="--")
    ax.axhline(0.0, color="black", linewidth=1, alpha=0.6)
    ax.set_ylim(-y_limit, y_limit)
    start = response["Time"].iloc[0]
    ax.set_xlim(start, start + pd.Timedelta(hours=1))
    ax.set_title(f"{kind.title()} One-Hour Regulation Response\n(RMSE = {rmse:.4f})",
                 fontsize=12)
    ax.set_xlabel("Time", fontsize=12)
    ax.set_ylabel("Fraction of Static Regulation Capacity", fontsize=12)
    ax.tick_params(axis="both", labelsize=10)
    ax.legend(loc="best", fontsize=10, frameon=True, facecolor="white", framealpha=0.9)
    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(plot_file)
    print(f"{kind.title()} hour: {start} to {start + pd.Timedelta(hours=1)}; "
          f"normalized RMSE={rmse:.6f}; plot saved to: {plot_file}")
    if no_show:
        plt.close(fig)


def main(run_dir=None, no_show=False, run_id=None):
    run_dir = resolve_run(RUN_DIR if run_dir is None and run_id is None else run_dir, run_id)
    ready_data_dir = run_dir / "Ready_data"
    ready_data_dir.mkdir(exist_ok=True)
    response = load_normalized_response(run_dir / "regulation_tracking.csv")
    if PLOT_POINTS is not None:
        response = response.tail(PLOT_POINTS)
    response.to_csv(ready_data_dir / f"{run_dir.name}_normalized_response.csv", index=False)
    if no_show:
        plt.switch_backend("Agg")

    windows = select_hour_windows(response)
    # Use the same symmetric scale for both hours for a fair visual comparison.
    y_limit = 1.1 * max(
        1.0,
        *(float(window[column].abs().max())
          for window, _ in windows.values()
          for column in ("normalized_actual_response", "Regulation Signal")),
    )
    for kind, (window, rmse) in windows.items():
        prefix = ready_data_dir / f"{run_dir.name}_{kind}_hour"
        window.to_csv(f"{prefix}_normalized_response.csv", index=False)
        plot_hour(window, kind, rmse, f"{prefix}_normalized_power_plot.pdf",
                  y_limit, no_show)
    if not no_show:
        plt.show()
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run-dir", type=Path)
    group.add_argument("--run-id", help="Folder name under Combo/Results")
    parser.add_argument("--no-show", action="store_true")
    args = parser.parse_args()
    main(args.run_dir, args.no_show, args.run_id)
