
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime as dt
import argparse


# ---------------------------------------------------------------------------
# USER SETTINGS
# ---------------------------------------------------------------------------

# Set True to display plots after saving them.
SHOW_PLOTS = True


# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(project_dir)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def find_vpp_log(run_id):
    """Return the first existing B2 VPP log path."""
    # B2 writes to its script directory. Older locations remain fallbacks for
    # existing result sets created before the Excel pipeline was consolidated.
    vpp_log_candidates = [
        os.path.join(script_dir, f"{run_id}_VPP_Fleet_States.csv"),
        os.path.join(project_dir, f"{run_id}_VPP_Fleet_States.csv"),
        os.path.join(working_dir, f"{run_id}_VPP_Fleet_States.csv"),
    ]
    for path in vpp_log_candidates:
        if os.path.isfile(path):
            return path
    searched = "\n  ".join(vpp_log_candidates)
    raise FileNotFoundError(f"Could not find the VPP state log. Searched:\n  {searched}")


def load_vpp_data(path):
    """Load and prepare the B2 VPP state log."""
    df = pd.read_csv(path)

    required = {
        "Time",
        "Regulation Capacity (kW)",
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
    numeric_columns = [
        "Regulation Capacity (kW)",
        "Target Delta (kW)",
        "Actual HPWH Delta (kW)",
        "Tracking Error (kW)",
    ]
    df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(
        subset=["Time", "Regulation Capacity (kW)", "Target Delta (kW)", "Actual HPWH Delta (kW)"]
    ).copy()

    df = df.sort_values("Time")
    df = df.drop_duplicates(subset="Time")

    # Infer the actual simulation timestep from timestamps.
    diffs = df["Time"].diff().dt.total_seconds().dropna() / 60.0
    timestep_minutes = diffs.median()

    if not np.isfinite(timestep_minutes) or timestep_minutes <= 0:
        timestep_minutes = 1.0

    return df, float(timestep_minutes)


def pjm_delay_corr(target, actual, timestamp, t_res):
    """
    Calculate delay and correlation scores for the trailing five-minute window
    ending at `timestamp`.

    Parameters
    ----------
    target : pd.Series
        Target Delta (kW), indexed by timestamp.
    actual : pd.Series
        Actual HPWH Delta (kW), indexed by timestamp.
    timestamp : pd.Timestamp
        End of the scoring window.
    t_res : float
        Data timestep in minutes.
    """
    candidates = []

    target = target.sort_index()
    actual = actual.sort_index()

    window_end = pd.Timestamp(timestamp)
    window_start = window_end - pd.Timedelta(minutes=5)

    # Includes both zero and five minutes. A one-minute B2 log therefore
    # evaluates delays of 0, 1, 2, 3, 4, and 5 minutes.
    delay_minutes = np.arange(0, 5 + t_res / 2, t_res)
    minimum_samples = max(2, int(round(5 / t_res)) + 1)

    for delay_min in delay_minutes:
        delay_steps = int(round(delay_min / t_res))

        pair = pd.concat(
            [
                target.shift(delay_steps).rename("target"),
                actual.rename("actual"),
            ],
            axis=1,
        )

        pair = pair.loc[window_start:window_end].dropna()

        if (
            len(pair) < minimum_samples
            or pair["target"].std() == 0
            or pair["actual"].std() == 0
        ):
            corr = np.nan
        else:
            corr = pair["target"].corr(pair["actual"])

        delay_score = abs((delay_min - 5.0) / 5.0)

        if np.isfinite(corr):
            candidates.append(
                {
                    "delay_min": float(delay_min),
                    "corr_score": float(corr),
                    "delay_score": float(delay_score),
                    "selection_score": float(corr + delay_score),
                }
            )

    if not candidates:
        return {
            "delay_min": np.nan,
            "corr_score": np.nan,
            "delay_score": np.nan,
            "selection_score": np.nan,
        }

    return max(candidates, key=lambda x: x["selection_score"])


def pjm_precision(target, actual, reg_cap_kw):

    reg_cap = np.mean(reg_cap_kw)

    if not np.isfinite(reg_cap) or reg_cap <= 0:
        return np.nan

    pair = pd.concat(
        [
            target.rename("target"),
            actual.rename("actual"),
        ],
        axis=1,
    ).dropna()

    absolute_error = (pair["target"] - pair["actual"]).abs()

    mean_absolute_error_kw = absolute_error.mean()

    raw_precision_score = (
        1.0
        - mean_absolute_error_kw / reg_cap
    )

    return np.clip(raw_precision_score, 0.0, 1.0)


def main(run_id):
    vpp_path = find_vpp_log(run_id)
    df, t_res = load_vpp_data(vpp_path)

    if t_res > 5:
        raise ValueError(
            f"VPP log timestep is {t_res:g} minutes. C4 requires a log at "
            "five-minute resolution or finer; use B2's normal one-minute setting."
        )

    delay_corr = []
    target = df.set_index("Time")["Target Delta (kW)"]
    actual = df.set_index("Time")["Actual HPWH Delta (kW)"]
    for timestamp in target.index:
        delay_corr.append(pjm_delay_corr(target, actual, timestamp, t_res))

    delay_corr_df = pd.DataFrame(delay_corr)
    avg_corr = delay_corr_df["corr_score"].mean()
    avg_delay = delay_corr_df["delay_score"].mean()

    precision = pjm_precision(df["Target Delta (kW)"], df["Actual HPWH Delta (kW)"], df["Regulation Capacity (kW)"])

    print(precision)
    return ((avg_corr / 3) + (avg_delay / 3) + (precision / 3))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    main(parser.parse_args().run_id)
