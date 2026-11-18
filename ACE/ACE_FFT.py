import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


DATA_FILE = (
    Path(__file__).resolve().parent
    / "HistoricalACE - CAISO"
    / "2025 CAISO Area Control Error 1 minute average.xlsx"
)


# Calendar periods in the workbook's displayed local clock.
PERIODS = {
    "hourly": ("h", 60, "hour"),
    "daily": ("D", 1440, "day"),
    "weekly": ("W-SUN", 10080, "week"),
}


def period_description(start, end, period):
    if period == "hourly":
        return f"{start:%Y-%m-%d %H:%M} to {end:%H:%M} (end exclusive)"
    if period == "daily":
        return f"{start:%Y-%m-%d}"
    last_day = end - pd.Timedelta(days=1)
    return f"{start:%Y-%m-%d} through {last_day:%Y-%m-%d}"


def calculate_fft(values):
    x = values.to_numpy(dtype=float)

    if not np.isfinite(x).all():
        raise ValueError("FFT input contains missing or invalid values.")

    # Remove the average imbalance to focus on changing ACE.
    x = x - x.mean()

    # Reduce leakage caused by the selected period starting and ending
    # at different ACE values.
    window = np.hanning(len(x))
    transformed = np.fft.rfft(x * window)

    # d is in minutes, so frequency is cycles per minute.
    frequency = np.fft.rfftfreq(len(x), d=1.0)

    # Single-sided amplitude, corrected for the window's gain.
    amplitude = np.abs(transformed) / window.sum()

    if len(x) % 2 == 0:
        amplitude[1:-1] *= 2
    else:
        amplitude[1:] *= 2

    return frequency, amplitude


def format_period(minutes):
    if minutes >= 1440:
        return f"{minutes / 1440:.2g} d"
    if minutes >= 60:
        return f"{minutes / 60:.2g} h"
    return f"{minutes:.2g} min"


def plot_selected_ffts(ace, selections, period, eligible_count, top_n=15):
    _, expected_minutes, unit = PERIODS[period]
    # Calculate first so all panels can use the same amplitude scale.
    spectra = []

    for label, start in selections.items():
        end = start + pd.Timedelta(minutes=expected_minutes)

        values = ace.loc[
            (ace.index >= start) & (ace.index < end)
        ]

        if len(values) != expected_minutes:
            raise ValueError(
                f"{label} does not contain {expected_minutes:,} samples."
            )

        frequency, amplitude = calculate_fft(values)

        # Exclude zero frequency, then select the strongest bins.
        nonzero = np.flatnonzero(frequency > 0)
        strongest = nonzero[
            np.argsort(amplitude[nonzero])[-top_n:]
        ]

        # Put selected bars in increasing frequency order.
        strongest = strongest[
            np.argsort(frequency[strongest])
        ]

        spectra.append((
            label,
            start,
            frequency[strongest],
            amplitude[strongest],
        ))

    ymax = max(a.max() for _, _, _, a in spectra) * 1.15

    fig, axes = plt.subplots(
        2,
        2,
        figsize=(17, 11),
        sharey=True,
        layout="constrained",
    )

    for ax, (label, start, frequency, amplitude) in zip(
        axes.flat, spectra
    ):
        # Use categorical spacing so each selected bin is readable.
        positions = np.arange(len(frequency))

        tick_labels = [
            f"{f:.4f}\n({format_period(1 / f)})"
            for f in frequency
        ]

        ax.bar(positions, amplitude, color="steelblue", width=0.75)

        ax.set_xticks(positions)
        ax.set_xticklabels(
            tick_labels,
            rotation=60,
            ha="right",
            fontsize=8,
        )

        end = start + pd.Timedelta(minutes=expected_minutes)

        ax.set_title(
            f"{label}\n{period_description(start, end, period)}",
            fontsize=11,
        )
        ax.set_xlabel("Frequency: cycles/minute\n(period in parentheses)")
        ax.set_ylabel("Hann-corrected FFT amplitude (MW)")
        ax.set_ylim(0, ymax)
        ax.grid(axis="y", alpha=0.3)
        ax.set_axisbelow(True)

    fig.suptitle(
        f"2025 CAISO ACE - {top_n} strongest nonzero FFT bins per {unit}\n"
        f"Selected from {eligible_count:,} eligible complete {unit}s; "
        "mean removed, Hann window applied",
        fontsize=13,
    )

    output_file = DATA_FILE.parent.parent / f"selected_{unit}_fft.png"
    fig.savefig(output_file, dpi=200)
    print(f"\nSaved FFT figure: {output_file}")

    plt.show()

