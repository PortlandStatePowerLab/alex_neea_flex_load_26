"""
Author: Alex Wardwell
Created: 8/12/26

Plot requested and actual Combo regulation response on one normalized axis.
Run B1_Baseline and B2_Regulation first. C3 reads B2's regulation tracking
log and divides the actual controlled-minus-baseline fleet power by the
recorded static regulation capacity. Thus, for example, 15 kW of response
against 20 kW of capacity is plotted as 0.75.
Adapted from HPWH Regulation Testing 831/HPWH_C3.py.
Run directly for the latest completed B1/B2 pair, or pass --run-dir / --run-id.
Use --no-show to save without opening a window. Outputs go to Ready_data
inside the selected run. C1 and C2 do not need to be run first.

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


def main(run_dir=None, no_show=False, run_id=None):
    run_dir = resolve_run(RUN_DIR if run_dir is None and run_id is None else run_dir, run_id)
    ready_data_dir = run_dir / "Ready_data"
    ready_data_dir.mkdir(exist_ok=True)
    plot_file = ready_data_dir / f"{run_dir.name}_normalized_power_plot.png"
    response = load_normalized_response(run_dir / "regulation_tracking.csv")
    if PLOT_POINTS is not None:
        response = response.tail(PLOT_POINTS)
    response.to_csv(ready_data_dir / f"{run_dir.name}_normalized_response.csv", index=False)
    if no_show:
        plt.switch_backend("Agg")

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        response["Time"],
        response["normalized_actual_response"],
        label="(controlled - baseline) / regulation capacity",
        color="green",
    )
    ax.plot(
        response["Time"],
        response["Regulation Signal"],
        label="regulation signal",
        color="mediumorchid",
        linestyle=":",
    )
    ax.axhline(0.0, color="black", linewidth=1, alpha=0.6)

    # Use one shared, symmetric axis so zero is exactly in the graph's middle.
    plotted_limit = max(
        1.0,
        response["normalized_actual_response"].abs().max(),
        response["Regulation Signal"].abs().max(),
    )
    y_limit = 1.1 * plotted_limit
    ax.set_ylim(-y_limit, y_limit)

    ax.set_title("Normalized Combo Fleet Regulation Response")
    ax.set_xlabel("Time")
    ax.set_ylabel("Fraction of Static Regulation Capacity")
    ax.legend(loc="upper right")
    time_locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(time_locator)
    ax.xaxis.set_major_formatter(
        mdates.ConciseDateFormatter(time_locator)
    )
    fig.autofmt_xdate()
    fig.savefig(plot_file, dpi=300, bbox_inches="tight")
    print(f"Normalized response plot saved to: {plot_file}")
    if no_show:
        plt.close(fig)
    else:
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
