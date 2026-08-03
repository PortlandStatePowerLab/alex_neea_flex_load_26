"""Plot controlled power normalized by baseline power.

Run AC_C1_parse_OCHRE_data_final.py and AC_C2_Plot_Totpower_WHpower.py
first.  This script reads the same AC-power CSVs as C2, then writes a
separate normalized-power plot without overwriting C2's plots.
"""

import os

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


# Must match ``filename`` in AC_B2_EnergySched_LoadShaping.
INPUT_FILE_ROOT = "AC_Test_PID_1.0_0.8_1.0"
MIN_BASELINE_KW = 0.01
PLOT_POINTS = 2000

script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(fl_dir)
ready_data_dir = os.path.join(working_dir, "Ready_data", INPUT_FILE_ROOT)

baseline_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_baseline_AC_power.csv"
)
controlled_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_controlled_AC_power.csv"
)
reg_sig_file = os.path.join(working_dir, "RegA Signal", "rega_filtered.csv")
plot_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_normalized_power_plot.png"
)


def average_power_by_time(csv_file, column_name):
    """Return the per-home average power with a usable time column."""
    data = pd.read_csv(csv_file, index_col=0)
    average = data.mean(axis=0, numeric_only=True)
    result = average.rename(column_name).rename_axis("Time").reset_index()
    result["Time"] = pd.to_datetime(result["Time"])
    return result


def load_regulation_signal():
    """Load the one-day signal segment corresponding to C2's plot."""
    signal = pd.read_csv(reg_sig_file, parse_dates=["Timestamp"])
    signal = signal.rename(columns={"Timestamp": "Time", "Signal": "signal"})
    signal_date = signal["Time"].dt.normalize().iloc[-1]
    signal = signal[signal["Time"].dt.normalize() == signal_date].copy()
    return signal[["Time", "signal"]]


def main():
    for required_file in (baseline_file, controlled_file, reg_sig_file):
        if not os.path.isfile(required_file):
            raise FileNotFoundError(
                f"Required input was not found: {required_file}\n"
                "Run C1 and C2 with the same INPUT_FILE_ROOT before C3."
            )

    baseline = average_power_by_time(baseline_file, "baseline_kw")
    controlled = average_power_by_time(controlled_file, "controlled_kw")
    global power
    power = baseline.merge(controlled, on="Time", how="inner")

    # A ratio is undefined when the baseline fleet is off.  Keep those
    # points as NaN so Matplotlib leaves a gap rather than plotting a spike.
    
    power["controlled_minus_baseline"] = power["controlled_kw"] - power["baseline_kw"]

    global signal
    signal = load_regulation_signal()

    # C2 compares only clock time, so do the same for an aligned overlay.
    for frame in (power, signal):
        frame["Time"] = pd.to_datetime(
            frame["Time"].dt.strftime("1900-01-01 %H:%M:%S")
        )

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        power["Time"].tail(PLOT_POINTS),
        power["controlled_minus_baseline"].tail(PLOT_POINTS),
        label="controlled - baseline power",
        color="green",
    )
    # ax.axhline(1.0, color="black", linewidth=1, alpha=0.6, label="baseline ratio")
    ax.set_title("Normalized Average Cooling Power per Household")
    ax.set_xlabel("Time")
    ax.set_ylabel("Controlled - Baseline Power")

    ax2 = ax.twinx()
    ax2.plot(
        signal["Time"].tail(PLOT_POINTS),
        signal["signal"].tail(PLOT_POINTS),
        label="regulation signal",
        color="mediumorchid",
        linestyle=":",
    )
    ax2.set_ylabel("Normalized Regulation Signal")
    ax2.set_ylim(-1.1, 1.1)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    fig.autofmt_xdate()
    fig.savefig(plot_file, dpi=300, bbox_inches="tight")

    calculate_correlation()
    plt.show()


def calculate_correlation():
    merged = power.merge(signal, on="Time", how="inner")
    correlation = merged["controlled_minus_baseline"].tail(len(merged) // 2).corr(merged["signal"].tail(len(merged) // 2))
    print(f"Correlation between controlled-baseline power and regulation signal: {correlation:.4f}")
    return correlation

if __name__ == "__main__":
    main()
    # calculate_correlation()