def load_ace():
    monthly_frames = []

    with pd.ExcelFile(DATA_FILE) as workbook:
        for sheet_name in workbook.sheet_names:
            # The first row contains "Number of Values".
            frame = pd.read_excel(
                workbook,
                sheet_name=sheet_name,
                skiprows=1,
                header=None,
                usecols=[0, 1],
                names=["timestamp", "ace_mw"],
            )

            frame["source_sheet"] = sheet_name
            monthly_frames.append(frame)

    data = pd.concat(monthly_frames, ignore_index=True)

    data["timestamp"] = pd.to_datetime(
        data["timestamp"], errors="coerce"
    )
    data["ace_mw"] = pd.to_numeric(
        data["ace_mw"], errors="coerce"
    )

    # Treat infinity as invalid, just like a missing measurement.
    data["ace_mw"] = data["ace_mw"].replace(
        [np.inf, -np.inf], np.nan
    )

    return data


def inspect_timestamp_issues(data):
    timed = data.sort_values("timestamp").copy()

    # How far does each timestamp fall after its minute boundary?
    minute_start = timed["timestamp"].dt.floor("min")
    offset_seconds = (
        timed["timestamp"] - minute_start
    ).dt.total_seconds()

    off_grid = timed.loc[offset_seconds.ne(0)].copy()
    off_grid["offset_seconds"] = offset_seconds.loc[off_grid.index]

    print("\n--- Off-minute timestamps ---")
    print(off_grid.head(20).to_string(index=False))

    print("\nMost common offsets after minute boundary (seconds):")
    print(
        off_grid["offset_seconds"]
        .round(6)
        .value_counts()
        .head(15)
    )

    # Separate repeated identical readings from conflicting readings.
    timestamp_groups = timed.groupby("timestamp")["ace_mw"]

    duplicate_summary = timestamp_groups.agg(
        rows="size",
        distinct_values="nunique",
        minimum_mw="min",
        maximum_mw="max",
    )

    duplicates = duplicate_summary[
        duplicate_summary["rows"] > 1
    ].copy()

    duplicates["spread_mw"] = (
        duplicates["maximum_mw"] - duplicates["minimum_mw"]
    )

    print("\n--- Duplicate timestamp groups ---")
    print(f"Total groups: {len(duplicates):,}")
    print(
        "Groups with conflicting ACE values:",
        f"{duplicates['distinct_values'].gt(1).sum():,}",
    )

    print("\nLargest differences within duplicate timestamps:")
    print(
        duplicates.sort_values("spread_mw", ascending=False)
        .head(10)
        .to_string()
    )

    # Inspect both potential daylight-saving transitions.
    for start, end in [
        ("2025-03-09 01:55", "2025-03-09 03:05"),
        ("2025-11-02 00:55", "2025-11-02 02:05"),
    ]:
        window = timed[
            timed["timestamp"].between(start, end)
        ]

        print(f"\n--- Clock-transition window: {start} to {end} ---")
        print(f"Rows: {len(window):,}")
        print(window.head(12).to_string(index=False))
        print("...")
        print(window.tail(12).to_string(index=False))



