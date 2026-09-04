"""
Author: Thomas Metzler
Created: 7/6/26
Runs the controlled HPWH fleet against a saved B2 baseline.

Modified by Alex Wardwell
Modified on 8/19/26
"""

import os
import shutil
import datetime as dt
import pandas as pd
from ochre import Dwelling
from ochre.utils.schedule import ALL_SCHEDULE_NAMES
import concurrent.futures
from pathlib import Path
import ochre
from math import isfinite
import time

import sys
import threading

import warnings

warnings.filterwarnings("ignore")


class OCHREOutputFilter:
    """
    Suppress OCHRE's normal console output while preserving:
      - user/application output
      - WARNING/ERROR tracebacks
      - simulation progress messages
    """

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.local = threading.local()

    def write(self, text):
        if not text:
            return 0

        if not hasattr(self.local, "buffer"):
            self.local.buffer = ""

        self.local.buffer += text

        while "\n" in self.local.buffer:

            line, self.local.buffer = (
                self.local.buffer.split("\n", 1)
            )

            if self._suppress(line):
                continue

            with self.lock:
                self.stream.write(line + "\n")
                self.stream.flush()

        return len(text)

    def flush(self):
        if hasattr(self.local, "buffer"):

            if self.local.buffer:
                line = self.local.buffer

                if not self._suppress(line):
                    with self.lock:
                        self.stream.write(line)
                        self.stream.flush()

                self.local.buffer = ""

        self.stream.flush()

    def _suppress(self, line):

        stripped = line.strip()

        if not stripped:
            return False

        upper_line = stripped.upper()

        # --------------------------------------------------------
        # Suppress all explicit WARNING messages
        # --------------------------------------------------------

        if "WARNING:" in upper_line:
            return True

        if "Removing previous results file:" in stripped:
            return True

        if "HPWH All Portland Input Files" in stripped:
            return True

        # --------------------------------------------------------
        # Suppress OCHRE initialization/status messages
        # --------------------------------------------------------

        if "OCHRE V" in upper_line:
            return True

        if stripped == "Dwelling Initialized":
            return True

        if stripped.startswith("Initializing Base_"):
            return True

        if stripped.startswith("Initializing Ctrl_"):
            return True

        # OCHRE dwelling timestamp/status lines
        if (
            ("Base_bldg" in stripped or "Ctrl_bldg" in stripped)
            and "2018-" in stripped
        ):
            return True

        return False
    def __getattr__(self, name):
        return getattr(self.stream, name)

sys.stdout = OCHREOutputFilter(sys.stdout)
sys.stderr = OCHREOutputFilter(sys.stderr)

    
#########################################
# USER SETTINGS
#########################################
#Gallons, MLU, MLU duration, Shed duration, ELU, ELU duration, Shed duration, Offset sheds 
filename = 'test_825'

#"HPWH 50 Input Files", "HPWH 66 Input Files/bldg", "HPWH 80 Input Files", "HPWH All Input Files/bldg"
Input_folder = "HPWH All Portland Input Files"

# Original OCHRE defaults folder
ochre_dir = Path(ochre.__file__).resolve().parent
DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
# print("OCHRE installed at:", ochre_dir)
# print(DEFAULT_INPUT)

DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"
#DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "G4100510_2018.csv" 
# ^ Incorrect format for the weather file, it doesn't want csv
# G4100510 is Multnomah county weather station, code will complain this is missing but it doesn't work otherwise

# Safe working folder (writable)
script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
# Generated HPWH data and results are self-contained in the HPWH folder.  The
# signal, Weather, and Metadata folders remain shared sources outside it.
EXCEL_DIR = fl_dir
OCHRE_DIR = os.path.dirname(os.path.dirname(EXCEL_DIR))
RESULTS_DIR = script_dir
INPUT_DIR = os.path.join(script_dir, Input_folder, "bldg")
WEATHER_DIR = os.path.join(script_dir, "Weather")
WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
METADATA_DIR = os.path.join(script_dir, "Metadata")
XML_ADDRESS = "home.xml"
CSV_ADDRESS = "in.schedules.csv"


REG_TYPE = 'RegA'
# The calculator-owned signal folder is the direct parent of HPWH.
REG_DIR = os.path.join(script_dir, "Reg Sig")
REG_ADDRESS = f"{REG_TYPE}-ochre.csv"


# Simulation parameters
Start = dt.datetime(2018, 1, 11, 0, 0)
Duration = 1  # days
t_res = 1.0  # minutes

# NUM_HOMES = 10

# B3 receives its directional regulation capacities from B2's baseline run.

# Dispatch and comfort settings.  With a one-minute timestep, five minutes is
# a conservative initial minimum command duration.  A home is always released
# if the regulation request reverses direction or returns to zero.
MIN_HOLD_MINUTES = 5
MIN_HOLD_STEPS = max(1, round(MIN_HOLD_MINUTES / t_res))
CONTROL_INTERVAL_MINUTES = 1
CONTROL_INTERVAL_STEPS = max(1, round(CONTROL_INTERVAL_MINUTES / t_res))
# SHED_MAX_TEMP_F = 76.0
# LOAD_MIN_TEMP_F = 71.0
SHED_MIN_TANK_TEMP_F = 120
LOAD_TARGET_TANK_TEMP_F = 130
ACTIVE_POWER_THRESHOLD_KW = 0.1
EXPECTED_ON_POWER_KW = 0.5
FEEDBACK_GAIN = 0.3
TRACKING_DEADBAND_KW = 0.25
MAX_RESPONSE_CHANGE_KW_PER_INTERVAL = 10


# HPWH control parameters (°F)
Tcontrol_SHEDF = 126
Tcontrol_deadbandF = 10
Tcontrol_LOADF = 130
Tcontrol_LOADdeadbandF = 2
TbaselineF = 130
TdeadbandF = 7
Tinit = 128
count = 0


def _positive_number(name, value):
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric; received {value!r}.") from exc
    if not isfinite(numeric_value) or numeric_value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero; received {value!r}.")
    return numeric_value


def _nonnegative_number(name, value):
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric; received {value!r}.") from exc
    if not isfinite(numeric_value) or numeric_value < 0:
        raise ValueError(
            f"{name} must be finite and non-negative; received {value!r}."
        )
    return numeric_value


