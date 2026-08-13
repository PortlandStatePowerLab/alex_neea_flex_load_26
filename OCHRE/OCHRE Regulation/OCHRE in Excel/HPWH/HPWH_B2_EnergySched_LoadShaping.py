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

#########################################
# USER SETTINGS
#########################################
#Gallons, MLU, MLU duration, Shed duration, ELU, ELU duration, Shed duration, Offset sheds 
filename = '2025_All_630_1_45_1700_1_45_OS'

#"HPWH 50 Input Files", "HPWH 66 Input Files/bldg", "HPWH 80 Input Files", "HPWH All Input Files/bldg"
Input_folder = "HPWH All Portland Input Files"

# Original OCHRE defaults folder
ochre_dir = Path(ochre.__file__).resolve().parent
DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
print("OCHRE installed at:", ochre_dir)
print(DEFAULT_INPUT)

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

# The calculator-owned signal folder is the direct parent of HPWH.
REG_DIR = os.path.join(EXCEL_DIR, "Reg Sig")
REG_ADDRESS = "RegA-ochre.csv"


# Simulation parameters
Start = dt.datetime(2018, 1, 11, 0, 0)
Duration = 2  # days
t_res = 30.0  # minutes


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

    os.makedirs(REG_DIR, exist_ok=True)

    saved_sig.to_csv(
        os.path.join(REG_DIR, "rega_filtered.csv"),
        index=False
    )

    print("file saved!")


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

    # A neutral or reversed request releases old commands immediately.  For a
    # continuing request, retain homes that are still within their hold time.
    retained_kw = 0.0
    for home in fleet_data:
        if home.get("lockout_steps", 0) > 0:
            home["lockout_steps"] = max(0, home["lockout_steps"] - CONTROL_INTERVAL_STEPS)

        if target_delta_kw == 0 or home.get("override") != requested_mode:
            home["override"] = "NORMAL"
            home["lockout_steps"] = 0
        elif home.get("override") == requested_mode:
            if home.get("lockout_steps", 0) > 0:
                retained_kw += home.get("dispatch_kw", _estimated_response_kw(home, requested_mode))
            else:
                # Its minimum hold has ended; re-evaluate it with the rest of
                # the fleet instead of silently leaving an old command active.
                home["override"] = "NORMAL"

    if target_delta_kw == 0:
        return reg_sig, target_delta_kw, 0.0, 0, 0.0, 0.0

    if requested_mode == "SHED":
        candidates = [home for home in fleet_data if _shed_eligible(home)]
        # Turn off the largest operating units first, subject to comfort.
        candidates.sort(key=lambda home: (-_estimated_response_kw(home, "SHED"), home.get("dispatch_count", 0)))
    else:
        candidates = [home for home in fleet_data if _load_eligible(home)]
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
    
    if dropped_columns:
        print(f"Dropped invalid schedules for {home_path}: {dropped_columns}")

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

def remove_first_day(df, start_date):
    if 'Time' not in df.columns:
        df = df.reset_index()
        if 'index' in df.columns:
            df.rename(columns={'index': 'Time'}, inplace=True)
    df['Time'] = pd.to_datetime(df['Time'], errors='coerce')
    first_day_end = start_date + pd.Timedelta(days=1)
    return df[df['Time'] >= first_day_end].copy()

def aggregate_results(homes, work_dir):
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
        df_ctrl_all.to_csv(os.path.join(work_dir, filename + "_controlled.csv"), index=False)

    if all_base:
        df_base_all = pd.concat(all_base, ignore_index=True)
        df_base_all.to_csv(os.path.join(work_dir, filename + "_baseline.csv"), index=False)
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

def init_fleet_worker(home):
    """Worker function to initialize dwellings in parallel"""
    base_dw, sim_dw = initialize_home(home, WEATHER_FILE)
    return {
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


def update_home_worker(home_data):
    """Advance one baseline/controlled dwelling pair by one timestep.

    Homes do not share model state, so these updates can run concurrently.
    The fleet override is assigned before this function is called.
    """
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
        "base_kw": get_metric(base_metrics, home_data["base"], "Total Electric Power (kW)"),
        "ctrl_kw": get_metric(ctrl_metrics, home_data["sim"], "Total Electric Power (kW)"),
        "ctrl_hpwh_kw": get_metric(ctrl_metrics, home_data["sim"], "Water Heating Electric Power (kW)"),
        "tank_temp_c": get_metric(ctrl_metrics, home_data["sim"], "Water Heating Control Temperature (C)"),
        "base_hpwh_kw": get_metric(base_metrics, home_data["base"], "Water Heating Electric Power (kW)"),
    }

