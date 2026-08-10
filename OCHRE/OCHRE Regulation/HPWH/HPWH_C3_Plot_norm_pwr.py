"""Plot the HPWH fleet's controlled-minus-baseline power response.

Run HPWH_C1_parse_OCHRE_data_final.py first. C3 uses C1's water-heating
power CSVs; it also accepts the same files after C2 has appended its average
row. The resulting plot is saved beside the C1/C2 outputs.
"""

import os

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


# Must match ``filename`` in HPWH_B2_EnergySched_LoadShaping.py.
INPUT_FILE_ROOT = "2025_All_630_1_45_1700_1_45_OS"
PLOT_POINTS = 1000

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(project_dir)
ready_data_dir = os.path.join(project_dir, "Ready_data", INPUT_FILE_ROOT)

baseline_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_baseline_WH_power.csv"
)
controlled_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_controlled_WH_power.csv"
)
reg_sig_file = os.path.join(working_dir, "RegA Signal", "rega_filtered.csv")
plot_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_normalized_power_plot.png"
)


def average_power_by_time(csv_file, column_name):
    """Return mean HPWH power by clock time from a C1/C2 output CSV."""
    data = pd.read_csv(csv_file, index_col=0)
    numeric_data = data.apply(pd.to_numeric, errors="coerce")

    # C2 appends its per-column average as a final row with an empty Home
    # value. Reuse that row when present so C3 exactly matches C2's average.
    if data.index.isna().any():
        average = numeric_data.loc[data.index.isna()].iloc[-1]
    else:
        average = numeric_data.mean(axis=0)

    result = average.rename(column_name).rename_axis("Time").reset_index()
    result["Time"] = pd.to_datetime(result["Time"], format="%H:%M", errors="coerce")
    result = result.dropna(subset=["Time", column_name])
    if result.empty:
        raise ValueError(
            f"No usable HH:MM power columns were found in: {csv_file}"
        )
    return result


def load_regulation_signal():
    """Load the first one-day signal segment, matching C2's plot."""
    signal = pd.read_csv(reg_sig_file, parse_dates=["Timestamp"])
    required_columns = {"Timestamp", "Signal"}
    if not required_columns.issubset(signal.columns):
        raise ValueError(
            f"{reg_sig_file} must contain Timestamp and Signal columns."
        )

    signal = signal.rename(columns={"Timestamp": "Time", "Signal": "signal"})
    signal = signal.dropna(subset=["Time", "signal"])
    if signal.empty:
        raise ValueError(f"No usable regulation-signal rows were found in: {reg_sig_file}")

    signal_date = signal["Time"].dt.normalize().iloc[0]
    return signal[signal["Time"].dt.normalize() == signal_date][["Time", "signal"]].copy()


def calculate_correlation(power, signal):
    """Print and return the response-to-signal correlation for plotted points."""
    merged = power.merge(signal, on="Time", how="inner")
    if len(merged) < 2:
        print("Correlation unavailable: fewer than two aligned power/signal points.")
        return float("nan")

    correlation = merged["controlled_minus_baseline"].corr(merged["signal"])
    print(
        "Correlation between controlled-baseline power and regulation signal: "
        f"{correlation:.4f}"
    )
    return correlation


def main():
    missing_files = [
        file for file in (baseline_file, controlled_file, reg_sig_file)
        if not os.path.isfile(file)
    ]
    if missing_files:
        raise FileNotFoundError(
            "C3 cannot plot because these required files are missing:\n- "
            + "\n- ".join(missing_files)
            + "\nRun HPWH_C1 with the same INPUT_FILE_ROOT, then run C3."
        )

    baseline = average_power_by_time(baseline_file, "baseline_kw")
    controlled = average_power_by_time(controlled_file, "controlled_kw")
    power = baseline.merge(controlled, on="Time", how="inner")
    if power.empty:
        raise ValueError("Baseline and controlled HPWH files have no matching clock times.")
    power["controlled_minus_baseline"] = (
        power["controlled_kw"] - power["baseline_kw"]
    )

    signal = load_regulation_signal()

    # C1 uses clock-time columns, while the signal has complete timestamps.
    # Put both on an arbitrary common day before plotting and correlating.
    for frame in (power, signal):
        frame["Time"] = pd.to_datetime(
            frame["Time"].dt.strftime("1900-01-01 %H:%M:%S")
        )

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        power["Time"].tail(PLOT_POINTS),
        power["controlled_minus_baseline"].tail(PLOT_POINTS),
        label="controlled - baseline HPWH power",
        color="green",
    )
    ax.axhline(0.0, color="black", linewidth=1, alpha=0.6)
    ax.set_title("Average Water-Heating Power Response per Household")
    ax.set_xlabel("Time")
    ax.set_ylabel("Controlled - Baseline Power (kW)")

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

    calculate_correlation(power, signal)
    plt.show()


if __name__ == "__main__":
    main()
