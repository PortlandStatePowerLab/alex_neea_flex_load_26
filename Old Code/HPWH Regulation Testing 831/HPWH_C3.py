"""
Author: Alex Wardwell
Created: 8/12/26

Plot requested and actual HPWH regulation response on one normalized axis.
Run the B2 baseline and B3 controlled simulations first. C3 reads B3's fleet-state
log and divides the actual controlled-minus-baseline fleet power by the
recorded static regulation capacity. Thus, for example, 15 kW of response
against 20 kW of capacity is plotted as 0.75.

@modified by: 
@modified date: 
"""

import argparse
import os

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


script_dir = os.path.dirname(os.path.abspath(__file__))
PLOT_POINTS = 1440


def load_normalized_response(vpp_log_file):
    """Load aligned regulation request and capacity-normalized fleet response."""
    data = pd.read_csv(vpp_log_file, parse_dates=["Time"])
    required_columns = {
        "Time",
        "Regulation Signal",
        "Up Regulation Capacity (kW)",
        "Down Regulation Capacity (kW)",
        "Actual HPWH Delta (kW)",
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
        "Actual HPWH Delta (kW)",
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
        data["Actual HPWH Delta (kW)"]
        / data["normalization_capacity_kw"]
    )

    return data.sort_values("Time")


def main(run_id):
    ready_data_dir = os.path.join(script_dir, "Ready_data", run_id)
    vpp_log_file = os.path.join(script_dir, f"{run_id}_VPP_Fleet_States.csv")
    plot_file = os.path.join(
        ready_data_dir, f"{run_id}_normalized_power_plot.png"
    )

    if not os.path.isfile(vpp_log_file):
        raise FileNotFoundError(
            f"Missing C3 input file: {vpp_log_file}\n"
            "Run HPWH_B2 and HPWH_B3 with the same run ID before C3."
        )

    response = load_normalized_response(vpp_log_file).tail(PLOT_POINTS)
    os.makedirs(ready_data_dir, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        response["Time"][-PLOT_POINTS:],
        response["normalized_actual_response"][-PLOT_POINTS:],
        label="(controlled - baseline) / regulation capacity",
        color="green",
    )
    ax.plot(
        response["Time"][-PLOT_POINTS:],
        response["Regulation Signal"][-PLOT_POINTS:],
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

    ax.set_title("Normalized HPWH Fleet Regulation Response")
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
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    main(parser.parse_args().run_id)
