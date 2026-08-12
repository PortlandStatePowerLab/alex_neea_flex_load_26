
import os
import pandas as pd
from pathlib import Path
import math

SIGNAL_TYPE = "RegA"

script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
WORKING_DIR = os.path.dirname(fl_dir)
REG_DIR = os.path.join(WORKING_DIR, f"{SIGNAL_TYPE.lower()} Signal")
REG_ADDRESS = f"{SIGNAL_TYPE}-test-wave.csv"
OUTPUT_ADDRESS = f"{SIGNAL_TYPE}-ochre.csv"

input_path = os.path.join(REG_DIR, REG_ADDRESS)
output_path = os.path.join(REG_DIR, OUTPUT_ADDRESS)

START_TIME = pd.Timestamp("2018-01-01 00:00:00")
TARGET_MINUTES = 2 * 24 * 60


def load_and_expand_signal(path) -> pd.DataFrame:
    raw = pd.read_csv(path)

    signal_columns = [
        col for col in raw.columns
        if col.strip().startswith("Normalized RegA Signal Test Wave")
    ]

    if "Time" not in raw.columns or len(signal_columns) != 1:
        raise ValueError(
            f"Expected Time and one RegA signal column; "
            f"found {list(raw.columns)}"
        )

    # Convert timestamps to elapsed time.
    parsed = pd.to_datetime(
        raw["Time"].astype(str),
        format="%M:%S",
        errors="raise"
    )

    offsets = parsed - parsed.iloc[0].normalize()

    # Stretch time by 10x.
    expanded_offsets = offsets * 10

    signal = pd.DataFrame(
        {
            "Time": START_TIME + expanded_offsets,
            "Signal": pd.to_numeric(
                raw[signal_columns[0]],
                errors="raise"
            ),
        }
    )

    return signal


def cycle_to_two_days(signal: pd.DataFrame) -> pd.DataFrame:
    # Determine the original timestep after expansion.
    timestep = signal["Time"].iloc[1] - signal["Time"].iloc[0]

    # How many samples are needed for two days?
    target_duration = pd.Timedelta(days=2)
    samples_needed = math.ceil(
        target_duration / timestep
    )

    # Repeat the signal enough times.
    cycles_needed = math.ceil(
        samples_needed / len(signal)
    )

    values = pd.concat(
        [signal["Signal"]] * cycles_needed,
        ignore_index=True
    ).iloc[:samples_needed]

    # Create timestamps at the expanded timestep.
    times = pd.date_range(
        start=START_TIME,
        periods=len(values),
        freq=timestep
    )

    return pd.DataFrame(
        {
            "Time": times,
            "Signal": values
        }
    )

signal_expanded = load_and_expand_signal(
    os.path.join(REG_DIR, REG_ADDRESS)
)

ochre_signal = cycle_to_two_days(signal_expanded)

ochre_signal.to_csv(
    os.path.join(REG_DIR, OUTPUT_ADDRESS),
    index=False,
    date_format="%Y-%m-%d %H:%M:%S",
)