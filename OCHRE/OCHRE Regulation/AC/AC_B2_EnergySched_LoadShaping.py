"""
Author: Thomas Metzler
Created: 7/6/26
Dispatches AC load and shed commands to track a normalized regulation signal.
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
import numpy as np

#########################################
# USER SETTINGS
#########################################

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

# Simulation parameters
Start = dt.datetime(2018, 7, 11, 0, 0)
Duration = 2  # days
t_res = 1  # minutes

# The regulation signal is normalized to [-1, 1].  It is converted to a kW
# request using REGULATION_CAPACITY_KW:
#   +1.0 -> increase fleet load by REGULATION_CAPACITY_KW
#   -1.0 -> reduce fleet load by REGULATION_CAPACITY_KW
#    0.0 -> return to the normal thermostat
#
# Set this no higher than the reliably available AC flexibility in the fleet.
# The controller logs availability so this value can be calibrated after a run.
REGULATION_CAPACITY_KW = 25

# Dispatch and comfort settings.  With a one-minute timestep, five minutes is
# a conservative initial minimum command duration.  A home is always released
# if the regulation request reverses direction or returns to zero.
MIN_HOLD_MINUTES = 5
MIN_HOLD_STEPS = max(1, round(MIN_HOLD_MINUTES / t_res))
SHED_MAX_TEMP_F = 76.0
LOAD_MIN_TEMP_F = 71.0
DEFAULT_LOAD_RESPONSE_KW = 3.0  # Used until a home's AC has run once.

RESOLUTION = 0.1      # kW
MAX_OVERSHOOT = 10.0  # kW
TOLERANCE = int(round(0.5 / RESOLUTION))   # ±0.5 kW


SWITCH_COST = 2.0
WEAR_COST = 0.5
COMFORT_COST = 1.0

# HVAC control parameters (°F)
Tcontrol_SHEDF = 76 
Tcontrol_LOADF = 68          
TbaselineF = 72              
TdeadbandF = 2
Tinit = 72                   
count = 0


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


REG_SIGNAL = signal_aggregator_mean()  # Pre-compute the regulation signal for the entire simulation

#########################################
# TEMPERATURE CONVERSIONS F to C
#########################################

def f_to_c(temp_f): 
    return (temp_f - 32) * 5/9

def f_to_c_DB(temp_f):
    return 5/9 * temp_f

Tcontrol_SHEDC = f_to_c(Tcontrol_SHEDF)
Tcontrol_LOADC = f_to_c(Tcontrol_LOADF)
TbaselineC = f_to_c(TbaselineF)
TdeadbandC = f_to_c_DB(TdeadbandF)
SHED_MAX_TEMP_C = f_to_c(SHED_MAX_TEMP_F)
LOAD_MIN_TEMP_C = f_to_c(LOAD_MIN_TEMP_F)

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

    For a shed, the currently operating AC power is the best available
    estimate.  For load, use the home's most recent AC power when available,
    otherwise use a configurable fleet-average starting estimate.
    """
    ac_kw = _clean_power(home.get("last_ac_kw"))
    if mode == "SHED":
        return ac_kw
    return ac_kw if ac_kw > 0 else DEFAULT_LOAD_RESPONSE_KW


def _shed_eligible(home):
    return (
        _clean_power(home.get("last_ac_kw")) > 0.1
        and home.get("last_indoor_temp_c", TbaselineC) <= SHED_MAX_TEMP_C
        and home.get("lockout_steps", 0) == 0
    )


def _load_eligible(home):
    return (
        home.get("last_indoor_temp_c", TbaselineC) >= LOAD_MIN_TEMP_C
        and home.get("lockout_steps", 0) == 0
    )


def load_priority(home):

    temp_margin = home.get("last_indoor_temp_c", TbaselineC) - TbaselineC

    response = _estimated_response_kw(home, "LOAD")

    return (
        temp_margin * response,
        -home.get("dispatch_count",0)
    )

def shed_priority(home):

    response = _estimated_response_kw(home, "SHED")

    temp_margin = TbaselineC - home.get("last_indoor_temp_c", TbaselineC)

    return (
        response,
        temp_margin,
        -home.get("dispatch_count",0)
    )