def calculate_period_scores(data, period="daily"):
    frequency, expected_minutes, unit = PERIODS[period]
    # Keep exact-minute records for this first analysis.
    exact_minute = data["timestamp"].eq(
        data["timestamp"].dt.floor("min")
    )

    records = data.loc[
        exact_minute, ["timestamp", "ace_mw"]
    ].copy()

    # Repeated identical readings are harmless.
    # Different values at the same timestamp remain unresolved.
    grouped = records.groupby("timestamp")["ace_mw"]

    minute_values = grouped.first()
    conflicting = grouped.nunique().gt(1)
    minute_values.loc[conflicting] = np.nan

    # Reindexing exposes missing minutes instead of closing the gaps.
    full_index = pd.date_range(
        "2025-01-01",
        "2026-01-01",
        freq="min",
        inclusive="left",
    )

    ace = minute_values.reindex(full_index)
    ace.index.name = "timestamp"

    # Exclude the entire affected calendar period. In hourly mode,
    # only the skipped/repeated clock hour is excluded.
    clock_change_periods = {
        pd.Timestamp("2025-03-09 02:00").to_period(frequency),
        pd.Timestamp("2025-11-02 01:00").to_period(frequency),
    }

    rows = []
    period_labels = ace.index.to_period(frequency)

    for calendar_period, values in ace.groupby(period_labels):
        start = calendar_period.start_time
        end = start + pd.Timedelta(minutes=expected_minutes)
        valid_minutes = int(values.notna().sum())

        if calendar_period in clock_change_periods:
            status = "clock-change period"
        elif len(values) != expected_minutes:
            status = "partial year-boundary period"
        elif valid_minutes != expected_minutes:
            status = "missing or conflicting minutes"
        else:
            status = "eligible"

        rms_ace = np.nan
        rms_ramp = np.nan

        if status == "eligible":
            x = values.to_numpy(dtype=float)

            rms_ace = np.sqrt(np.mean(x**2))

            # Samples are exactly one minute apart.
            # Compute differences within this period only.
            ramps = np.diff(x) / 1.0
            rms_ramp = np.sqrt(np.mean(ramps**2))

        rows.append({
            "period_start": start,
            "period_end_exclusive": end,
            "valid_minutes": valid_minutes,
            "status": status,
            "rms_ace_mw": rms_ace,
            "rms_ramp_mw_per_min": rms_ramp,
        })

    scores = pd.DataFrame(rows).set_index("period_start")

    return ace, scores


