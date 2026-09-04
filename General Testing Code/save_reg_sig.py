import os
import shutil
import datetime as dt
import pandas as pd
from ochre import Dwelling
from ochre.utils.schedule import ALL_SCHEDULE_NAMES
import concurrent.futures
from pathlib import Path
import ochre

filename = 'AC_Test_PID_1.0_0.8_1.0'
Input_folder = "AC Input Files"

# Original OCHRE defaults folder
ochre_dir = Path(ochre.__file__).resolve().parent
DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"

# Safe working folder (writable)
script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
WORKING_DIR = os.path.dirname(fl_dir)
INPUT_DIR = os.path.join(WORKING_DIR, Input_folder, "bldg")
WEATHER_DIR = os.path.join(WORKING_DIR, "Weather")
WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
XML_ADDRESS = "home.xml"
CSV_ADDRESS = "in.schedules.csv"

REG_DIR = os.path.join(WORKING_DIR, "RegA Signal")
REG_ADDRESS = "RegA_Generated.csv"

Start = dt.datetime(2018, 7, 11, 0, 0)
Duration = 2  # days
t_res = 1 


def signal_aggregator_mean(reg_signal = pd.read_csv(os.path.join(REG_DIR, REG_ADDRESS))):
    # assume sig_step in seconds and t_res in minutes
    reg_signal["timestamp"] = pd.to_datetime(reg_signal["Timestamp"])

    sig_step_dt = reg_signal["timestamp"].diff()
    sig_step = int(
        sig_step_dt.dt.total_seconds().mean()
    )
    ochre_step = t_res * 60
    working_step = int(ochre_step / sig_step)
    duration_min = Duration * 24 * 60
    frequency = f"{t_res}min"
    period = int(duration_min / t_res)

    sim_times = pd.date_range(start=Start, periods=period, freq=frequency)

    required_samples = len(sim_times) * working_step

    if len(reg_signal) < required_samples:
        raise ValueError(
            f"Regulation signal is too short. "
            f"Need {required_samples} samples, "
            f"have {len(reg_signal)}."
        )

    working_sig = []

    count = 0

    for sim_time in sim_times:

        working_sig.append(
            reg_signal["Signal"].iloc[count:count+working_step].mean()
        )

        count += working_step

    working_sig = pd.Series(
        working_sig,
        index=sim_times
    )

    save_sig(working_sig, Start + pd.Timedelta(days=1))

    return working_sig


def save_sig(reg_sig, start_time):

    ts = int(1 / t_res)        # minutes per average

    avg_sig = []

    for i in range(0, len(reg_sig), ts):
        avg_sig.append(reg_sig.iloc[i:i+ts].mean())

    avg_sig = pd.Series(avg_sig)

    sim_times = pd.date_range(
        start=start_time,
        periods=len(avg_sig),
        freq="1min"
    )

    saved_sig = pd.DataFrame({
        "Timestamp": sim_times,
        "Signal": avg_sig
    })

    reg_results_dir = os.path.join(
        WORKING_DIR,
        "RegA Signal"
    )

    os.makedirs(reg_results_dir, exist_ok=True)

    saved_sig.to_csv(
        os.path.join(reg_results_dir, "rega_filtered.csv"),
        index=False
    )

    print("file saved!")

signal_aggregator_mean()