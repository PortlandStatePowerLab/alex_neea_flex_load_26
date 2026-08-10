
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


def load_and_downsample_signal(path) -> pd.DataFrame:
    raw = pd.read_csv(path)

    signal_columns = [
        col for col in raw.columns
        if col.strip().startswith("Normalized RegA Signal Test Wave")
    ]
    if "Time" not in raw.columns or len(signal_columns) != 1:
        raise ValueError(f"Expected Time and one RegA signal column; found {list(raw.columns)}")

    # Input times such as 0:02 mean 0 minutes, 2 seconds.
    parsed = pd.to_datetime(raw["Time"].astype(str), format="%M:%S", errors="raise")
    offsets = parsed - parsed.iloc[0].normalize()

    signal = pd.DataFrame(
        {
            "Time": START_TIME + offsets,
            "Signal": pd.to_numeric(raw[signal_columns[0]], errors="raise"),
        }
    ).set_index("Time")

    # A value exactly at 40:00 is the endpoint, not a new full minute.
    if signal.index[-1] == signal.index[0] + pd.Timedelta(minutes=40):
        signal = signal.iloc[:-1]

    one_minute = signal.resample("1min").mean()

    if one_minute["Signal"].isna().any():
        raise ValueError("Missing samples prevent creation of a complete one-minute signal.")

    return one_minute.reset_index()


def cycle_to_two_days(one_minute: pd.DataFrame) -> pd.DataFrame:
    cycles_needed = math.ceil(TARGET_MINUTES / len(one_minute))
    values = pd.concat(
        [one_minute["Signal"]] * cycles_needed,
        ignore_index=True,
    ).iloc[:TARGET_MINUTES]

    return pd.DataFrame(
        {
            "Time": pd.date_range(
                start=START_TIME,
                periods=TARGET_MINUTES,
                freq="min",
            ),
            "Signal": values,
        }
    )


signal_1min = load_and_downsample_signal(os.path.join(REG_DIR, REG_ADDRESS))
ochre_signal = cycle_to_two_days(signal_1min)

ochre_signal.to_csv(
    os.path.join(REG_DIR, OUTPUT_ADDRESS),
    index=False,
    date_format="%Y-%m-%d %H:%M:%S",
)