def print_year_frequency_summary(data):
    """Summarize nonzero frequency limits and common daily dominant bins."""
    ace, scores = calculate_period_scores(data, "daily")
    eligible = scores.loc[scores["status"].eq("eligible")]
    print("\n--- Whole-year frequency summary (daily FFTs) ---")
    print(f"Eligible days: {len(eligible):,} / {len(scores):,}")
    print(scores["status"].value_counts().to_string())
    print("Frequency extremes use all positive-frequency bins with nonzero amplitude.")
    print("Common frequencies count the strongest nonzero FFT bin per day.")
    print("Mean removed; Hann window applied; no interpolation.")
    print("Frequency resolution: 1/1440 cycles/min (1 cycle/day).")

    rows = []
    lowest_frequency = None
    highest_frequency = None
    for start in eligible.index:
        end = start + pd.Timedelta(days=1)
        values = ace.loc[(ace.index >= start) & (ace.index < end)]
        # A constant series has no nonzero-frequency variation to rank.
        if np.ptp(values.to_numpy(dtype=float)) == 0:
            continue
        frequency, amplitude = calculate_fft(values)
        present = frequency[(frequency > 0) & (amplitude > 0)]
        if not len(present):
            continue
        day_low = float(present.min())
        day_high = float(present.max())
        lowest_frequency = (
            day_low if lowest_frequency is None else min(lowest_frequency, day_low)
        )
        highest_frequency = (
            day_high if highest_frequency is None else max(highest_frequency, day_high)
        )
        peak_bin = int(np.argmax(amplitude[1:])) + 1
        rows.append({
            "day": start,
            "bin": peak_bin,
            "frequency": frequency[peak_bin],
            "amplitude": amplitude[peak_bin],
        })

    print(f"Days with a defined dominant frequency: {len(rows):,}")
    if not rows:
        print("No eligible days with nonconstant ACE are available.")
        return

    for label, value in [
        ("Lowest nonzero frequency", lowest_frequency),
        ("Highest nonzero frequency", highest_frequency),
    ]:
        print(
            f"{label}: {value:.9f} cycles/min "
            f"({value * 1440:.0f} cycles/day; period {format_period(1 / value)})"
        )
    print(
        "No amplitude threshold is applied: tiny components, leakage, and "
        "floating-point residuals can count. These limits generally reflect "
        "daily FFT resolution and the one-minute sampling rate."
    )

    peaks = pd.DataFrame(rows)
    # Count integer FFT bins rather than rounded frequency labels.
    counts = (
        peaks.groupby("bin").size().rename("days").reset_index()
        .sort_values(["days", "bin"], ascending=[False, True])
    )
    print("\nTop 3 most common daily dominant frequencies:")
    print("Ties in day count are ordered by increasing frequency.")
    for rank, row in enumerate(counts.head(3).itertuples(index=False), 1):
        frequency = row.bin / 1440
        print(
            f"{rank}. {frequency:.6f} cycles/min "
            f"({row.bin} cycles/day; period {format_period(1 / frequency)})"
            f" | {row.days} days ({row.days / len(peaks):.1%} of analyzed days)"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Rank complete CAISO ACE hours, days, or weeks and plot FFTs."
    )
    parser.add_argument(
        "--period", choices=PERIODS, default="daily",
        help="Calendar period to rank (default: daily).",
    )
    parser.add_argument(
        "--year-frequency-summary", action="store_true",
        help="Print whole-year nonzero frequency limits and common daily dominant frequencies.",
    )
    args = parser.parse_args()
    if args.year_frequency_summary:
        print_year_frequency_summary(load_ace())
        return
    period = args.period
    _, expected_minutes, unit = PERIODS[period]
    print(f"Analysis: {period} ({expected_minutes:,} minute samples per {unit})")
    data = load_ace()

    print(f"Total rows: {len(data):,}")
    print(f"Invalid timestamps: {data['timestamp'].isna().sum():,}")
    print(f"Missing/invalid ACE values: {data['ace_mw'].isna().sum():,}")

    timed = (
        data.dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .copy()
    )

    print(f"\nFirst timestamp: {timed['timestamp'].min()}")
    print(f"Last timestamp:  {timed['timestamp'].max()}")

    duplicate_rows = timed[
        timed["timestamp"].duplicated(keep=False)
    ]

    print(f"\nRows sharing a timestamp: {len(duplicate_rows):,}")

    if not duplicate_rows.empty:
        print(duplicate_rows.head(12).to_string(index=False))

    # Compare unique timestamps so duplicates do not create zero intervals.
    unique_times = pd.DatetimeIndex(
        timed["timestamp"].drop_duplicates()
    )

    intervals = unique_times.to_series().diff().dropna()

    print("\nMost common timestamp intervals:")
    print(intervals.value_counts().head(10))

    expected = pd.date_range(
        start="2025-01-01",
        end="2026-01-01",
        freq="min",
        inclusive="left",
    )

    missing = expected.difference(unique_times)
    outside = unique_times[
        (unique_times < expected[0])
        | (unique_times >= pd.Timestamp("2026-01-01"))
    ]
    off_minute = unique_times[
        unique_times != unique_times.floor("min")
    ]

    print(f"\nMissing 2025 minute timestamps: {len(missing):,}")
    print(f"Timestamps outside 2025: {len(outside):,}")
    print(f"Timestamps off the minute grid: {len(off_minute):,}")

    if len(missing):
        print("First missing timestamps:")
        print(missing[:10])

    inspect_timestamp_issues(data)

    ace, scores = calculate_period_scores(data, period)

    print(f"\n--- {period.title()} eligibility ---")
    print(scores["status"].value_counts())

    eligible = scores.loc[scores["status"].eq("eligible")]

    if eligible.empty:
        print(f"\nNo complete {unit}s qualify under these rules.")
        return

    selections = {
        "Highest RMS ACE": eligible["rms_ace_mw"].idxmax(),
        "Lowest RMS ACE": eligible["rms_ace_mw"].idxmin(),
        "Highest RMS ramp": eligible["rms_ramp_mw_per_min"].idxmax(),
        "Lowest RMS ramp": eligible["rms_ramp_mw_per_min"].idxmin(),
    }

    print(f"\n--- Selected {unit}s (among {len(eligible):,} eligible) ---")

    for label, start in selections.items():
        row = eligible.loc[start]
        end = row["period_end_exclusive"]

        print(
            f"{label}: "
            f"{period_description(start, end, period)} | "
            f"RMS ACE = {row['rms_ace_mw']:.2f} MW | "
            f"RMS ramp = {row['rms_ramp_mw_per_min']:.2f} MW/min"
        )

    plot_selected_ffts(ace, selections, period, len(eligible))


if __name__ == "__main__":
    main()