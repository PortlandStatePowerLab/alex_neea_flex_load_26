"""Display B2 controlled averages, following the metrics plotted by C1/C2.

Run this file directly to use the latest completed run in Combo/Results.
Optional: python Combo/C0_Plot_Controlled.py --run-dir Combo/Results/<run_id>
Use --no-show to save plots without opening windows.
Requires pandas and matplotlib; does not import or rerun the simulation.
"""

import argparse
import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


RESULTS_DIR = Path(__file__).resolve().parent / "Results"
# Set to a specific run folder, or leave as None to select the latest complete run.
RUN_DIR = None

METRICS = {
    "Total Electric Power (kW)": "Total household power",
    "Water Heating Electric Power (kW)": "Water heating",
    "HVAC Cooling Electric Power (kW)": "HVAC cooling",
    "HVAC Heating Electric Power (kW)": "HVAC heating",
    "Clothes Dryer Electric Power (kW)": "Clothes dryer",
    "EV Electric Power (kW)": "EV power",
    "Battery Electric Power (kW)": "Battery power",
    "EV SOC (-)": "EV state of charge",
    "Battery SOC (-)": "Battery state of charge",
}


def select_run(run_dir=None):
    try:
        from .C1_parse_OCHRE_data_final import select_run as select_controlled
    except ImportError:
        from C1_parse_OCHRE_data_final import select_run as select_controlled
    return select_controlled(run_dir)


def load_averages(run_dir):
    """Average each metric over homes reporting it, retaining full timestamps."""
    frame = pd.read_csv(
        run_dir / "controlled.csv",
        usecols=lambda name: name in {"Time", "Home", *METRICS},
        dtype={"Home": str},
    )
    required = {"Time", "Home", "Total Electric Power (kW)"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"controlled.csv is missing required columns: {sorted(missing)}")
    if frame.empty or frame[["Time", "Home"]].isna().any().any():
        raise ValueError("controlled.csv has no results or contains missing Time/Home values.")
    frame["Time"] = pd.to_datetime(frame["Time"], errors="raise")
    if frame.duplicated(["Time", "Home"]).any():
        raise ValueError("controlled.csv contains duplicate Time/Home rows.")
    metrics = [name for name in METRICS if name in frame]
    frame[metrics] = frame[metrics].apply(pd.to_numeric, errors="raise")
    if np.isinf(frame[metrics].to_numpy()).any():
        raise ValueError("controlled.csv contains infinite metric values.")
    # Missing device values must not discard otherwise valid household rows.
    metrics = [name for name in metrics if frame[name].notna().any()]
    if "Total Electric Power (kW)" not in metrics:
        raise ValueError("controlled.csv contains no total household power values.")
    grouped = frame.groupby("Time", sort=True)
    averages = grouped[metrics].mean()
    counts = grouped[metrics].count()
    print(f"Loaded {frame['Home'].nunique()} homes and {len(averages)} timestamps.")
    print("Averages use homes with recorded values for each metric (including zeros).")
    if (counts.nunique() > 1).any():
        print("WARNING: Reporting-home counts vary over time; see C0_controlled_reporting_homes.csv.")
    return averages, counts


def plot_averages(averages, run_id):
    """Keep figures open until main calls show, unlike C2's save/close loop."""
    columns = list(averages.columns)
    rows = (len(columns) + 2) // 3
    fig, axes = plt.subplots(rows, 3, figsize=(16, 3.4 * rows), squeeze=False,
                             constrained_layout=True)
    fig.suptitle(f"B2 controlled - average per reporting home\n{run_id}", fontsize=15)
    for ax, column in zip(axes.flat, columns):
        is_soc = "SOC" in column
        values = averages[column] * (100 if is_soc else 1)
        ax.plot(averages.index, values, color="#004C6D", linewidth=1.5)
        ax.set_title(METRICS[column])
        ax.set_ylabel("State of charge (%)" if is_soc else "Power (kW/home)")
        locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.grid(True, alpha=0.3)
        if is_soc:
            ax.set_ylim(0, 100)
    for ax in list(axes.flat)[len(columns):]:
        ax.set_visible(False)
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR,
                        help="B2 result folder; default: latest completed run")
    parser.add_argument("--no-show", action="store_true", help="Save without opening plots")
    args = parser.parse_args()
    if args.no_show:
        plt.switch_backend("Agg")
    run_dir = select_run(args.run_dir)
    print(f"Controlled run: {run_dir}")
    averages, counts = load_averages(run_dir)
    output_dir = run_dir / "C0_Plots"
    output_dir.mkdir(exist_ok=True)
    averages.to_csv(output_dir / "C0_controlled_averages.csv")
    counts.to_csv(output_dir / "C0_controlled_reporting_homes.csv")
    fig = plot_averages(averages, run_dir.name)
    fig.savefig(output_dir / "C0_controlled_overview.png", dpi=180)
    print(f"Plots and averages saved to: {output_dir}")
    if args.no_show:
        plt.close(fig)
    else:
        plt.show()


if __name__ == "__main__":
    main()

