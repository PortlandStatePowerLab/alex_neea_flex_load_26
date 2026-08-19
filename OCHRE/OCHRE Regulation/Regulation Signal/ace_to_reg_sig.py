"""
Author: Alex Wardwell
Created: 8/18/26

Modifies an ACE signal from ERCOT into a RegA and RegD signal.
Based on PJM Manual 12, 2020

@modified by: 
@modified date: 
"""

from pathlib import Path
import numpy as np
import pandas as pd


REG_DIR = Path(__file__).resolve().parent
INPUT_PATH = REG_DIR / "ancillary-services-frequency.csv"
OUTPUT_DIR = REG_DIR.parent / "OCHRE in Excel" / "Reg Sig"
OUTPUT_PATH_A = OUTPUT_DIR / "RegA-ochre.csv"
OUTPUT_PATH_D = OUTPUT_DIR / "RegD-ochre.csv"

START_TIME = pd.Timestamp("2018-01-11 00:00:00")
TARGET_MINUTES = 2 * 24 * 60

TAU_REGA = 100.0
TAU_NEUTRAL = 120.0
TAU_REGD = 1.0

FREQ_NORM = 0.1


def load_ace(path):
    """Load the headerless time/frequency file and determine its cadence."""
    raw = pd.read_csv(path)

    raw["DateTime"] = pd.to_timedelta(
        raw["DateTime"].astype(str).str[11:],
        errors="raise",
    )
    raw["Frequency"] = pd.to_numeric(raw["Frequency"], errors="raise")

    if len(raw) < 2:
        raise ValueError("The ACE input must contain at least two samples.")

    time_steps = raw["DateTime"].diff().dropna().dt.total_seconds()
    if (time_steps <= 0).any() or not np.allclose(time_steps, time_steps.iloc[0]):
        raise ValueError("Input timestamps must be strictly increasing and evenly spaced.")

    return raw, float(time_steps.iloc[0])


def first_order_lowpass(signal, tau, dt):
    """Apply a first-order low-pass filter to an evenly sampled signal."""
    signal = np.asarray(signal, dtype=float)
    if signal.size == 0:
        raise ValueError("Cannot filter an empty signal.")

    alpha = np.exp(-dt / tau)
    filtered = np.empty_like(signal)
    filtered[0] = signal[0]

    for i in range(1, len(signal)):
        filtered[i] = alpha * filtered[i - 1] + (1 - alpha) * signal[i]

    return filtered


def get_reg_signals(ace, dt):
    reg_a = first_order_lowpass(ace, tau=TAU_REGA, dt=dt)
    reg_d_raw = ace - reg_a
    reg_d_slow = first_order_lowpass(reg_d_raw, tau=TAU_NEUTRAL, dt=dt)
    reg_d = first_order_lowpass(reg_d_raw - reg_d_slow, tau=TAU_REGD, dt=dt)
    return reg_a, reg_d


def average_normalize_and_repeat(signal, sample_seconds, t_res):
    """Average into fixed bins, normalize to [-1, 1], and fill two days."""
    bin_seconds = t_res * 60
    samples_per_bin = bin_seconds / sample_seconds
    if not samples_per_bin.is_integer():
        raise ValueError(
            f"A {t_res}-minute interval is not divisible by the "
            f"{sample_seconds:g}-second input cadence."
        )

    samples_per_bin = int(samples_per_bin)
    complete_samples = len(signal) - (len(signal) % samples_per_bin)
    if complete_samples == 0:
        raise ValueError("The input is shorter than one output interval.")

    averaged = np.asarray(signal[:complete_samples]).reshape(-1, samples_per_bin).mean(axis=1)
    # scale = np.max(np.abs(averaged))
    # if scale > 0:
    #     averaged = averaged / scale
    averaged = averaged / FREQ_NORM
    target_periods = TARGET_MINUTES // t_res
    repeats = int(np.ceil(target_periods / len(averaged)))
    return np.tile(averaged, repeats)[:target_periods]


def make_output(signal, t_res):
    return pd.DataFrame(
        {
            "Time": pd.date_range(
                start=START_TIME, periods=len(signal), freq=f"{t_res}min"
            ),
            "Signal": signal,
        }
    )


def main(t_res=1):
    if not isinstance(t_res, int) or t_res <= 0:
        raise ValueError("t_res must be a positive whole number of minutes.")
    if TARGET_MINUTES % t_res:
        raise ValueError("t_res must divide evenly into the two-day output duration.")

    ace, sample_seconds = load_ace(INPUT_PATH)
    centered_ace = 60.0 - ace["Frequency"].to_numpy()
    reg_a, reg_d = get_reg_signals(centered_ace, dt=sample_seconds)

    reg_a = average_normalize_and_repeat(reg_a, sample_seconds, t_res)
    reg_d = average_normalize_and_repeat(reg_d, sample_seconds, t_res)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    make_output(reg_a, t_res).to_csv(
        OUTPUT_PATH_A, index=False, date_format="%Y-%m-%d %H:%M:%S"
    )
    make_output(reg_d, t_res).to_csv(
        OUTPUT_PATH_D, index=False, date_format="%Y-%m-%d %H:%M:%S"
    )

    print(f"Wrote {OUTPUT_PATH_A}")
    print(f"Wrote {OUTPUT_PATH_D}")


if __name__ == "__main__":
    main()
