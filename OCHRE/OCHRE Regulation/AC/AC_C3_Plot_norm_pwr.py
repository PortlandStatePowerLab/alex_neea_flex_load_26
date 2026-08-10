"""Plot the fleet regulation request and response on one shared kW axis.

Run AC_B2_EnergySched_LoadShaping.py first.  This script reads B2's VPP
fleet-state log and writes a separate response plot without overwriting C2's
plots.
"""

import os

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


# Must match ``filename`` in AC_B2_EnergySched_LoadShaping.
INPUT_FILE_ROOT = "AC_Test_PID_1.0_0.8_1.0"
PLOT_POINTS = 1000

script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(fl_dir)
ready_data_dir = os.path.join(working_dir, "Ready_data", INPUT_FILE_ROOT)

fleet_state_file = os.path.join(
    working_dir, f"{INPUT_FILE_ROOT}_VPP_Fleet_States.csv"
)
plot_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_normalized_power_plot.png"
)


def load_fleet_response():
    """Return requested and actual controlled-minus-baseline fleet power in kW."""
    data = pd.read_csv(fleet_state_file, parse_dates=["Time"])
    response = data[["Time", "Target Delta (kW)", "Actual Delta (kW)"]].copy()
    return response.rename(
        columns={
            "Target Delta (kW)": "requested_delta_kw",
            "Actual Delta (kW)": "controlled_minus_baseline_kw",
        }
    )


def calculate_correlation(response):
    """Return correlation between the requested and actual regulation power."""
    correlation = response["controlled_minus_baseline_kw"].corr(
        response["requested_delta_kw"]
    )
    print(f"Correlation between actual and requested regulation power: {correlation:.4f}")
    return correlation


def main():
    if not os.path.isfile(fleet_state_file):
        raise FileNotFoundError(
            f"Required input was not found: {fleet_state_file}\n"
            "Run B2 with the same INPUT_FILE_ROOT before C3."
        )

    response = load_fleet_response()

    # Plot the final simulation day, matching C2's one-day view.
    plot_date = response["Time"].dt.normalize().iloc[-1]
    response = response[response["Time"].dt.normalize() == plot_date].copy()
    response["Time"] = pd.to_datetime(
        response["Time"].dt.strftime("1900-01-01 %H:%M:%S")
    )

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        response["Time"].tail(PLOT_POINTS),
        response["controlled_minus_baseline_kw"].tail(PLOT_POINTS),
        label="controlled - baseline (actual)",
        color="green",
    )
    ax.plot(
        response["Time"].tail(PLOT_POINTS),
        response["requested_delta_kw"].tail(PLOT_POINTS),
        label="regulation request",
        color="mediumorchid",
        linestyle=":",
    )
    ax.axhline(0.0, color="black", linewidth=1, alpha=0.6)
    ax.set_title("Fleet Regulation Response")
    ax.set_xlabel("Time")
    ax.set_ylabel("Change from baseline (kW)")
    ax.legend(loc="upper right")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    fig.autofmt_xdate()
    fig.savefig(plot_file, dpi=300, bbox_inches="tight")

    calculate_correlation(response)
    plt.show()


if __name__ == "__main__":
    main()