def _refresh_derived_settings():
    """Refresh values expressed in simulation units after configuration."""
    global MIN_HOLD_STEPS, CONTROL_INTERVAL_STEPS, MAX_TANK_TEMPERATURE_C
    global Tcontrol_SHEDC, Tcontrol_deadbandC, Tcontrol_LOADC
    global Tcontrol_LOADdeadbandC, TbaselineC, TdeadbandC, TinitC
    global SHED_MIN_TANK_TEMP_C, LOAD_TARGET_TANK_TEMP_C

    MIN_HOLD_STEPS = max(1, round(MIN_HOLD_MINUTES / t_res))
    CONTROL_INTERVAL_STEPS = max(1, round(CONTROL_INTERVAL_MINUTES / t_res))
    Tcontrol_SHEDC = f_to_c(Tcontrol_SHEDF)
    Tcontrol_deadbandC = f_to_c_DB(Tcontrol_deadbandF)
    Tcontrol_LOADC = f_to_c(Tcontrol_LOADF)
    Tcontrol_LOADdeadbandC = f_to_c_DB(Tcontrol_LOADdeadbandF)
    TbaselineC = f_to_c(TbaselineF)
    TdeadbandC = f_to_c_DB(TdeadbandF)
    TinitC = f_to_c(Tinit)
    SHED_MIN_TANK_TEMP_C = f_to_c(SHED_MIN_TANK_TEMP_F)
    LOAD_TARGET_TANK_TEMP_C = f_to_c(LOAD_TARGET_TANK_TEMP_F)
    MAX_TANK_TEMPERATURE_C = f_to_c(LOAD_TARGET_TANK_TEMP_F)


def configure(parameters=None):
    """Apply calculator HPWH settings before the B2 simulation starts.

    Temperatures are Fahrenheit and power is kW.  XML properties (tank volume,
    UEF, heating capacity, and resistance capacity) are intentionally handled
    by A3; this function controls B2's dispatch behaviour.
    """
    if parameters is None:
        return {"applied": [], "handled_by_a3": []}
    if not isinstance(parameters, dict):
        raise TypeError("parameters must be a dictionary keyed by calculator parameter name.")

    global EXPECTED_ON_POWER_KW, SHED_MIN_TANK_TEMP_F
    global LOAD_TARGET_TANK_TEMP_F, Tcontrol_SHEDF, Tcontrol_LOADF
    global MIN_HOLD_MINUTES, CONTROL_INTERVAL_MINUTES

    applied = []
    if parameters.get("comp_pwr") not in (None, ""):
        EXPECTED_ON_POWER_KW = _positive_number("comp_pwr", parameters["comp_pwr"])
        applied.append("comp_pwr")
    if parameters.get("min_water_temp") not in (None, ""):
        SHED_MIN_TANK_TEMP_F = _positive_number("min_water_temp", parameters["min_water_temp"])
        Tcontrol_SHEDF = SHED_MIN_TANK_TEMP_F
        applied.append("min_water_temp")
    if parameters.get("max_water_temp") not in (None, ""):
        LOAD_TARGET_TANK_TEMP_F = _positive_number("max_water_temp", parameters["max_water_temp"])
        Tcontrol_LOADF = LOAD_TARGET_TANK_TEMP_F
        applied.append("max_water_temp")
    if parameters.get("resp_time") not in (None, ""):
        MIN_HOLD_MINUTES = _positive_number("resp_time", parameters["resp_time"])
        applied.append("resp_time")
    if parameters.get("cntrl_int") not in (None, ""):
        CONTROL_INTERVAL_MINUTES = _positive_number("cntrl_int", parameters["cntrl_int"])
        applied.append("cntrl_int")

    _refresh_derived_settings()
    return {
        "applied": applied,
        "handled_by_a3": sorted(
            key for key in ("tank_vol", "cop_uef", "heat_cap", "resist_pwr")
            if parameters.get(key) not in (None, "")
        ),
    }


def signal_aggregator_mean(reg_signal=None):
    if reg_signal is None:
        reg_signal = pd.read_csv(os.path.join(REG_DIR, REG_ADDRESS))
    # assume sig_step in seconds and t_res in minutes
    reg_signal["timestamp"] = pd.to_datetime(reg_signal["Time"])

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

    save_sig(working_sig)

    return working_sig


def save_sig(reg_sig):

    saved_sig = pd.DataFrame({
        "Timestamp": reg_sig.index,
        "Signal": reg_sig.values
    })

    os.makedirs(REG_DIR, exist_ok=True)

    saved_sig.to_csv(
        os.path.join(REG_DIR, f"{REG_TYPE}_filtered.csv"),
        index=False
    )

    # print("Filtered regulation signal saved.")


REG_SIGNAL = pd.Series(dtype=float)


def configure_regulation(reg_type):
    """Select and load the regulation signal used by this B2 run."""
    global REG_TYPE, REG_ADDRESS, REG_SIGNAL

    normalized_types = {"rega": "RegA", "regd": "RegD"}
    try:
        selected_type = normalized_types[str(reg_type).strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"reg_type must be 'RegA' or 'RegD'; received {reg_type!r}."
        ) from exc

    signal_file = os.path.join(REG_DIR, f"{selected_type}-ochre.csv")
    if not os.path.isfile(signal_file):
        raise FileNotFoundError(f"Regulation signal file not found: {signal_file}")

    REG_TYPE = selected_type
    REG_ADDRESS = f"{REG_TYPE}-ochre.csv"
    REG_SIGNAL = signal_aggregator_mean()


    import numpy as np
    duration_min = Duration * 24 * 60
    frequency = f"{t_res}min"
    period = int(duration_min / t_res)
    sim_times = pd.date_range(start=Start, periods=period, freq=frequency)
    x = np.arange(0, 1440*0.1, 0.1)
    REG_SIGNAL = pd.Series(
        np.sin(x),
        index=sim_times
    )
    return signal_file
#########################################
# TEMPERATURE CONVERSIONS F to C
#########################################

def f_to_c(temp_f): 
    return (temp_f - 32) * 5/9

def f_to_c_DB(temp_f):
    return 5/9 * temp_f

_refresh_derived_settings()

#########################################
# HELPER FUNCTIONS
#########################################



def get_reg_sig(sim_time):
    return REG_SIGNAL.get(sim_time, 0.0)


