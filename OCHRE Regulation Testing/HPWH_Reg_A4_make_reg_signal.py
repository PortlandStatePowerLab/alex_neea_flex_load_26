from pathlib import Path
import datetime as dt
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.signal


# ---------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------

script_dir = os.path.dirname(os.path.abspath(__file__))
FL_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(FL_dir)

OUTPUT_DIR = Path(working_dir)


# ---------------------------------------------------------------------
# Signal parameters
# ---------------------------------------------------------------------

SIGNAL_PARAMETERS = {

    "RegA": {
        "cutoff_freq": 0.002,
        "order": 2,
        "phi": 0.99,
        "noise_std": 0.10,
    },

    "RegD": {
        "cutoff_freq": 0.02,
        "order": 2,
        "phi": 0.95,
        "noise_std": 0.20,
    }

}


# ---------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------

def random_noise_gen(n_periods, phi, noise_std):

    noise = np.zeros(n_periods)

    for i in range(1, n_periods):

        random_step = np.random.normal(0, noise_std)

        noise[i] = phi * noise[i-1] + random_step

    return noise


def smooth_signal(raw_signal, cutoff_freq, order, timestep):

    sos = scipy.signal.butter(
        order,
        cutoff_freq,
        btype="low",
        output="sos",
        fs=1 / timestep
    )

    return scipy.signal.sosfiltfilt(sos, raw_signal)


def normalize_signal(filtered_signal):

    signal = filtered_signal.copy()
    signal -= np.mean(signal)

    if np.max(np.abs(signal)) > 1:
        signal /= np.max(np.abs(signal))

    return signal


def save_signal(time, signal, output_folder, filename):

    output_folder.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame({
        "Timestamp": time,
        "Signal": signal
    })

    df.to_csv(output_folder / filename, index=False)

    return df


# ---------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------

def generate_regulation_signal(
        signal_type="RegA",
        duration_days=2,
        timestep=10,
        random_seed=None,
        start_time=dt.datetime(2018, 1, 11, 0, 0),
        save=True,
        plot=True):

    if signal_type not in SIGNAL_PARAMETERS:
        raise ValueError(f"Unknown signal type: {signal_type}")

    if random_seed is not None:
        np.random.seed(random_seed)

    params = SIGNAL_PARAMETERS[signal_type]

    n_periods = duration_days * 24 * 60 * 60 // timestep

    time = pd.date_range(
        start=start_time,
        periods=n_periods,
        freq=f"{timestep}s"
    )

    raw_signal = random_noise_gen(
        n_periods,
        params["phi"],
        params["noise_std"]
    )

    filtered_signal = smooth_signal(
        raw_signal,
        params["cutoff_freq"],
        params["order"],
        timestep
    )

    regulation_signal = normalize_signal(filtered_signal)

    print("Statistics")
    print("----------------")
    print("Min :", regulation_signal.min())
    print("Max :", regulation_signal.max())
    print("Mean:", regulation_signal.mean())
    print("Std :", regulation_signal.std())

    if save:

        filename = f"{signal_type}_Generated.csv"

        save_signal(
            time,
            regulation_signal,
            OUTPUT_DIR / f"{signal_type} Signal",
            filename
        )

    if plot:

        samples_per_hour = 3600 // timestep

        plt.figure(figsize=(12,4))

        plt.plot(
            time[:samples_per_hour],
            regulation_signal[:samples_per_hour]
        )

        plt.title(f"{signal_type} Signal")

        plt.xlabel("Time")
        plt.ylabel("Normalized AGC Signal")

        plt.tight_layout()

        plt.show()

    return time, regulation_signal


# ---------------------------------------------------------------------
# Example
# ---------------------------------------------------------------------

if __name__ == "__main__":

    generate_regulation_signal(
        signal_type="RegA",
        duration_days=2,
        timestep=10,
        random_seed=55
    )
