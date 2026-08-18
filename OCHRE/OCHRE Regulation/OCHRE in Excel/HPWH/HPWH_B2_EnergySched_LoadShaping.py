"""
Author: Thomas Metzler
Created: 7/6/26
Dispatches HPWH load and shed commands to track a normalized regulation signal.
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
filename = 'hpwh_test_8_18_2026'

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
WEATHER_DIR = os.path.join(EXCEL_DIR, "Weather")
WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
METADATA_DIR = os.path.join(OCHRE_DIR, "Metadata")
XML_ADDRESS = "home.xml"
CSV_ADDRESS = "in.schedules.csv"


REG_TYPE = 'RegA'
# The calculator-owned signal folder is the direct parent of HPWH.
REG_DIR = os.path.join(EXCEL_DIR, "Reg Sig")
REG_ADDRESS = f"{REG_TYPE}-ochre.csv"


# Simulation parameters
Start = dt.datetime(2018, 1, 11, 0, 0)
Duration = 2  # days
t_res = 1.0  # minutes

NUM_HOMES = 10

# The regulation signal is normalized to [-1, 1].  It is converted to a kW
# request using REGULATION_CAPACITY_KW:
#   +1.0 -> increase fleet load by REGULATION_CAPACITY_KW
#   -1.0 -> reduce fleet load by REGULATION_CAPACITY_KW
#    0.0 -> return to the normal thermostat
#
# Set this no higher than the reliably available HPWH flexibility in the fleet.
# The controller logs availability so this value can be calibrated after a run.
REGULATION_CAPACITY_KW = 200.0

# Dispatch and comfort settings.  With a one-minute timestep, five minutes is
# a conservative initial minimum command duration.  A home is always released
# if the regulation request reverses direction or returns to zero.
MIN_HOLD_MINUTES = 5
MIN_HOLD_STEPS = max(1, round(MIN_HOLD_MINUTES / t_res))
CONTROL_INTERVAL_MINUTES = 1
CONTROL_INTERVAL_STEPS = max(1, round(CONTROL_INTERVAL_MINUTES / t_res))
# SHED_MAX_TEMP_F = 76.0
# LOAD_MIN_TEMP_F = 71.0
# DEFAULT_LOAD_RESPONSE_KW = 3.0  # Used until a home's AC has run once.
SHED_MIN_TANK_TEMP_F = 120
LOAD_TARGET_TANK_TEMP_F = 130
DEFAULT_LOAD_RESPONSE_KW = 3.0

# Limit the number of previously shed HPWHs returned to normal per control
# interval. This spreads thermal recovery instead of releasing the fleet at once.
MAX_SHED_RELEASES_PER_INTERVAL = 4


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

    global DEFAULT_LOAD_RESPONSE_KW, SHED_MIN_TANK_TEMP_F
    global LOAD_TARGET_TANK_TEMP_F, Tcontrol_SHEDF, Tcontrol_LOADF
    global MIN_HOLD_MINUTES, CONTROL_INTERVAL_MINUTES

    applied = []
    if parameters.get("comp_pwr") not in (None, ""):
        DEFAULT_LOAD_RESPONSE_KW = _positive_number("comp_pwr", parameters["comp_pwr"])
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


REG_SIGNAL = signal_aggregator_mean()

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


def _estimated_response_kw(home, mode):
    """Estimate the incremental response from dispatching one home.

    For a shed, the currently operating HPWH power is the best available
    estimate.  For load, use the home's most recent HPWH power when available,
    otherwise use a configurable fleet-average starting estimate.
    """
    hpwh_kw = _clean_power(home.get("last_hpwh_kw"))
    if mode == "SHED":
        return hpwh_kw
    return hpwh_kw if hpwh_kw > 0 else DEFAULT_LOAD_RESPONSE_KW


def _shed_eligible(home):
    return (
        _clean_power(home.get("last_hpwh_kw")) > 0.1
        and home.get("last_tank_temp_c", TbaselineC) >= SHED_MIN_TANK_TEMP_C
        and home.get("lockout_steps", 0) == 0
    )


def _load_eligible(home):
    return (
        home.get("last_tank_temp_c", TbaselineC) <= LOAD_TARGET_TANK_TEMP_C
        and home.get("lockout_steps", 0) == 0
    )


def dispatch_regulation_signal(fleet_data, reg_sig):
    """Dispatch eligible homes toward the requested kW regulation target.

    Negative signals shed HPWHs that are currently on.  Positive signals
    preheat cooler tanks.  The selection uses physical state and estimated kW
    response rather than a fixed percentage of all homes.
    """
    try:
        reg_sig = float(reg_sig)
    except (TypeError, ValueError):
        reg_sig = 0.0

    if pd.isna(reg_sig):
        reg_sig = 0.0
    reg_sig = max(-1.0, min(1.0, reg_sig))

    target_delta_kw = reg_sig * REGULATION_CAPACITY_KW
    requested_mode = "LOAD" if target_delta_kw > 0 else "SHED"

    # A SHED request may end abruptly. Do not release every shed home at once:
    # hold the remaining shed homes temporarily and return only a small batch
    # to normal operation each control interval.
    retained_kw = 0.0

    for home in fleet_data:
        home["released_this_interval"] = False

        if home.get("lockout_steps", 0) > 0:
            home["lockout_steps"] = max(
                0,
                home["lockout_steps"] - CONTROL_INTERVAL_STEPS
            )

        # On a neutral or positive request, keep SHED homes in their present
        # state for now. They are released below in controlled batches.
        if (
            home.get("override") == "SHED"
            and target_delta_kw >= 0
        ):
            continue

        # Other incompatible commands can still be released immediately.
        if target_delta_kw == 0 or home.get("override") != requested_mode:
            home["override"] = "NORMAL"
            home["lockout_steps"] = 0

        elif home.get("override") == requested_mode:
            if home.get("lockout_steps", 0) > 0:
                retained_kw += home.get(
                    "dispatch_kw",
                    _estimated_response_kw(home, requested_mode)
                )
            else:
                home["override"] = "NORMAL"

    # Gradually release shed homes when the request is neutral or turns into
    # a positive/load request. Always release tanks at or below the comfort
    # threshold, even if that exceeds the normal batch size.
    if target_delta_kw >= 0:
        shed_homes = [
            home for home in fleet_data
            if home.get("override") == "SHED"
        ]

        urgent_releases = [
            home for home in shed_homes
            if home.get("last_tank_temp_c", TbaselineC)
            <= SHED_MIN_TANK_TEMP_C
        ]

        normal_releases = [
            home for home in shed_homes
            if home not in urgent_releases
        ]

        # Release cooler tanks first for comfort. Dispatch count breaks ties
        # so the same homes are not always favored.
        normal_releases.sort(
            key=lambda home: (
                home.get("last_tank_temp_c", TbaselineC),
                home.get("dispatch_count", 0),
            )
        )

        selected_releases = urgent_releases + normal_releases[
            :max(0, MAX_SHED_RELEASES_PER_INTERVAL - len(urgent_releases))
        ]

        for home in selected_releases:
            home["override"] = "NORMAL"
            home["lockout_steps"] = 0
            home["released_this_interval"] = True

    if target_delta_kw == 0:
        return reg_sig, target_delta_kw, 0.0, 0, 0.0, 0.0

    if requested_mode == "SHED":
        candidates = [
            home for home in fleet_data
            if (
                home.get("override") == "NORMAL"
                and not home.get("released_this_interval", False)
                and _shed_eligible(home)
            )
        ]
        # Turn off the largest operating units first, subject to comfort.
        candidates.sort(key=lambda home: (-_estimated_response_kw(home, "SHED"), home.get("dispatch_count", 0)))
    else:
        candidates = [
            home for home in fleet_data
            if (
                home.get("override") == "NORMAL"
                and not home.get("released_this_interval", False)
                and _load_eligible(home)
            )
        ]
        # Pre-cool the warmest homes first.
        candidates.sort(key=lambda home: (home.get("last_tank_temp_c", TbaselineC), home.get("dispatch_count", 0)))

    available_kw = sum(_estimated_response_kw(home, requested_mode) for home in candidates)
    dispatched_kw = retained_kw
    dispatched_units = sum(home.get("override") == requested_mode for home in fleet_data)

    for home in candidates:
        if dispatched_kw >= abs(target_delta_kw):
            break
        response_kw = _estimated_response_kw(home, requested_mode)
        home["override"] = requested_mode
        home["lockout_steps"] = MIN_HOLD_STEPS
        home["dispatch_kw"] = response_kw
        home["dispatch_count"] += 1
        dispatched_kw += response_kw
        dispatched_units += 1

    return (reg_sig, target_delta_kw, dispatched_kw, dispatched_units,
            available_kw, retained_kw)

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


def aggregate_results(homes, work_dir, run_id):
    all_ctrl, all_base = [], []
    for home in homes:
        results_dir = os.path.join(home, "Results")
        ctrl_file = os.path.join(results_dir, "hpwh_controlled.csv")
        base_file = os.path.join(results_dir, "hpwh_baseline.csv")
        
        if os.path.exists(ctrl_file):
            df_ctrl = pd.read_csv(ctrl_file)
            df_ctrl["Home"] = os.path.basename(home)
            all_ctrl.append(df_ctrl)

        if os.path.exists(base_file):
            df_base = pd.read_csv(base_file)
            df_base["Home"] = os.path.basename(home)
            all_base.append(df_base)

    if all_ctrl:
        df_ctrl_all = pd.concat(all_ctrl, ignore_index=True)
        df_ctrl_all.to_csv(os.path.join(work_dir, run_id + "_controlled.csv"), index=False)

    if all_base:
        df_base_all = pd.concat(all_base, ignore_index=True)
        df_base_all.to_csv(os.path.join(work_dir, run_id + "_baseline.csv"), index=False)
    print(f"Aggregated CSVs written!")

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
        "verbosity": 6,
        "Equipment": {
            "Water Heating": {
                "Initial Temperature (C)": TinitC,
                "hp_only_mode": True,
                "Max Tank Temperature": MAX_TANK_TEMPERATURE_C,
                "Upper Node": 3,
                "Lower Node": 10,
                "Upper Node Weight": 0.75,
            },
        },
    }

    base_dwelling = Dwelling(name=f"Base_{os.path.basename(home_path)}", **dwelling_args_local)
    sim_dwelling = Dwelling(name=f"Ctrl_{os.path.basename(home_path)}", **dwelling_args_local)
    return base_dwelling, sim_dwelling

def init_fleet_worker(home, build_num, num_builds):
    """Worker function to initialize dwellings in parallel."""

    try:
        base_dw, sim_dw = initialize_home(
            home,
            WEATHER_FILE
        )

        return {
            "success": True,
            "base": base_dw,
            "sim": sim_dw,
            "path": home,
            "override": "NORMAL",
            "lockout_steps": 0,
            "dispatch_count": 0,
            "dispatch_kw": 0.0,
            "last_base_kw": 0.0,
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
    """Advance one baseline/controlled dwelling pair by one timestep."""

    building_name = os.path.basename(home_data["path"])

    try:
        base_ctrl = {
            "Water Heating": {
                "Setpoint": TbaselineC,
                "Deadband": TdeadbandC,
                "Load Fraction": 1,
            }
        }
        base_metrics = home_data["base"].update(control_signal=base_ctrl)

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
            "base_kw": get_metric(base_metrics, home_data["base"], "Total Electric Power (kW)"),
            "ctrl_kw": get_metric(ctrl_metrics, home_data["sim"], "Total Electric Power (kW)"),
            "ctrl_hpwh_kw": get_metric(ctrl_metrics, home_data["sim"], "Water Heating Electric Power (kW)"),
            "tank_temp_c": get_metric(ctrl_metrics, home_data["sim"], "Water Heating Control Temperature (C)"),
            "base_hpwh_kw": get_metric(base_metrics, home_data["base"], "Water Heating Electric Power (kW)"),
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

def main(parameters=None, run_id=None):
    """Run the HPWH B2 fleet simulation using calculator parameters."""

    global REG_SIGNAL

    effective_run_id = run_id or filename

    # ============================================================
    # 0. Configuration
    # ============================================================

    configuration = configure(parameters)
    REG_SIGNAL = signal_aggregator_mean()

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

    homes = find_all_homes(INPUT_DIR)
    homes = homes[:NUM_HOMES]

    if not homes:
        raise RuntimeError(
            f"No valid homes found in {INPUT_DIR}."
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
                initial_home_count
            )
            for i, home in enumerate(homes, start=1)
        ]

        pending = set(futures)

        first_building_initialized = False
        last_report_time = None
        last_reported_count = 0

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

                print(
                    f"{initialized_count} / "
                    f"{initial_home_count} homes initialized",
                    flush=True
                )

            # Report every 5 seconds.
            elif (
                first_building_initialized
                and time.monotonic() - last_report_time >= 8
            ):

                if initialized_count != last_reported_count:

                    print(
                        f"{initialized_count} / "
                        f"{initial_home_count} homes initialized",
                        flush=True
                    )

                    last_reported_count = initialized_count

                last_report_time = time.monotonic()

        # Always report the final count.
        initialized_count = len(fleet_data)

        if initialized_count != last_reported_count:

            print(
                f"{initialized_count} / "
                f"{initial_home_count} homes initialized",
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

    sim_times = fleet_data[0]["base"].sim_times

    average_power_kw = 0.0
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

                (
                    reg_sig,
                    target_delta_kw,
                    estimated_dispatch_kw,
                    dispatched_units,
                    available_kw,
                    retained_kw,
                ) = dispatch_regulation_signal(
                    fleet_data,
                    raw_reg_sig
                )

            else:

                try:
                    reg_sig = float(raw_reg_sig)
                except (TypeError, ValueError):
                    reg_sig = 0.0

                if pd.isna(reg_sig):
                    reg_sig = 0.0

                reg_sig = max(-1.0, min(1.0, reg_sig))

                target_delta_kw = (
                    reg_sig * REGULATION_CAPACITY_KW
                )

                active_mode = (
                    "LOAD"
                    if target_delta_kw > 0
                    else "SHED"
                )

                active_homes = [
                    home
                    for home in fleet_data
                    if home.get("override") == active_mode
                ]

                estimated_dispatch_kw = sum(
                    home.get("dispatch_kw", 0.0)
                    for home in active_homes
                )

                dispatched_units = len(active_homes)

                available_kw = sum(
                    _estimated_response_kw(
                        home,
                        active_mode
                    )
                    for home in fleet_data
                    if (
                        _load_eligible(home)
                        if active_mode == "LOAD"
                        else _shed_eligible(home)
                    )
                )

                retained_kw = estimated_dispatch_kw

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
                home["last_base_kw"] = _clean_power(
                    result["base_kw"]
                )

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
                    result["base_hpwh_kw"]
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
                "Regulation Capacity (kW)": REGULATION_CAPACITY_KW,
                "Target Delta (kW)": target_delta_kw,
                "Actual Delta (kW)": hpwh_actual_delta_kw,
                "Tracking Error (kW)": tracking_error_kw,

                "Available Capacity in Requested Direction (kW)":
                    available_kw,

                "Estimated Dispatched Capacity (kW)":
                    estimated_dispatch_kw,

                "Retained Capacity (kW)":
                    retained_kw,

                "Requested Dispatch Units":
                    dispatched_units,

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
        "Water Heating Control Temperature (C)",
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

            df_base, _, _ = (
                home_data["base"].finalize()
            )

            df_ctrl, _, _ = (
                home_data["sim"].finalize()
            )

            df_base = restore_time_column(
                df_base,
                f"{building_name} baseline"
            )

            df_ctrl = restore_time_column(
                df_ctrl,
                f"{building_name} controlled"
            )

            # df_base = remove_first_day(
            #     df_base,
            #     Start
            # )

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

            df_base = df_base[
                [
                    c
                    for c in CTRL_COLS
                    if c in df_base.columns
                ]
            ]

            df_ctrl.to_csv(
                os.path.join(
                    results_dir,
                    "hpwh_controlled.csv"
                ),
                index=False
            )

            df_base.to_csv(
                os.path.join(
                    results_dir,
                    "hpwh_baseline.csv"
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

    aggregate_results(
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

    print(
        "Simulation finished.",
        flush=True
    )

    return {
        "configuration": configuration,
        "homes_simulated": len(successful_finalizations),
        "homes_failed": failed_count,
        "run_id": effective_run_id,
        "vpp_log_path": vpp_log_path,
    }

if __name__ == "__main__":
    main()