def _clean_power(value, default=0.0):
    """Return a non-negative numeric power value."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if pd.notna(value) and value > 0 else default


def _estimated_incremental_load_kw(home):
    current_kw = _clean_power(home.get("last_ctrl_hpwh_kw"))

    if current_kw > ACTIVE_POWER_THRESHOLD_KW:
        return 0.0  # Already operating; little upward response available.

    return max(0.0, EXPECTED_ON_POWER_KW - current_kw)


def _estimated_incremental_shed_kw(home):
    current_kw = _clean_power(home.get("last_ctrl_hpwh_kw"))

    if current_kw <= ACTIVE_POWER_THRESHOLD_KW:
        return 0.0

    return max(0.0, current_kw)


def estimate_up_capacity_kw(fleet_data):
    """Additional HPWH power available by loading eligible NORMAL homes."""
    return sum(
        _estimated_incremental_load_kw(home)
        for home in fleet_data
        if (
            home["override"] == "NORMAL"
            and _load_eligible(home)
        )
    )


def estimate_down_capacity_kw(fleet_data):
    """HPWH power available for shedding eligible NORMAL homes."""
    return sum(
        _estimated_incremental_shed_kw(home)
        for home in fleet_data
        if (
            home["override"] == "NORMAL"
            and _shed_eligible(home)
        )
    )

def _shed_eligible(home):
    return (
        _clean_power(home.get("last_ctrl_hpwh_kw"))
        > ACTIVE_POWER_THRESHOLD_KW
        and home.get("last_tank_temp_c", TbaselineC) >= SHED_MIN_TANK_TEMP_C
        and home.get("lockout_steps", 0) == 0
    )


def _load_eligible(home):
    return (
        _clean_power(home.get("last_ctrl_hpwh_kw"))
        <= ACTIVE_POWER_THRESHOLD_KW
        and home.get("last_tank_temp_c", TbaselineC) <= LOAD_TARGET_TANK_TEMP_C
        and home.get("lockout_steps", 0) == 0
    )


def _normalise_reg_signal(reg_sig):
    try:
        reg_sig = float(reg_sig)
    except (TypeError, ValueError):
        reg_sig = 0.0
    if pd.isna(reg_sig):
        reg_sig = 0.0
    return max(-1.0, min(1.0, reg_sig))


def _releasable(home, mode):
    return (
        home.get("override") == mode
        and home.get("lockout_steps", 0) == 0
        and not home.get("changed_this_interval", False)
    )


def _release_home(home):
    """Release one command and return its signed estimated response change."""
    mode = home.get("override", "NORMAL")
    response_kw = _clean_power(home.get("dispatch_kw"))
    signed_change_kw = response_kw if mode == "SHED" else -response_kw
    home["override"] = "NORMAL"
    home["lockout_steps"] = 0
    home["dispatch_kw"] = 0.0
    home["changed_this_interval"] = True
    return signed_change_kw


def _current_estimated_dispatch_kw(fleet_data):
    """Return the signed estimated response of all persistent commands."""
    return sum(
        _clean_power(home.get("dispatch_kw"))
        * (1 if home.get("override") == "LOAD" else -1)
        for home in fleet_data
        if home.get("override") in {"LOAD", "SHED"}
    )


def _available_adjustment_capacity_kw(fleet_data):
    """Return immediately actionable upward and downward response capacity."""
    releasable_shed_kw = sum(
        _clean_power(home.get("dispatch_kw"))
        for home in fleet_data
        if _releasable(home, "SHED")
    )
    releasable_load_kw = sum(
        _clean_power(home.get("dispatch_kw"))
        for home in fleet_data
        if _releasable(home, "LOAD")
    )
    available_up_kw = estimate_up_capacity_kw(fleet_data) + releasable_shed_kw
    available_down_kw = estimate_down_capacity_kw(fleet_data) + releasable_load_kw
    return available_up_kw, available_down_kw


def _apply_actions(candidates, action, requested_change_kw):
    """Apply one ordered action list subject to the per-interval kW limit."""
    applied_magnitude_kw = 0.0
    changed_count = 0

    for home in candidates:
        if applied_magnitude_kw >= requested_change_kw:
            break

        if action == "RELEASE_LOAD" or action == "RELEASE_SHED":
            response_kw = _clean_power(home.get("dispatch_kw"))
        elif action == "ADD_LOAD":
            response_kw = _estimated_incremental_load_kw(home)
        else:
            response_kw = _estimated_incremental_shed_kw(home)

        if response_kw <= 0:
            continue
        if (
            applied_magnitude_kw + response_kw
            > MAX_RESPONSE_CHANGE_KW_PER_INTERVAL + 1e-9
        ):
            continue

        if action == "RELEASE_LOAD" or action == "RELEASE_SHED":
            _release_home(home)
        else:
            home["override"] = "LOAD" if action == "ADD_LOAD" else "SHED"
            home["lockout_steps"] = MIN_HOLD_STEPS
            home["dispatch_kw"] = response_kw
            home["dispatch_count"] = home.get("dispatch_count", 0) + 1
            home["changed_this_interval"] = True

        applied_magnitude_kw += response_kw
        changed_count += 1

    return applied_magnitude_kw, changed_count


def dispatch_regulation_signal(
    fleet_data,
    reg_sig,
    previous_actual_delta_kw,
    up_cap,
    dwn_cap,
    # home_num
):
    """Adjust persistent HPWH commands using signed fleet-response feedback."""
    # up_cap = up_cap / home_num
    # dwn_cap = dwn_cap / home_num

    reg_sig = _normalise_reg_signal(reg_sig)
    if reg_sig > 0:
        target_delta_kw = reg_sig * up_cap
    elif reg_sig < 0:
        target_delta_kw = reg_sig * dwn_cap
    else:
        target_delta_kw = 0.0

    for home in fleet_data:
        home["changed_this_interval"] = False
        if home.get("lockout_steps", 0) > 0:
            home["lockout_steps"] = max(
                0,
                home["lockout_steps"] - CONTROL_INTERVAL_STEPS,
            )

    counts = {
        "added_load": 0,
        "released_load": 0,
        "added_shed": 0,
        "released_shed": 0,
    }
    applied_adjustment_kw = 0.0

    # A command in the opposite direction must not remain locked through a
    # signal reversal.  At zero, release both directions so the fleet returns
    # to its normal thermostat instead of carrying response across the zero
    # crossing.  Released homes wait until the next interval before they can
    # receive another command.
    forced_release_modes = set()
    if reg_sig >= 0:
        forced_release_modes.add("SHED")
    if reg_sig <= 0:
        forced_release_modes.add("LOAD")
    for home in fleet_data:
        mode = home.get("override")
        if mode in forced_release_modes:
            applied_adjustment_kw += _release_home(home)
            counts[
                "released_load" if mode == "LOAD" else "released_shed"
            ] += 1

    # Comfort limits override minimum holds. These homes cannot be selected
    # for another command during the same interval.
    urgent_shed_releases = [
        home for home in fleet_data
        if (
            home.get("override") == "SHED"
            and home.get("last_tank_temp_c", TbaselineC)
            <= SHED_MIN_TANK_TEMP_C
        )
    ]
    urgent_load_releases = [
        home for home in fleet_data
        if (
            home.get("override") == "LOAD"
            and home.get("last_tank_temp_c", TbaselineC)
            >= LOAD_TARGET_TANK_TEMP_C
        )
    ]
    for home in urgent_shed_releases:
        applied_adjustment_kw += _release_home(home)
        counts["released_shed"] += 1
    for home in urgent_load_releases:
        applied_adjustment_kw += _release_home(home)
        counts["released_load"] += 1

    predicted_delta_kw = previous_actual_delta_kw + applied_adjustment_kw
    available_up_kw, available_down_kw = (
        _available_adjustment_capacity_kw(fleet_data)
    )
    capacity_limited_target_kw = min(
        max(
            target_delta_kw,
            predicted_delta_kw - available_down_kw,
        ),
        predicted_delta_kw + available_up_kw,
    )
    feedback_error_kw = capacity_limited_target_kw - predicted_delta_kw
    raw_adjustment_kw = FEEDBACK_GAIN * feedback_error_kw
    requested_adjustment_kw = raw_adjustment_kw
    requested_adjustment_kw = max(
        -MAX_RESPONSE_CHANGE_KW_PER_INTERVAL,
        min(MAX_RESPONSE_CHANGE_KW_PER_INTERVAL, requested_adjustment_kw),
    )
    feedback_applied_kw = 0.0

    if feedback_error_kw > TRACKING_DEADBAND_KW:
        remaining_kw = requested_adjustment_kw
        release_candidates = sorted(
            (
                home for home in fleet_data
                if _releasable(home, "SHED")
            ),
            key=lambda home: (
                home.get("last_tank_temp_c", TbaselineC),
                home.get("dispatch_count", 0),
            ),
        )
        released_kw, released_count = _apply_actions(
            release_candidates,
            "RELEASE_SHED",
            remaining_kw,
        )
        feedback_applied_kw += released_kw
        counts["released_shed"] += released_count
        remaining_kw = max(0.0, remaining_kw - released_kw)

        load_candidates = sorted(
            (
                home for home in fleet_data
                if (
                    home.get("override") == "NORMAL"
                    and not home.get("changed_this_interval", False)
                    and _load_eligible(home)
                )
            ),
            key=lambda home: (
                home.get("last_tank_temp_c", TbaselineC),
                home.get("dispatch_count", 0),
            ),
        )
        loaded_kw, loaded_count = _apply_actions(
            load_candidates,
            "ADD_LOAD",
            remaining_kw,
        )
        feedback_applied_kw += loaded_kw
        counts["added_load"] += loaded_count

    elif feedback_error_kw < -TRACKING_DEADBAND_KW:
        remaining_kw = abs(requested_adjustment_kw)
        release_candidates = sorted(
            (
                home for home in fleet_data
                if _releasable(home, "LOAD")
            ),
            key=lambda home: (
                -home.get("last_tank_temp_c", TbaselineC),
                home.get("dispatch_count", 0),
            ),
        )
        released_kw, released_count = _apply_actions(
            release_candidates,
            "RELEASE_LOAD",
            remaining_kw,
        )
        feedback_applied_kw -= released_kw
        counts["released_load"] += released_count
        remaining_kw = max(0.0, remaining_kw - released_kw)

        shed_candidates = sorted(
            (
                home for home in fleet_data
                if (
                    home.get("override") == "NORMAL"
                    and not home.get("changed_this_interval", False)
                    and _shed_eligible(home)
                )
            ),
            key=lambda home: (
                -home.get("last_tank_temp_c", TbaselineC),
                home.get("dispatch_count", 0),
            ),
        )
        shed_kw, shed_count = _apply_actions(
            shed_candidates,
            "ADD_SHED",
            remaining_kw,
        )
        feedback_applied_kw -= shed_kw
        counts["added_shed"] += shed_count

    applied_adjustment_kw += feedback_applied_kw
    achieved_feedback_kw = abs(feedback_applied_kw)
    requested_feedback_kw = abs(requested_adjustment_kw)
    controller_saturated = (
        abs(capacity_limited_target_kw - target_delta_kw)
        > TRACKING_DEADBAND_KW
        or abs(raw_adjustment_kw)
        > MAX_RESPONSE_CHANGE_KW_PER_INTERVAL + 1e-9
        or achieved_feedback_kw + TRACKING_DEADBAND_KW
        < requested_feedback_kw
    )
    requested_mode = (
        "LOAD" if target_delta_kw > 0
        else "SHED" if target_delta_kw < 0
        else "NORMAL"
    )
    dispatched_units = sum(
        home.get("override") == requested_mode
        for home in fleet_data
    ) if requested_mode != "NORMAL" else 0
    retained_kw = sum(
        _clean_power(home.get("dispatch_kw"))
        for home in fleet_data
        if (
            home.get("override") in {"LOAD", "SHED"}
            and home.get("lockout_steps", 0) > 0
        )
    )
    available_requested_kw = (
        available_up_kw if target_delta_kw >= predicted_delta_kw
        else available_down_kw
    )

    return {
        "reg_sig": reg_sig,
        "target_delta_kw": target_delta_kw,
        "capacity_limited_target_kw": capacity_limited_target_kw,
        "previous_actual_delta_kw": previous_actual_delta_kw,
        "feedback_error_kw": feedback_error_kw,
        "requested_adjustment_kw": requested_adjustment_kw,
        "applied_adjustment_kw": applied_adjustment_kw,
        "available_up_kw": available_up_kw,
        "available_down_kw": available_down_kw,
        "available_requested_kw": available_requested_kw,
        "estimated_dispatch_kw": _current_estimated_dispatch_kw(fleet_data),
        "dispatched_units": dispatched_units,
        "retained_kw": retained_kw,
        "controller_saturated": controller_saturated,
        **counts,
    }

def filter_schedules(home_path):
    orig_sched_file = os.path.join(home_path, CSV_ADDRESS)
    filtered_sched_file = os.path.join(home_path, 'filtered_schedules.csv')

    df_sched = pd.read_csv(orig_sched_file)
    valid_schedule_names = set(ALL_SCHEDULE_NAMES.keys())
    filtered_columns = [col for col in df_sched.columns if col in valid_schedule_names]
    dropped_columns = [col for col in df_sched.columns if col not in filtered_columns]
    
    # if dropped_columns:
        # print(f"Dropped invalid schedules for {home_path}: {dropped_columns}")

    df_sched_filtered = df_sched[filtered_columns]
    df_sched_filtered.to_csv(filtered_sched_file, index=False)
    return filtered_sched_file

def find_all_homes(base_dir):
    images = []
    homes = []
    for item in os.listdir(base_dir):
        home_path = os.path.join(base_dir, item)
        if os.path.isdir(home_path):
            if os.path.isfile(os.path.join(home_path, XML_ADDRESS)) and \
               os.path.isfile(os.path.join(home_path, CSV_ADDRESS)):
                homes.append(home_path)
    return homes

# def remove_first_day(df, start_date):
#     if 'Time' not in df.columns:
#         df = df.reset_index()
#         if 'index' in df.columns:
#             df.rename(columns={'index': 'Time'}, inplace=True)
#     df['Time'] = pd.to_datetime(df['Time'], errors='coerce')
#     first_day_end = start_date + pd.Timedelta(days=1)
#     return df[df['Time'] >= first_day_end].copy()

def restore_time_column(df, result_name):
    """Move OCHRE's datetime index into a regular Time column."""
    if "Time" in df.columns:
        return df

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            f"{result_name} has no Time column and its index is not datetime."
        )

    return df.rename_axis("Time").reset_index()