#########################################
# MAIN EXECUTION
#########################################

def main(parameters=None):
    """Run the HPWH B2 fleet simulation using calculator parameters."""
    global REG_SIGNAL
    configuration = configure(parameters)
    REG_SIGNAL = signal_aggregator_mean()
    print(f"B2 calculator parameters applied: {configuration['applied']}")
    if configuration["handled_by_a3"]:
        print(f"B2 parameters already applied to HPXML by A3: {configuration['handled_by_a3']}")

    # --- Directory Setup ---
    if not os.path.isdir(INPUT_DIR):
        raise FileNotFoundError(
            f"HPWH XML fleet not found: {INPUT_DIR}. Run A3 first to create it."
        )
    if not os.path.isfile(WEATHER_FILE):
        raise FileNotFoundError(f"Weather file not found: {WEATHER_FILE}")
    if not os.path.isdir(METADATA_DIR):
        raise FileNotFoundError(f"Metadata directory not found: {METADATA_DIR}")

    homes = find_all_homes(INPUT_DIR)
    print(f"Found {len(homes)} homes")

    # --- 1. Parallel Fleet Initialization ---
    fleet_data = []
    print("Initializing dwellings (in parallel)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(init_fleet_worker, home) for home in homes]
        for f in concurrent.futures.as_completed(futures):
            try:
                fleet_data.append(f.result())
            except Exception as e:
                print("Initialization failed:", e)

    if not fleet_data:
        print("No dwellings were initialized. Exiting.")
        exit()

    num_homes = len(fleet_data)
    
    # --- 2. Co-Simulation Time Loop Setup ---
    sim_times = fleet_data[0]["base"].sim_times
    average_power_kw = 0.0

    vpp_state_log = [] # Add this line to initialize the log

    total_steps = len(sim_times)
    progress_interval = max(1, int(60 / t_res))  # report once per simulation hour
    print(f"Starting Co-Simulation Time Loop ({total_steps} steps)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
      for step_index, sim_time in enumerate(sim_times, start=1):
        raw_reg_sig = get_reg_sig(sim_time)

        # Re-evaluate dispatch only at the calculator's requested control
        # interval.  OCHRE still advances every timestep using the most recent
        # command between controller decisions.
        if (step_index - 1) % CONTROL_INTERVAL_STEPS == 0:
            (reg_sig, target_delta_kw, estimated_dispatch_kw, dispatched_units,
             available_kw, retained_kw) = dispatch_regulation_signal(fleet_data, raw_reg_sig)
        else:
            try:
                reg_sig = float(raw_reg_sig)
            except (TypeError, ValueError):
                reg_sig = 0.0
            if pd.isna(reg_sig):
                reg_sig = 0.0
            reg_sig = max(-1.0, min(1.0, reg_sig))
            target_delta_kw = reg_sig * REGULATION_CAPACITY_KW
            active_mode = "LOAD" if target_delta_kw > 0 else "SHED"
            active_homes = [
                home for home in fleet_data if home.get("override") == active_mode
            ]
            estimated_dispatch_kw = sum(home.get("dispatch_kw", 0.0) for home in active_homes)
            dispatched_units = len(active_homes)
            available_kw = sum(
                _estimated_response_kw(home, active_mode)
                for home in fleet_data
                if (_load_eligible(home) if active_mode == "LOAD" else _shed_eligible(home))
            )
            retained_kw = estimated_dispatch_kw

        # The dwellings are independent within this timestep. ``map`` keeps
        # the work bounded and waits for all homes before the next dispatch.
        step_results = list(executor.map(update_home_worker, fleet_data))

        # Store simulated state for the next dispatch.  This is deliberately
        # done only after every parallel worker has completed.
        for home, result in zip(fleet_data, step_results):
            home["last_base_kw"] = _clean_power(result["base_kw"])
            home["last_ctrl_kw"] = _clean_power(result["ctrl_kw"])
            # ``update_home_worker`` reports baseline and controlled HPWH
            # power separately.  Dispatch eligibility must use the most
            # recent controlled HPWH power, not a nonexistent generic key.
            home["last_hpwh_kw"] = _clean_power(result["ctrl_hpwh_kw"])
            home["last_tank_temp_c"] = result["tank_temp_c"]
            home["last_base_hpwh_kw"] = _clean_power(result["base_hpwh_kw"])
            home["last_ctrl_hpwh_kw"] = _clean_power(result["ctrl_hpwh_kw"])
        baseline_hpwh_fleet_kw = sum(h["last_base_hpwh_kw"] for h in fleet_data)
        controlled_hpwh_fleet_kw = sum(h["last_ctrl_hpwh_kw"] for h in fleet_data)
        hpwh_actual_delta_kw = controlled_hpwh_fleet_kw - baseline_hpwh_fleet_kw        
        current_step_aggregate_power = sum(home["last_ctrl_kw"] for home in fleet_data)
        # actual_delta_kw = current_step_aggregate_power - baseline_fleet_kw
        # tracking_error_kw = target_delta_kw - actual_delta_kw
        tracking_error_kw = target_delta_kw - hpwh_actual_delta_kw

        # Recalculate average fleet power for the next time step's logic
        aggregate_power_kw = current_step_aggregate_power
        average_power_kw = aggregate_power_kw / num_homes

        # --- NEW: Log Fleet States for this Timestep ---
        shed_count = sum(1 for h in fleet_data if h["override"] == "SHED")
        load_count = sum(1 for h in fleet_data if h["override"] == "LOAD")
        normal_count = sum(1 for h in fleet_data if h["override"] == "NORMAL")
        
        vpp_state_log.append({
            "Time": sim_time,
            "Regulation Signal": reg_sig,
            "Regulation Capacity (kW)": REGULATION_CAPACITY_KW,
            "Target Delta (kW)": target_delta_kw,
            "Actual Delta (kW)": hpwh_actual_delta_kw,
            "Tracking Error (kW)": tracking_error_kw,
            # "Baseline Fleet Power (kW)": baseline_fleet_kw,
            # "Controlled Fleet Power (kW)": current_step_aggregate_power,
            "Available Capacity in Requested Direction (kW)": available_kw,
            "Estimated Dispatched Capacity (kW)": estimated_dispatch_kw,
            "Retained Capacity (kW)": retained_kw,
            "Requested Dispatch Units": dispatched_units,
            "Actual Average Power (kW)": average_power_kw,
            "Aggregate Power (kW)": aggregate_power_kw,
            "Units in NORMAL": normal_count,
            "Units in SHED": shed_count,
            "Units in LOAD": load_count,
            "Baseline HPWH Fleet Power (kW)": baseline_hpwh_fleet_kw,
            "Controlled HPWH Fleet Power (kW)": controlled_hpwh_fleet_kw,
            "Actual HPWH Delta (kW)": hpwh_actual_delta_kw,
            "Average Tank Temperature (C)": sum(h["last_tank_temp_c"] for h in fleet_data) / num_homes
        })

        if step_index % progress_interval == 0 or step_index == total_steps:
            print(
                f"Completed {step_index}/{total_steps} steps "
                f"({sim_time:%Y-%m-%d %H:%M})",
                flush=True,
            )

    # --- 3. Finalize and Output Data ---
    print("Simulation complete! Finalizing results...")
    
    CTRL_COLS = [
        "Time", "Total Electric Power (kW)", "Total Electric Energy (kWh)",
        "Temperature - Indoor (C)", 
        "Water Heating Electric Power (kW)",
        "Water Heating COP (-)",
        "Water Heating Deadband Upper Limit (C)",
        "Water Heating Deadband Lower Limit (C)",
        "Water Heating Heat Pump COP (-)",
        "Water Heating Control Temperature (C)",
        "Hot Water Outlet Temperature (C)"
    ]
    
    for home_data in fleet_data:
        home_path = home_data["path"]
        results_dir = os.path.join(home_path, "Results")
        os.makedirs(results_dir, exist_ok=True)
        
        df_base, _, _ = home_data["base"].finalize()
        df_ctrl, _, _ = home_data["sim"].finalize()
        
        df_base = remove_first_day(df_base, Start)
        df_ctrl = remove_first_day(df_ctrl, Start)
        
        df_ctrl = df_ctrl[[c for c in CTRL_COLS if c in df_ctrl.columns]]
        df_base = df_base[[c for c in CTRL_COLS if c in df_base.columns]]
        
        df_ctrl.to_csv(os.path.join(results_dir, 'hpwh_controlled.csv'), index=False)
        df_base.to_csv(os.path.join(results_dir, 'hpwh_baseline.csv'), index=False)

    # --- 4. Aggregate ---
    aggregate_results(homes, RESULTS_DIR)

    # --- 5. Export VPP State Log ---
    print("Saving VPP state log...")
    df_vpp_log = pd.DataFrame(vpp_state_log)
    vpp_log_path = os.path.join(RESULTS_DIR, filename + "_VPP_Fleet_States.csv")
    df_vpp_log.to_csv(vpp_log_path, index=False)
    print(f"VPP State Log saved to: {vpp_log_path}")
    return {
        "configuration": configuration,
        "homes_simulated": num_homes,
        "vpp_log_path": vpp_log_path,
    }


if __name__ == "__main__":
    main()
