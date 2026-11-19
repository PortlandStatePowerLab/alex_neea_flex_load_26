"""
Author: Alex Wardwell
Created: 8/12/26

Plot requested and actual Combo regulation response on one normalized axis.
Run B1_Baseline and B2_Regulation first. C5 reads B2's regulation tracking
log and divides the actual controlled-minus-baseline fleet power by the
recorded static regulation capacity. Thus, for example, 15 kW of response
against 20 kW of capacity is plotted as 0.75.
Adapted from HPWH Regulation Testing 831/HPWH_C3.py.
Run directly for the latest completed B1/B2 pair, or pass --run-dir / --run-id.
Use --no-show to save the PNG plot without opening a window. Outputs go to Ready_data
inside the selected run. C1 and C2 do not need to be run first.
Plots show only the regulation period selected by F1, using B2's saved
regulation window. No best/worst-hour selection is performed.

@modified by: 
@modified date: 
"""

import argparse
import json
from pathlib import Path
import numpy as np

try:
    from .C3_Normalized_Regulation import resolve_run, load_tracking, load_normalized_response
except ImportError:
    from C3_Normalized_Regulation import resolve_run, load_tracking, load_normalized_response

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


RUN_DIR = None  # Default: latest completed B1/B2 pair.


def plot_period(response, start, end, rmse, plot_file, y_limit, no_show):
    """Save the selected regulation period with both normalized curves."""
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(response["Time"], response["normalized_actual_response"],
            label="(controlled - baseline) / regulation capacity", color="green")
    ax.plot(response["Time"], response["normalized_target_response"],
            label="dispatched target / regulation capacity", color="mediumorchid", linestyle="--")
    ax.axhline(0.0, color="black", linewidth=1, alpha=0.6)
    ax.set_ylim(-y_limit, y_limit)
    ax.set_xlim(start, end)
    ax.set_title(f"Normalized Regulation Response\n(RMSE = {rmse:.4f})",
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
    fig.savefig(plot_file, dpi=150)
    print(f"Regulation period: {start} to {end} (end exclusive); "
          f"normalized RMSE={rmse:.6f}; plot saved to: {plot_file}")
    if no_show:
        plt.close(fig)


def main(run_dir=None, no_show=False, run_id=None):
    """Return the normalized response and the path of the saved PNG."""
    run_dir = resolve_run(RUN_DIR if run_dir is None and run_id is None else run_dir, run_id)
    ready_data_dir = run_dir / "Ready_data"
    ready_data_dir.mkdir(exist_ok=True)
    response = load_normalized_response(run_dir / "regulation_tracking.csv")
    manifest = json.loads(
        (run_dir / "regulation_manifest.json").read_text(encoding="utf-8")
    )
    # Older runs without window metadata already contain only reporting samples.
    start = pd.Timestamp(manifest.get("regulation_start", response["Time"].iloc[0]))
    end_value = manifest.get("regulation_end_exclusive")
    if end_value is None:
        steps = response["Time"].diff().dropna()
        step = steps.median() if not steps.empty else pd.Timedelta(minutes=1)
        end = response["Time"].iloc[-1] + step
    else:
        end = pd.Timestamp(end_value)
    if end <= start:
        raise ValueError("Regulation window end must be after its start.")
    response = response.loc[
        (response["Time"] >= start) & (response["Time"] < end)
    ].copy()
    if response.empty:
        raise ValueError("No tracking samples fall inside the selected regulation period.")
    prefix = ready_data_dir.resolve() / run_dir.name
    response.to_csv(f"{prefix}_normalized_response.csv", index=False)
    if no_show:
        plt.switch_backend("Agg")
    rmse = float(np.sqrt(np.mean(
        (response["normalized_actual_response"] - response["normalized_target_response"]) ** 2
    )))
    y_limit = 1.1 * max(
        1.0,
        *(float(response[column].abs().max())
          for column in ("normalized_actual_response", "normalized_target_response")),
    )
    plot_path = Path(f"{prefix}_normalized_power_plot.png")
    plot_period(response, start, end, rmse, plot_path, y_limit, no_show)
    if not no_show:
        plt.show()
    return response, plot_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run-dir", type=Path)
    group.add_argument("--run-id", help="Folder name under Combo/Results")
    parser.add_argument("--no-show", action="store_true")
    args = parser.parse_args()
    main(args.run_dir, args.no_show, args.run_id)