def load_baseline_profiles(baseline_path):
    """Load run-specific B2 HPWH power profiles keyed by home name."""
    if not os.path.isfile(baseline_path):
        raise FileNotFoundError(
            f"Baseline aggregate not found: {baseline_path}. Run B2 first "
            "with the same run_id."
        )

    required_columns = {
        "Time",
        "Home",
        "Water Heating Electric Power (kW)",
    }
    available_columns = pd.read_csv(baseline_path, nrows=0).columns
    missing_columns = required_columns.difference(available_columns)
    if missing_columns:
        raise ValueError(
            f"Baseline aggregate is missing required columns: "
            f"{sorted(missing_columns)}"
        )

    baseline_data = pd.read_csv(
        baseline_path,
        usecols=list(required_columns),
    )

    baseline_data["Time"] = pd.to_datetime(
        baseline_data["Time"],
        errors="raise",
    )
    baseline_data["Water Heating Electric Power (kW)"] = pd.to_numeric(
        baseline_data["Water Heating Electric Power (kW)"],
        errors="raise",
    )
    baseline_power = baseline_data["Water Heating Electric Power (kW)"]
    if not baseline_power.map(isfinite).all():
        raise ValueError(
            "Baseline aggregate contains non-finite HPWH power values."
        )

    duplicate_rows = baseline_data.duplicated(subset=["Home", "Time"])
    if duplicate_rows.any():
        duplicate_count = int(duplicate_rows.sum())
        raise ValueError(
            f"Baseline aggregate contains {duplicate_count} duplicate "
            "Home/Time rows."
        )

    profiles = {}
    for home_name, home_data in baseline_data.groupby("Home", sort=False):
        home_data = home_data.sort_values("Time")
        profiles[str(home_name)] = pd.Series(
            home_data["Water Heating Electric Power (kW)"].to_numpy(
                dtype=float
            ),
            index=pd.DatetimeIndex(home_data["Time"]),
        )

    if not profiles:
        raise ValueError("Baseline aggregate contains no home profiles.")

    return profiles