def dispatch_regulation_signal(fleet_data, reg_sig):
    """Dispatch eligible homes toward the requested kW regulation target.

    Negative signals shed ACs that are currently on.  Positive signals
    pre-cool warm homes.  The selection uses physical state and estimated kW
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
            home["lockout_steps"] -= 1

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
                home["dispatch_kw"] = 0.0

    if target_delta_kw == 0:
        return reg_sig, target_delta_kw, 0.0, 0, 0.0, 0.0

    if requested_mode == "SHED":
        candidates = [home for home in fleet_data if _shed_eligible(home)]
        # Turn off the largest operating units first, subject to comfort.
        
    else:
        candidates = [home for home in fleet_data if _load_eligible(home)]
        # Pre-cool the warmest homes first.
        
    dispatched_kw = retained_kw

    dispatched_units = sum(
        home.get("override") == requested_mode
        for home in fleet_data
    )

    target = max(
        0.0,
        abs(target_delta_kw) - retained_kw
    )

    if target <= 0:
        return (
            reg_sig,
            target_delta_kw,
            retained_kw,
            dispatched_units,
            0.0,
            retained_kw,
        )

    # ---------------------------------------------------
    # Build candidate list
    # ---------------------------------------------------

    dispatch_candidates = []

    for home in candidates:

        # Homes already dispatched and still within their hold period
        # are already counted in retained_kw.
        if home.get("override") == requested_mode:
            continue

        response = _estimated_response_kw(home, requested_mode)

        if response <= 0:
            continue

        # -----------------------
        # Cost Function
        # -----------------------

        cost = 0.0

        # Prefer keeping homes in their current state
        if home.get("override") != requested_mode:
            cost += SWITCH_COST

        # Spread wear across the fleet
        cost += WEAR_COST * np.sqrt(home.get("dispatch_count", 0))

        indoor = home.get("last_indoor_temp_c", TbaselineC)

        if requested_mode == "LOAD":
            margin = max(0.0, indoor - TbaselineC)
        else:
            margin = max(0.0, TbaselineC - indoor)

        # Warm homes are cheaper to precool.
        # Cool homes are cheaper to shed.
        cost += COMFORT_COST * np.exp(-margin)

        dispatch_candidates.append({
            "home": home,
            "response": response,
            "weight": max(
                1,
                int(round(response / RESOLUTION))
            ),
            "cost": cost,
        })

    if not dispatch_candidates:

        return (
            reg_sig,
            target_delta_kw,
            retained_kw,
            dispatched_units,
            0.0,
            retained_kw,
        )

    available_kw = sum(c["response"] for c in dispatch_candidates)

    # ---------------------------------------------------
    # Dynamic Programming
    # ---------------------------------------------------

    target_int = max(
        0,
        int(round(target / RESOLUTION))
    )

    limit = target_int + int(MAX_OVERSHOOT / RESOLUTION)

    #
    # states[power] =
    # {
    #     "cost": ...,
    #     "parent": previous_power,
    #     "candidate": candidate_index
    # }
    #
    states = {
        0: {
            "cost": 0.0,
            "parent": None,
            "candidate": None,
        }
    }

    for i, candidate in enumerate(dispatch_candidates):

        weight = candidate["weight"]
        cost = candidate["cost"]

        current = list(states.items())

        for power, info in current:

            new_power = power + weight

            if new_power > limit:
                continue

            new_cost = info["cost"] + cost

            if (
                new_power not in states
                or new_cost < states[new_power]["cost"]
            ):

                states[new_power] = {
                    "cost": new_cost,
                    "parent": power,
                    "candidate": i,
                }

    # ---------------------------------------------------
    # Choose best solution
    # ---------------------------------------------------

    best_error = min(
        abs(power - target_int)
        for power in states
    )

    candidate_powers = [

        power

        for power in states

        if abs(power - target_int)
        <= best_error + TOLERANCE
    ]

    best_power = min(
        candidate_powers,
        key=lambda p: states[p]["cost"]
    )

    # ---------------------------------------------------
    # Recover selected homes
    # ---------------------------------------------------

    selected = []

    power = best_power

    while power != 0:

        state = states[power]

        if state["candidate"] is None:
            break

        selected.append(state["candidate"])

        power = state["parent"]

    selected.reverse()

    # ---------------------------------------------------
    # Dispatch homes
    # ---------------------------------------------------

    for idx in selected:

        candidate = dispatch_candidates[idx]

        home = candidate["home"]

        response = candidate["response"]

        home["override"] = requested_mode
        home["lockout_steps"] = MIN_HOLD_STEPS
        home["dispatch_kw"] = response
        home["dispatch_count"] = home.get("dispatch_count", 0) + 1

        dispatched_kw += response
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

def determine_hvac_control(global_mode="NORMAL"):
    """
    Highly simplified controller. 
    It purely reacts to the assigned global VPP mode.
    """
    ctrl_signal = {
        'HVAC Cooling': {
            'Setpoint': TbaselineC,
            'Deadband': TdeadbandC,
            'Load Fraction': 1,
        }
    }

    if global_mode == "SHED":
        ctrl_signal['HVAC Cooling'].update({'Setpoint': Tcontrol_SHEDC})
    elif global_mode == "LOAD":
        ctrl_signal['HVAC Cooling'].update({'Setpoint': Tcontrol_LOADC})

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
        "last_ac_kw": 0.0,
        "last_indoor_temp_c": TbaselineC,
    }


def update_home_worker(home_data):
    """Advance one baseline/controlled dwelling pair by one timestep.

    Homes do not share model state, so these updates can run concurrently.
    The fleet override is assigned before this function is called.
    """
    base_ctrl = {
        "HVAC Cooling": {
            "Setpoint": TbaselineC,
            "Deadband": TdeadbandC,
            "Load Fraction": 1,
        }
    }
    base_metrics = home_data["base"].update(control_signal=base_ctrl)

    control_cmd = determine_hvac_control(global_mode=home_data["override"])
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
        "ac_kw": get_metric(ctrl_metrics, home_data["sim"], "HVAC Cooling Electric Power (kW)"),
        "indoor_temp_c": get_metric(ctrl_metrics, home_data["sim"], "Temperature - Indoor (C)"),
    }

#########################################
# MAIN EXECUTION
#########################################

if __name__ == "__main__":
    # --- Directory Setup ---
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(WEATHER_DIR, exist_ok=True)
    
    # Copy homes from defaults
    count2 = 0
    for item in os.listdir(DEFAULT_INPUT):
        count2 += 1
        src = os.path.join(DEFAULT_INPUT, item)
        dst = os.path.join(INPUT_DIR, item)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)
            count += 1
        count += 1
        
    # Copy weather file
    if not os.path.exists(WEATHER_FILE):
        shutil.copy(DEFAULT_WEATHER, WEATHER_FILE)
        count += 1

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

        # Track the regulation signal at every simulation step.  A zero
        # signal returns every AC to its baseline thermostat; there is no
        # separate clock-based event window that can suppress a command.
        (reg_sig, target_delta_kw, estimated_dispatch_kw, dispatched_units,
         available_kw, retained_kw) = dispatch_regulation_signal(fleet_data, raw_reg_sig)

        # The dwellings are independent within this timestep. ``map`` keeps
        # the work bounded and waits for all homes before the next dispatch.
        step_results = list(executor.map(update_home_worker, fleet_data))

        # Store simulated state for the next dispatch.  This is deliberately
        # done only after every parallel worker has completed.
        for home, result in zip(fleet_data, step_results):
            home["last_base_kw"] = _clean_power(result["base_kw"])
            home["last_ctrl_kw"] = _clean_power(result["ctrl_kw"])
            home["last_ac_kw"] = _clean_power(result["ac_kw"])
            home["last_indoor_temp_c"] = result["indoor_temp_c"]

        baseline_fleet_kw = sum(home["last_base_kw"] for home in fleet_data)
        current_step_aggregate_power = sum(home["last_ctrl_kw"] for home in fleet_data)
        actual_delta_kw = current_step_aggregate_power - baseline_fleet_kw
        tracking_error_kw = target_delta_kw - actual_delta_kw
            
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
            "Actual Delta (kW)": actual_delta_kw,
            "Tracking Error (kW)": tracking_error_kw,
            "Baseline Fleet Power (kW)": baseline_fleet_kw,
            "Controlled Fleet Power (kW)": current_step_aggregate_power,
            "Available Capacity in Requested Direction (kW)": available_kw,
            "Estimated Dispatched Capacity (kW)": estimated_dispatch_kw,
            "Retained Capacity (kW)": retained_kw,
            "Requested Dispatch Units": dispatched_units,
            "Actual Average Power (kW)": average_power_kw,
            "Aggregate Power (kW)": aggregate_power_kw,
            "Units in NORMAL": normal_count,
            "Units in SHED": shed_count,
            "Units in LOAD": load_count
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
        "HVAC Cooling Electric Power (kW)", "HVAC Cooling COP (-)",
        "Temperature - Indoor (C)", "HVAC Heating Electric Power (kW)" 
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
    aggregate_results(homes, WORKING_DIR)

    # --- 5. Export VPP State Log ---
    print("Saving VPP state log...")
    df_vpp_log = pd.DataFrame(vpp_state_log)
    vpp_log_path = os.path.join(WORKING_DIR, filename + "_VPP_Fleet_States.csv")
    df_vpp_log.to_csv(vpp_log_path, index=False)
    print(f"VPP State Log saved to: {vpp_log_path}")
