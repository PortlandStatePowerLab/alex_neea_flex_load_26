"""
C4: Diagnose HPWH regulation-signal tracking and correlation.

Run HPWH_B2_EnergySched_LoadShaping.py first.

C4 primarily uses B2's *_VPP_Fleet_States.csv because it contains the
requested regulation target and the actual HPWH fleet response at every
simulation timestep. If that file is unavailable, C4 falls back to the
baseline/controlled HPWH power files used by C3.

Diagnostics:
    1. Zero-lag Pearson correlation.
    2. Pearson correlation over a configurable lag range.
    3. Best correlation and corresponding lag.
    4. Normalized target-vs-actual response metrics.
    5. Tracking-error statistics when the B2 VPP log is available.
    6. Diagnostic plots for target/actual response and correlation vs lag.
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# ---------------------------------------------------------------------------
# USER SETTINGS
# ---------------------------------------------------------------------------

# Must match ``filename`` in HPWH_B2_EnergySched_LoadShaping.py.
INPUT_FILE_ROOT = "2025_All_630_1_45_1700_1_45_OS"

# Search this many minutes in both directions for the best lag.
MAX_LAG_MINUTES = 30

# Set True to display plots after saving them.
SHOW_PLOTS = True


# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(project_dir)

ready_data_dir = os.path.join(project_dir, "Ready_data", INPUT_FILE_ROOT)

vpp_log_file = os.path.join(
    project_dir,
    f"{INPUT_FILE_ROOT}_VPP_Fleet_States.csv",
)

# B2 writes its VPP log to WORKING_DIR, which is two levels above the
# script directory in the existing project structure. Check both locations.
vpp_log_candidates = [
    vpp_log_file,
    os.path.join(working_dir, f"{INPUT_FILE_ROOT}_VPP_Fleet_States.csv"),
]

baseline_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_baseline_WH_power.csv"
)
controlled_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_controlled_WH_power.csv"
)

plot_response_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_C4_response_diagnostic.png"
)
plot_lag_file = os.path.join(
    ready_data_dir, f"{INPUT_FILE_ROOT}_C4_correlation_vs_lag.png"
)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def find_vpp_log():
    """Return the first existing B2 VPP log path."""
    for path in vpp_log_candidates:
        if os.path.isfile(path):
            return path
    return None


def correlation_at_lag(target, actual, lag_steps):
    """
    Calculate Pearson correlation after shifting the target relative to actual.

    Positive lag means the actual response is compared with an earlier target:
        actual(t) vs target(t - lag)

    This corresponds to a response that occurs approximately ``lag`` minutes
    after the regulation command.
    """
    pair = pd.concat(
        [
            target.rename("target"),
            actual.rename("actual"),
        ],
        axis=1,
    )

    if lag_steps > 0:
        pair = pair.iloc[lag_steps:].copy()
        pair["target"] = target.iloc[:-lag_steps].to_numpy()
    elif lag_steps < 0:
        n = abs(lag_steps)
        pair = pair.iloc[:-n].copy()
        pair["target"] = target.iloc[n:].to_numpy()

    pair = pair.dropna()

    if len(pair) < 2:
        return np.nan

    if pair["target"].std() == 0 or pair["actual"].std() == 0:
        return np.nan

    return pair["target"].corr(pair["actual"])

def lag_scan(target, actual, timestep_minutes):
    """Calculate correlation across the configured lag range."""
    max_steps = max(1, int(round(MAX_LAG_MINUTES / timestep_minutes)))

    rows = []
    for lag_steps in range(-max_steps, max_steps + 1):
        corr = correlation_at_lag(target, actual, lag_steps)
        rows.append(
            {
                "lag_steps": lag_steps,
                "lag_minutes": lag_steps * timestep_minutes,
                "correlation": corr,
            }
        )

    return pd.DataFrame(rows)


def print_metrics(target, actual, timestep_minutes, source_name,
                  tracking_error=None):
    """Print the correlation and response diagnostics."""
    zero_lag = correlation_at_lag(target, actual, 0)

    lag_results = lag_scan(target, actual, timestep_minutes)
    valid = lag_results.dropna(subset=["correlation"])

    if valid.empty:
        best_corr = np.nan
        best_lag = np.nan
    else:
        # We want the strongest positive tracking relationship.
        best_row = valid.loc[valid["correlation"].idxmax()]
        best_corr = best_row["correlation"]
        best_lag = best_row["lag_minutes"]

    target_std = target.std()
    actual_std = actual.std()

    if target_std > 0:
        response_gain = actual.std() / target_std
    else:
        response_gain = np.nan

    # Least-squares slope through the origin. This is useful for seeing
    # whether the actual response has the expected magnitude even when
    # correlation is imperfect.
    denominator = float((target ** 2).sum())
    if denominator > 0:
        gain = float((target * actual).sum() / denominator)
    else:
        gain = np.nan

    rmse = float(np.sqrt(np.mean((actual - target) ** 2)))

    print("\n" + "=" * 65)
    print("C4 REGULATION TRACKING DIAGNOSTICS")
    print("=" * 65)
    print(f"Data source:                 {source_name}")
    print(f"Timestep:                    {timestep_minutes:g} min")
    print(f"Zero-lag correlation:        {zero_lag:.4f}")
    print(f"Best correlation:             {best_corr:.4f}")
    print(f"Lag of best correlation:     {best_lag:g} min")
    print(f"Actual/target RMS ratio:     {response_gain:.4f}")
    print(f"Through-origin response gain:{gain:.4f}")
    print(f"Target-vs-actual RMSE:        {rmse:.4f}")

    if tracking_error is not None:
        tracking_error = tracking_error.dropna()
        if not tracking_error.empty:
            print(f"Mean absolute tracking error: {tracking_error.abs().mean():.4f} kW")
            print(f"RMSE tracking error:           "
                  f"{np.sqrt(np.mean(tracking_error ** 2)):.4f} kW")

    print("=" * 65)

    print("\nInterpretation:")
    print(
        "  Zero-lag correlation measures whether the HPWH response follows "
        "the signal at the same timestamp."
    )
    print(
        "  The best-lag correlation checks whether the response follows the "
        "signal after a time delay."
    )
    print(
        "  A substantially higher best-lag correlation would indicate that "
        "thermal/control response delay is a major contributor to the low "
        "zero-lag correlation."
    )

    return lag_results


# ---------------------------------------------------------------------------
# PRIMARY DATA SOURCE: B2 VPP FLEET LOG
# ---------------------------------------------------------------------------

def load_vpp_data(path):
    """Load and prepare the B2 VPP state log."""
    df = pd.read_csv(path)

    required = {
        "Time",
        "Target Delta (kW)",
        "Actual HPWH Delta (kW)",
        "Tracking Error (kW)",
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"VPP log is missing required columns: {sorted(missing)}"

        )

    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df = df.dropna(
        subset=["Time", "Target Delta (kW)", "Actual HPWH Delta (kW)"]
    ).copy()

    df = df.sort_values("Time")
    df = df.drop_duplicates(subset="Time")

    # Infer the actual simulation timestep from timestamps.
    diffs = df["Time"].diff().dt.total_seconds().dropna() / 60.0
    timestep_minutes = diffs.median()

    if not np.isfinite(timestep_minutes) or timestep_minutes <= 0:
        timestep_minutes = 1.0

    return df, float(timestep_minutes)


# ---------------------------------------------------------------------------
# FALLBACK: C3-STYLE BASELINE / CONTROLLED DATA
# ---------------------------------------------------------------------------

def average_power_by_time(csv_file, column_name):
    """Return mean power by clock time from a C1/C2 output CSV."""
    data = pd.read_csv(csv_file, index_col=0)
    numeric_data = data.apply(pd.to_numeric, errors="coerce")

    # C2 appends an average row with an empty Home index.
    if data.index.isna().any():
        average = numeric_data.loc[data.index.isna()].iloc[-1]
    else:
        average = numeric_data.mean(axis=0)

    result = (
        average.rename(column_name)
        .rename_axis("Time")
        .reset_index()
    )

    result["Time"] = pd.to_datetime(
        result["Time"],
        format="%H:%M",
        errors="coerce",
    )
    result = result.dropna(subset=["Time", column_name])

    if result.empty:
        raise ValueError(f"No usable time columns found in {csv_file}")

    return result


def load_fallback_power():
    """Load C3-style controlled-minus-baseline HPWH response."""
    if not os.path.isfile(baseline_file):
        raise FileNotFoundError(baseline_file)

    if not os.path.isfile(controlled_file):
        raise FileNotFoundError(controlled_file)

    baseline = average_power_by_time(
        baseline_file,
        "baseline_kw",
    )
    controlled = average_power_by_time(
        controlled_file,
        "controlled_kw",
    )

    power = baseline.merge(
        controlled,
        on="Time",
        how="inner",
    )

    if power.empty:
        raise ValueError(
            "Baseline and controlled files have no matching clock times."
        )

    power["actual_delta_kw"] = (
        power["controlled_kw"] - power["baseline_kw"]
    )

    # Put clock-time data onto an arbitrary common day.
    power["Time"] = pd.to_datetime(
        power["Time"].dt.strftime("1900-01-01 %H:%M:%S")
    )

    return power


def load_signal_for_fallback():
    """Load the first day of the filtered regulation signal."""
    signal_file = os.path.join(
        working_dir,
        "RegA Signal",
        "rega_filtered.csv",
    )

    if not os.path.isfile(signal_file):
        raise FileNotFoundError(signal_file)

    signal = pd.read_csv(
        signal_file,
        parse_dates=["Timestamp"],
    )

    signal = signal.rename(
        columns={
            "Timestamp": "Time",
            "Signal": "signal",
        }
    )

    signal = signal.dropna(subset=["Time", "signal"])

    if signal.empty:
        raise ValueError("No usable regulation signal rows found.")

    signal_date = signal["Time"].dt.normalize().iloc[0]

    signal = signal[
        signal["Time"].dt.normalize() == signal_date
    ].copy()

    signal["Time"] = pd.to_datetime(
        signal["Time"].dt.strftime("1900-01-01 %H:%M:%S")
    )

    return signal[["Time", "signal"]]


# ---------------------------------------------------------------------------
# PLOTS
# ---------------------------------------------------------------------------

def plot_vpp_response(df):
    """Plot target and actual HPWH response from the B2 VPP log."""
    fig, ax = plt.subplots(figsize=(10, 5))

    ax.plot(
        df["Time"],
        df["Target Delta (kW)"],
        label="target HPWH delta",
    )
    ax.plot(
        df["Time"],
        df["Actual HPWH Delta (kW)"],
        label="actual HPWH delta",
        linestyle="--",
    )

    ax.axhline(0.0, linewidth=1)
    ax.set_title("HPWH Regulation Target vs Actual Response")
    ax.set_xlabel("Time")
    ax.set_ylabel("Power Difference (kW)")
    ax.legend()

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    fig.autofmt_xdate()

    fig.savefig(
        plot_response_file,
        dpi=300,
        bbox_inches="tight",
    )

    return fig


def plot_lag_correlation(lag_results):
    """Plot correlation as a function of response lag."""
    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(
        lag_results["lag_minutes"],
        lag_results["correlation"],
        marker="o",
        markersize=3,
    )

    valid = lag_results.dropna(subset=["correlation"])
    if not valid.empty:
        best = valid.loc[valid["correlation"].idxmax()]
        ax.axvline(
            best["lag_minutes"],
            linestyle="--",
            linewidth=1,
            label=(
                f"Best lag = {best['lag_minutes']:g} min, "
                f"r = {best['correlation']:.3f}"
            ),
        )

    ax.axhline(0.0, linewidth=1)
    ax.set_title("HPWH Response Correlation vs Signal Lag")
    ax.set_xlabel("Response Lag (minutes)")
    ax.set_ylabel("Pearson Correlation")
    ax.grid(True, alpha=0.25)
    ax.legend()

    fig.savefig(
        plot_lag_file,
        dpi=300,
        bbox_inches="tight",
    )

    return fig


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    os.makedirs(ready_data_dir, exist_ok=True)

    vpp_path = find_vpp_log()

    if vpp_path is not None:
        print(f"Using B2 VPP fleet log:\n  {vpp_path}")

        df, timestep_minutes = load_vpp_data(vpp_path)

        target = df["Target Delta (kW)"]
        actual = df["Actual HPWH Delta (kW)"]
        tracking_error = df["Tracking Error (kW)"]

        lag_results = print_metrics(
            target,
            actual,
            timestep_minutes,
            source_name="B2 VPP Fleet States",
            tracking_error=tracking_error,
        )

        plot_vpp_response(df)

    else:
        print("B2 VPP fleet log not found.")
        print("Falling back to C3 baseline/controlled power data.")

        power = load_fallback_power()
        signal = load_signal_for_fallback()

        merged = power.merge(
            signal,
            on="Time",
            how="inner",
        )

        if len(merged) < 2:
            raise ValueError(
                "Fewer than two aligned power/signal points were found."
            )

        timestep_minutes = (
            merged["Time"]
            .diff()
            .dt.total_seconds()
            .dropna()
            .median()
            / 60.0
        )

        if not np.isfinite(timestep_minutes) or timestep_minutes <= 0:
            timestep_minutes = 1.0

        lag_results = print_metrics(
            merged["signal"],
            merged["actual_delta_kw"],
            timestep_minutes,
            source_name="C3 baseline/controlled power fallback",
        )

    plot_lag_correlation(lag_results)

    print("\nSaved diagnostic plots:")
    print(f"  {plot_response_file}")
    print(f"  {plot_lag_file}")

    if SHOW_PLOTS:
        plt.show()
    else:
        plt.close("all")


if __name__ == "__main__":
    main()