def aggregate_results(homes, work_dir, run_id):
    all_ctrl = []
    for home in homes:
        results_dir = os.path.join(home, "Results")
        ctrl_file = os.path.join(results_dir, "hpwh_controlled.csv")

        if os.path.exists(ctrl_file):
            df_ctrl = pd.read_csv(ctrl_file)
            df_ctrl["Home"] = os.path.basename(home)
            all_ctrl.append(df_ctrl)

    if not all_ctrl:
        raise RuntimeError("No controlled CSVs were available for aggregation.")

    aggregate_path = os.path.join(work_dir, run_id + "_controlled.csv")
    df_ctrl_all = pd.concat(all_ctrl, ignore_index=True)
    df_ctrl_all.to_csv(aggregate_path, index=False)
    print("Aggregated controlled CSV written!", flush=True)
    return aggregate_path

#########################################
# HPWH / HVAC CONTROL & INITIALIZATION
#########################################

def determine_hpwh_control(global_mode="NORMAL"):
    """
    Highly simplified controller. 
    It purely reacts to the assigned global VPP mode.
    """
    ctrl_signal = {
        'Water Heating': {
            'Setpoint': TbaselineC,
            'Deadband': TdeadbandC,
            'Load Fraction': 1,
        }
    }

    if global_mode == "SHED":
        ctrl_signal['Water Heating'].update({'Setpoint': Tcontrol_SHEDC})
        ctrl_signal['Water Heating'].update({'Deadband': Tcontrol_deadbandC})
        ctrl_signal["Water Heating"].update({'Load Fraction': 0})
    elif global_mode == "LOAD":
        ctrl_signal['Water Heating'].update({'Setpoint': Tcontrol_LOADC})
        ctrl_signal['Water Heating'].update({'Deadband': Tcontrol_LOADdeadbandC})

    return ctrl_signal

def initialize_home(home_path, weather_file_path):
    filtered_sched_file = filter_schedules(home_path)
    hpxml_file = os.path.join(home_path, XML_ADDRESS)
    
    dwelling_args_local = {
        "start_time": Start,
        "time_res": dt.timedelta(minutes=t_res),
        "duration": dt.timedelta(days=Duration),
        "hpxml_file": hpxml_file,
        "hpxml_schedule_file": filtered_sched_file,
        "weather_file": weather_file_path,
        # Level 6 retains every column exported below (including energy),
        # while avoiding the level-7 schedule/debug results at every minute.
        "initialization_time": dt.timedelta(
            weeks=0,
            days=1,
            hours=0,
            minutes=0,
            seconds=0,
            milliseconds=0,
            microseconds=0
        ),
        "verbosity": 7,
        "Equipment": {
            "Water Heating": {
                "Initial Temperature (C)": TinitC,
                "hp_only_mode": True,
                "Max Tank Temperature (C)": MAX_TANK_TEMPERATURE_C,
                "Upper Node": 3,
                "Lower Node": 10,
                "Upper Node Weight": 0.75,
            },
        },
    }

    sim_dwelling = Dwelling(name=f"Ctrl_{os.path.basename(home_path)}", **dwelling_args_local)
    return sim_dwelling

def init_fleet_worker(home, build_num, num_builds, baseline_profile):
    """Initialize one controlled dwelling and align its B2 baseline profile."""

    try:
        sim_dw = initialize_home(
            home,
            WEATHER_FILE
        )

        sim_times = pd.DatetimeIndex(sim_dw.sim_times)
        if not sim_times.equals(baseline_profile.index):
            raise ValueError(
                f"Controlled simulation times do not match the B2 baseline "
                f"for {os.path.basename(home)}."
            )

        return {
            "success": True,
            "sim": sim_dw,
            "path": home,
            "baseline_hpwh_kw": baseline_profile.to_numpy(dtype=float),
            "override": "NORMAL",
            "lockout_steps": 0,
            "dispatch_count": 0,
            "dispatch_kw": 0.0,
            "last_ctrl_kw": 0.0,
            "last_hpwh_kw": 0.0,
            "last_tank_temp_c": TbaselineC,
            "last_base_hpwh_kw": 0.0,
            "last_ctrl_hpwh_kw": 0.0,
        }

    except Exception as e:
        return {
            "success": False,
            "path": home,
            "error": repr(e),
        }

      
def update_home_worker(home_data):
    """Advance one controlled dwelling by one timestep."""

    building_name = os.path.basename(home_data["path"])

    try:
        control_cmd = determine_hpwh_control(global_mode=home_data["override"])
        ctrl_metrics = home_data["sim"].update(control_signal=control_cmd)

        def get_metric(metrics, dwelling, name):
            if isinstance(metrics, dict) and name in metrics:
                return metrics[name]
            if hasattr(dwelling, "current_results"):
                return dwelling.current_results.get(name, 0.0)
            return 0.0

        return {
            "success": True,
            "ctrl_kw": get_metric(ctrl_metrics, home_data["sim"], "Total Electric Power (kW)"),
            "ctrl_hpwh_kw": get_metric(ctrl_metrics, home_data["sim"], "Water Heating Electric Power (kW)"),
            "tank_temp_c": get_metric(ctrl_metrics, home_data["sim"], "Hot Water Average Temperature (C)"),
        }
    except Exception as e:
        return {
            "success": False,
            "path": home_data["path"],
            "error": repr(e),
        }

#########################################
# MAIN EXECUTION
#########################################

def main(parameters=None, run_id=None, reg_type="RegA", up_cap=None, dwn_cap=None):
    """Run the controlled HPWH fleet against the matching B2 baseline."""

    effective_run_id = run_id or filename

    # ============================================================
    # 0. Configuration
    # ============================================================

    configuration = configure(parameters)
    signal_file = configure_regulation(reg_type)
    if up_cap is None or dwn_cap is None:
        raise ValueError(
            "B3 requires up_cap and dwn_cap from the matching B2 baseline run."
        )
    baseline_up_capacity_kw = _nonnegative_number("up_cap", up_cap)
    baseline_down_capacity_kw = _nonnegative_number("dwn_cap", dwn_cap)
    committed_capacity_kw = min(
        baseline_up_capacity_kw,
        baseline_down_capacity_kw,
    )
    if committed_capacity_kw <= 0:
        raise ValueError(
            "B3 requires positive up and down capacities to form a symmetric "
            "sine-wave commitment."
        )
    print(
        f"Using B2 reliable capacities: up={baseline_up_capacity_kw:.3f} kW, "
        f"down={baseline_down_capacity_kw:.3f} kW; symmetric sine-wave "
        f"commitment={committed_capacity_kw:.3f} kW",
        flush=True,
    )
    # print(f"Regulation type: {REG_TYPE} ({signal_file})", flush=True)

    # ============================================================
    # 1. Directory Setup
    # ============================================================

    if not os.path.isdir(INPUT_DIR):
        raise FileNotFoundError(
            f"HPWH XML fleet not found: {INPUT_DIR}. Run A3 first to create it."
        )

    if not os.path.isfile(WEATHER_FILE):
        raise FileNotFoundError(
            f"Weather file not found: {WEATHER_FILE}"
        )

    if not os.path.isdir(METADATA_DIR):
        raise FileNotFoundError(
            f"Metadata directory not found: {METADATA_DIR}"
        )

    baseline_path = os.path.join(
        RESULTS_DIR,
        effective_run_id + "_baseline.csv",
    )
    baseline_profiles = load_baseline_profiles(baseline_path)

    all_homes = find_all_homes(INPUT_DIR)
    # homes = homes[:NUM_HOMES]

    if not all_homes:
        raise RuntimeError(
            f"No valid homes found in {INPUT_DIR}."
        )

    homes = [
        home
        for home in all_homes
        if os.path.basename(home) in baseline_profiles
    ]
    missing_baselines = len(all_homes) - len(homes)
    if missing_baselines:
        print(
            f"Skipping {missing_baselines} homes with no B2 baseline data.",
            flush=True,
        )

    if not homes:
        raise RuntimeError(
            "None of the input homes have matching B2 baseline data."
        )

    print(f"Found {len(homes)} homes.", flush=True)
    print("Initializing homes...", flush=True)

    # This number NEVER changes. It is the denominator used to determine
    # whether a majority of the original fleet has failed.
    initial_home_count = len(homes)

    # Keep track of every home that fails at any point.
    failed_home_paths = set()

    # ============================================================
    # 2. Parallel Fleet Initialization
    # ============================================================

    fleet_data = []
    failed_initializations = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:

        futures = [
            executor.submit(
                init_fleet_worker,
                home,
                i,
                initial_home_count,
                baseline_profiles[os.path.basename(home)],
            )
            for i, home in enumerate(homes, start=1)
        ]

        pending = set(futures)

        first_building_initialized = False
        last_report_time = None
        last_reported_count = 0
        last_reported_percent = 0

        while pending:

            done, pending = concurrent.futures.wait(
                pending,
                timeout=0.5,
                return_when=concurrent.futures.FIRST_COMPLETED
            )

            # Process every building that finished since the last check.
            for future in done:

                result = future.result()

                if result["success"]:
                    fleet_data.append(result)

                else:
                    failed_initializations.append(result)
                    failed_home_paths.add(result["path"])

            initialized_count = len(fleet_data)

            # Start the 5-second timer when the first home finishes.
            if initialized_count > 0 and not first_building_initialized:

                first_building_initialized = True
                last_report_time = time.monotonic()
                last_reported_count = initialized_count

                percent_init = int(
                    100 * initialized_count / initial_home_count
                )
                last_reported_percent = percent_init

                print(
                    f"{percent_init}% initialized",
                    flush=True
                )

            # Report every 5 seconds.
            elif (
                first_building_initialized
                and time.monotonic() - last_report_time >= 20
            ):

                percent_init = int(
                    100 * initialized_count / initial_home_count
                )

                if initialized_count != last_reported_count and percent_init != last_reported_percent:
                    print(
                        f"{percent_init}% initialized",
                        flush=True
                    )
                    last_reported_percent = percent_init

                    last_reported_count = initialized_count

                last_report_time = time.monotonic()

        # Always report the final count.
        initialized_count = len(fleet_data)

        if initialized_count != last_reported_count:

            percent_init = int(
                100 * initialized_count / initial_home_count
            )

            if percent_init >= 98:
                percent_init = 100
            
            print(
                f"{percent_init}% initialized",
                flush=True
            )

    failed_count = len(failed_home_paths)

    # Stop only if more than half of the original homes failed.
    if failed_count > initial_home_count / 2:
        raise RuntimeError(
            f"Majority of homes failed initialization: "
            f"{failed_count}/{initial_home_count}."
        )

    if not fleet_data:
        raise RuntimeError(
            "No homes were successfully initialized."
        )

    # Number of currently active homes.
    num_homes = len(fleet_data)

    # ============================================================
    # 3. Co-Simulation Setup
    # ============================================================

    sim_times = fleet_data[0]["sim"].sim_times

    average_power_kw = 0.0
    previous_actual_delta_kw = 0.0
    vpp_state_log = []

    total_steps = len(sim_times)

    # Report once per simulation hour.
    progress_interval = max(
        1,
        int(60 / t_res)
    )

    # ============================================================
    # 4. Co-Simulation Time Loop
    # ============================================================

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:

        for step_index, sim_time in enumerate(sim_times, start=1):

            # ----------------------------------------------------
            # Get regulation signal
            # ----------------------------------------------------

            raw_reg_sig = get_reg_sig(sim_time)

            # ----------------------------------------------------
            # Dispatch regulation
            # ----------------------------------------------------

            if (step_index - 1) % CONTROL_INTERVAL_STEPS == 0:
                dispatch_state = dispatch_regulation_signal(
                    fleet_data,
                    raw_reg_sig,
                    previous_actual_delta_kw,
                    committed_capacity_kw,
                    committed_capacity_kw,
                    # num_homes,
                )

            else:
                reg_sig = _normalise_reg_signal(raw_reg_sig)
                if reg_sig > 0:
                    target_delta_kw = reg_sig * committed_capacity_kw
                elif reg_sig < 0:
                    target_delta_kw = reg_sig * committed_capacity_kw
                else:
                    target_delta_kw = 0.0
                available_up_kw, available_down_kw = (
                    _available_adjustment_capacity_kw(fleet_data)
                )
                capacity_limited_target_kw = min(
                    max(
                        target_delta_kw,
                        previous_actual_delta_kw - available_down_kw,
                    ),
                    previous_actual_delta_kw + available_up_kw,
                )
                requested_mode = (
                    "LOAD" if target_delta_kw > 0
                    else "SHED" if target_delta_kw < 0
                    else "NORMAL"
                )
                dispatch_state = {
                    "reg_sig": reg_sig,
                    "target_delta_kw": target_delta_kw,
                    "capacity_limited_target_kw": capacity_limited_target_kw,
                    "previous_actual_delta_kw": previous_actual_delta_kw,
                    "feedback_error_kw": (
                        capacity_limited_target_kw
                        - previous_actual_delta_kw
                    ),
                    "requested_adjustment_kw": 0.0,
                    "applied_adjustment_kw": 0.0,
                    "available_up_kw": available_up_kw,
                    "available_down_kw": available_down_kw,
                    "available_requested_kw": (
                        available_up_kw
                        if target_delta_kw >= previous_actual_delta_kw
                        else available_down_kw
                    ),
                    "estimated_dispatch_kw": (
                        _current_estimated_dispatch_kw(fleet_data)
                    ),
                    "dispatched_units": sum(
                        home.get("override") == requested_mode
                        for home in fleet_data
                    ) if requested_mode != "NORMAL" else 0,
                    "retained_kw": sum(
                        _clean_power(home.get("dispatch_kw"))
                        for home in fleet_data
                        if (
                            home.get("override") in {"LOAD", "SHED"}
                            and home.get("lockout_steps", 0) > 0
                        )
                    ),
                    "controller_saturated": (
                        abs(capacity_limited_target_kw - target_delta_kw)
                        > TRACKING_DEADBAND_KW
                    ),
                    "added_load": 0,
                    "released_load": 0,
                    "added_shed": 0,
                    "released_shed": 0,
                }

            reg_sig = dispatch_state["reg_sig"]
            target_delta_kw = dispatch_state["target_delta_kw"]

            # ----------------------------------------------------
            # Advance every active dwelling
            # ----------------------------------------------------

            step_results = list(
                executor.map(
                    update_home_worker,
                    fleet_data
                )
            )

            # ----------------------------------------------------
            # Remove homes that failed this timestep
            # ----------------------------------------------------

            successful_homes = []

            for home, result in zip(
                fleet_data,
                step_results
            ):

                if not result["success"]:

                    failed_home_paths.add(
                        home["path"]
                    )

                    continue

                # Update state for successful home.
                home["last_ctrl_kw"] = _clean_power(
                    result["ctrl_kw"]
                )

                home["last_hpwh_kw"] = _clean_power(
                    result["ctrl_hpwh_kw"]
                )

                home["last_tank_temp_c"] = (
                    result["tank_temp_c"]
                )

                home["last_base_hpwh_kw"] = _clean_power(
                    home["baseline_hpwh_kw"][step_index - 1]
                )

                home["last_ctrl_hpwh_kw"] = _clean_power(
                    result["ctrl_hpwh_kw"]
                )

                successful_homes.append(home)

            fleet_data = successful_homes

            # ----------------------------------------------------
            # Check fleet failure threshold
            # ----------------------------------------------------

            failed_count = len(failed_home_paths)

            if failed_count > initial_home_count / 2:
                raise RuntimeError(
                    f"Majority of buildings failed during "
                    f"the simulation: "
                    f"{failed_count}/{initial_home_count}."
                )

            if not fleet_data:
                raise RuntimeError(
                    "All buildings failed during the simulation."
                )

            # Update current active fleet size.
            num_homes = len(fleet_data)

            # ----------------------------------------------------
            # Calculate fleet results
            # ----------------------------------------------------

            baseline_hpwh_fleet_kw = sum(
                h["last_base_hpwh_kw"]
                for h in fleet_data
            )

            controlled_hpwh_fleet_kw = sum(
                h["last_ctrl_hpwh_kw"]
                for h in fleet_data
            )

            hpwh_actual_delta_kw = (
                controlled_hpwh_fleet_kw
                - baseline_hpwh_fleet_kw
            )

            current_step_aggregate_power = sum(
                home["last_ctrl_kw"]
                for home in fleet_data
            )

            tracking_error_kw = (
                target_delta_kw
                - hpwh_actual_delta_kw
            )
            previous_actual_delta_kw = hpwh_actual_delta_kw

            aggregate_power_kw = (
                current_step_aggregate_power
            )

            average_power_kw = (
                aggregate_power_kw / num_homes
            )

            # ----------------------------------------------------
            # Fleet state counts
            # ----------------------------------------------------

            shed_count = sum(
                1
                for h in fleet_data
                if h["override"] == "SHED"
            )

            load_count = sum(
                1
                for h in fleet_data
                if h["override"] == "LOAD"
            )

            normal_count = sum(
                1
                for h in fleet_data
                if h["override"] == "NORMAL"
            )

            # ----------------------------------------------------
            # Save VPP state
            # ----------------------------------------------------

            vpp_state_log.append({
                "Time": sim_time,
                "Regulation Signal": reg_sig,
                "Up Regulation Capacity (kW)":
                    committed_capacity_kw,
                "Down Regulation Capacity (kW)":
                    committed_capacity_kw,
                "B2 Reliable Up Capacity (kW)":
                    baseline_up_capacity_kw,
                "B2 Reliable Down Capacity (kW)":
                    baseline_down_capacity_kw,
                "Available Up Capacity (kW)":
                    dispatch_state["available_up_kw"],
                "Available Down Capacity (kW)":
                    dispatch_state["available_down_kw"],
                "Committed Regulation Capacity (kW)": committed_capacity_kw,
                "Target Before Capacity Limit (kW)":
                    dispatch_state["target_delta_kw"],
                "Capacity-Limited Target (kW)":
                    dispatch_state["capacity_limited_target_kw"],
                "Target Delta (kW)": target_delta_kw,
                "Actual Delta (kW)": hpwh_actual_delta_kw,
                "Tracking Error (kW)": tracking_error_kw,
                "Previous Actual Delta (kW)":
                    dispatch_state["previous_actual_delta_kw"],
                "Feedback Error (kW)":
                    dispatch_state["feedback_error_kw"],
                "Requested Adjustment (kW)":
                    dispatch_state["requested_adjustment_kw"],
                "Applied Adjustment (kW)":
                    dispatch_state["applied_adjustment_kw"],
                "Controller Saturated":
                    dispatch_state["controller_saturated"],

                "Available Capacity in Requested Direction (kW)":
                    dispatch_state["available_requested_kw"],

                "Estimated Dispatched Capacity (kW)":
                    dispatch_state["estimated_dispatch_kw"],

                "Retained Capacity (kW)":
                    dispatch_state["retained_kw"],

                "Requested Dispatch Units":
                    dispatch_state["dispatched_units"],

                "Units Added to LOAD":
                    dispatch_state["added_load"],
                "Units Released from LOAD":
                    dispatch_state["released_load"],
                "Units Added to SHED":
                    dispatch_state["added_shed"],
                "Units Released from SHED":
                    dispatch_state["released_shed"],

                "Actual Average Power (kW)":
                    average_power_kw,

                "Aggregate Power (kW)":
                    aggregate_power_kw,

                "Units in NORMAL":
                    normal_count,

                "Units in SHED":
                    shed_count,

                "Units in LOAD":
                    load_count,

                "Baseline HPWH Fleet Power (kW)":
                    baseline_hpwh_fleet_kw,

                "Controlled HPWH Fleet Power (kW)":
                    controlled_hpwh_fleet_kw,

                "Actual HPWH Delta (kW)":
                    hpwh_actual_delta_kw,

                "Average Tank Temperature (C)":
                    sum(
                        h["last_tank_temp_c"]
                        for h in fleet_data
                    ) / num_homes,
            })

            # ----------------------------------------------------
            # Progress message
            # ----------------------------------------------------

            if (
                step_index % progress_interval == 0
                or step_index == total_steps
            ):
                print(
                    f"Completed {step_index}/{total_steps} steps ",
                    flush=True,
                )

    # ============================================================
    # 5. Finalize Individual Building Results
    # ============================================================

    CTRL_COLS = [
        "Time",
        "Total Electric Power (kW)",
        "Total Electric Energy (kWh)",
        "Temperature - Indoor (C)",
        "Water Heating Electric Power (kW)",
        "Water Heating COP (-)",
        "Water Heating Deadband Upper Limit (C)",
        "Water Heating Deadband Lower Limit (C)",
        "Water Heating Heat Pump COP (-)",
        "Hot Water Average Temperature (C)",
        "Hot Water Outlet Temperature (C)",
    ]

    successful_finalizations = []

    i = 0
    for home_data in fleet_data:
        i += 1

        home_path = home_data["path"]
        building_name = os.path.basename(home_path)

        try:

            results_dir = os.path.join(
                home_path,
                "Results"
            )

            os.makedirs(
                results_dir,
                exist_ok=True
            )

            df_ctrl, _, _ = (
                home_data["sim"].finalize()
            )

            df_ctrl = restore_time_column(
                df_ctrl,
                f"{building_name} controlled"
            )

            # df_ctrl = remove_first_day(
            #     df_ctrl,
            #     Start
            # )

            df_ctrl = df_ctrl[
                [
                    c
                    for c in CTRL_COLS
                    if c in df_ctrl.columns
                ]
            ]

            df_ctrl.to_csv(
                os.path.join(
                    results_dir,
                    "hpwh_controlled.csv"
                ),
                index=False
            )

            successful_finalizations.append(
                home_path
            )

            if i % 50 == 0 or i == len(fleet_data):
                print(
                    f"Finalized {i}/{len(fleet_data)} homes",
                    flush=True
                )
            # print(
            #     f"Building {building_name} results saved",
            #     flush=True
            # )

        except Exception as e:

            failed_home_paths.add(home_path)

            if len(failed_home_paths) == 1:
                print(
                    f"First finalization failure for "
                    f"{building_name}: {repr(e)}",
                    flush=True
                )

    # ============================================================
    # 6. Check Finalization Failure Threshold
    # ============================================================

    failed_count = len(failed_home_paths)

    if failed_count > initial_home_count / 2:
        raise RuntimeError(
            f"Majority of buildings failed by the end of "
            f"the simulation: "
            f"{failed_count}/{initial_home_count}."
        )

    if not successful_finalizations:
        raise RuntimeError(
            "No building results were successfully finalized."
        )

    # ============================================================
    # 7. Aggregate Successful Results
    # ============================================================

    controlled_path = aggregate_results(
        successful_finalizations,
        RESULTS_DIR,
        effective_run_id
    )

    # ============================================================
    # 8. Export VPP State Log
    # ============================================================

    df_vpp_log = pd.DataFrame(
        vpp_state_log
    )

    vpp_log_path = os.path.join(
        RESULTS_DIR,
        effective_run_id + "_VPP_Fleet_States.csv"
    )

    df_vpp_log.to_csv(
        vpp_log_path,
        index=False
    )

    # ============================================================
    # 9. Final Message
    # ============================================================

    return {
        "configuration": configuration,
        "homes_simulated": len(successful_finalizations),
        "homes_failed": failed_count,
        "run_id": effective_run_id,
        "up_regulation_capacity_kw": committed_capacity_kw,
        "down_regulation_capacity_kw": committed_capacity_kw,
        "baseline_up_regulation_capacity_kw": baseline_up_capacity_kw,
        "baseline_down_regulation_capacity_kw": baseline_down_capacity_kw,
        "committed_regulation_capacity_kw": committed_capacity_kw,
        "baseline_path": baseline_path,
        "controlled_path": controlled_path,
        "vpp_log_path": vpp_log_path,
    }

if __name__ == "__main__":
    main()
    print(
        "Simulation finished.",
        flush=True
    )
